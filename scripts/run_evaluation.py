"""M14: run the simulated evaluation and record it.

    python scripts/run_evaluation.py --seed 42
    python scripts/run_evaluation.py --seed 42 --preset hard
    python scripts/run_evaluation.py --seed 7 --trials 500 --remediation-trials 100

Each run writes experiments/runs/<UTC time>-seed<seed>/ with:
    config.json   every parameter, the git commit and the methods used
    results.json  all metrics for the proposed pipeline and the baseline (+ per-case details)
    report.md     the same numbers as tables

The proposed pipeline is the real integration API (in-process, temporary database). The
baseline is a conventional NMS on the SAME inputs: one ticket per alert, the alerting device
is the "cause", a fixed latency threshold, and "restart then close the ticket".

Everything here is a SIMULATED environment with injected, labelled faults. Report it as such.
MTTD and MTTR are not measured here; they need timings from the live Zabbix deployment.
"""
import argparse
import json
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "integration-api", ROOT, ROOT / "test-environment" / "fault-scenarios",
          ROOT / "test-environment" / "simulators"):
    sys.path.insert(0, str(p))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.zabbix_api import ZabbixApiClient  # noqa: E402
from generator import PRESETS, correlation_scenario, latency_series  # noqa: E402
from intelligence import anomaly, correlation, rca  # noqa: E402
from intelligence.anomaly.evaluate import confusion  # noqa: E402
from intelligence.evaluation import alert_reduction, grouping_scores, rate, top_k_hit  # noqa: E402
from test_service import ServiceState  # noqa: E402

STATIC_LATENCY_THRESHOLD_MS = 100.0
CORRELATION_WINDOW_SECONDS = 120


def device_body(device_id: str, kind: str, **extra) -> dict:
    profile, dtype = {
        "switch": ("network_switch_basic", "network_switch"),
        "camera": ("ip_camera_basic", "ip_camera"),
        "service": ("test_service_basic", "test_service"),
    }[kind]
    return {"device_id": device_id, "name": device_id, "device_type": dtype, "profile_id": profile,
            "organization_id": "SIM", "site_id": "SIM", "zone_id": "SIM",
            "management_address": "<simulated>", "responsible_team": "sim", **extra}


def must(r: httpx.Response, *ok: int) -> dict | list:
    if r.status_code not in (ok or (200, 201)):
        raise RuntimeError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text}")
    return r.json()


# ---------------------------------------------------------------- correlation + RCA

def group_kind(group: list[str], cause: str, events: dict[str, dict]) -> str:
    if cause.startswith("SW-"):
        return "switch_outage" if any(events[e]["device_id"] == cause for e in group) else "silent_switch_outage"
    return "camera_failure"


def evaluate_correlation(seed: int, trials: int, workdir: Path, preset: dict) -> dict:
    sc = correlation_scenario(seed, trials, spacing_seconds=preset["spacing_seconds"],
                              max_cascade_delay=preset["max_cascade_delay"],
                              missing_alert_probability=preset["missing_alert_probability"])
    events = {e["event_id"]: e for e in sc.events}
    settings = Settings(database_path=workdir / "corr.sqlite", profiles_dir=ROOT / "device-profiles")
    with TestClient(create_app(settings)) as client:
        for d in sc.devices:
            must(client.post("/devices", json=device_body(d["device_id"], d["kind"])), 201)
        for child, parent in sc.edges:
            must(client.post("/topology/edges", json={"from_device_id": child, "to_device_id": parent}), 201)
        for e in sc.events:
            must(client.post("/events", json=e), 201)
        must(client.post(f"/incidents/sync?window_seconds={CORRELATION_WINDOW_SECONDS}"))
        incidents = must(client.get("/incidents"))

    by_event = {eid: inc for inc in incidents for eid in inc["event_ids"]}
    proposed_groups = [inc["event_ids"] for inc in incidents]
    baseline_groups = [[eid] for eid in events]

    per_kind: dict[str, dict[str, int]] = {}
    totals = {"proposed_top1": 0, "proposed_top3": 0, "baseline_top1": 0, "baseline_top3": 0}
    cases = []
    for group in sc.truth_groups:
        key = group[0]
        cause = sc.truth_causes[key]
        kind = group_kind(group, cause, events)
        inc = by_event[key]
        ranked = [c["device_id"] for c in inc["rca"]["ranked_causes"]]
        baseline_ranked = [events[key]["device_id"]]
        hits = {"proposed_top1": top_k_hit(ranked, cause, 1), "proposed_top3": top_k_hit(ranked, cause, 3),
                "baseline_top1": top_k_hit(baseline_ranked, cause, 1),
                "baseline_top3": top_k_hit(baseline_ranked, cause, 3)}
        k = per_kind.setdefault(kind, {"cases": 0, **{h: 0 for h in hits}})
        k["cases"] += 1
        for h, v in hits.items():
            k[h] += v
            totals[h] += v
        cases.append({"truth_key": key, "kind": kind, "true_cause": cause,
                      "predicted_incident": inc["incident_id"], "ranked": ranked[:3], **hits})

    n = len(sc.truth_groups)
    gp, gb = grouping_scores(sc.truth_groups, proposed_groups), grouping_scores(sc.truth_groups, baseline_groups)
    return {
        "params": sc.params | {"correlation_window_seconds": CORRELATION_WINDOW_SECONDS},
        "raw_alerts": len(events),
        "true_incidents": n,
        "proposed": {
            "incidents_or_tickets": len(incidents),
            "alert_reduction_percent": alert_reduction(len(events), len(incidents)),
            "grouping": gp.__dict__,
            "rca_top1_accuracy": rate(totals["proposed_top1"], n),
            "rca_top3_accuracy": rate(totals["proposed_top3"], n),
        },
        "baseline": {
            "incidents_or_tickets": len(events),
            "alert_reduction_percent": 0.0,
            "grouping": gb.__dict__,
            "rca_top1_accuracy": rate(totals["baseline_top1"], n),
            "rca_top3_accuracy": rate(totals["baseline_top3"], n),
        },
        "by_kind": {kind: {"cases": v["cases"],
                           "proposed_top1": rate(v["proposed_top1"], v["cases"]),
                           "baseline_top1": rate(v["baseline_top1"], v["cases"])}
                    for kind, v in sorted(per_kind.items())},
        "cases": cases,
    }


# ---------------------------------------------------------------- anomaly detection

def evaluate_anomaly(seed: int, preset: dict, warmup: int = 30) -> dict:
    series = latency_series(seed, warmup=warmup, spike_range=preset["spike_range"], jitter=preset["jitter"])
    pred_p, pred_b, truth = [], [], []
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for s in series:
        readings = [anomaly.Reading(t0 + timedelta(minutes=i), v) for i, v in enumerate(s.values)]
        scored = {r.timestamp: r.is_anomaly for r in anomaly.score_series(readings)}
        for i in range(warmup, len(s.values)):
            pred_p.append(scored[readings[i].timestamp])
            pred_b.append(s.values[i] > STATIC_LATENCY_THRESHOLD_MS)
            truth.append(s.anomalous[i])
    out = {"params": {"series": len(series), "length": len(series[0].values), "warmup_excluded": warmup,
                      "static_threshold_ms": STATIC_LATENCY_THRESHOLD_MS,
                      "model": anomaly.MODEL_VERSION, "threshold": anomaly.DEFAULT_THRESHOLD,
                      "window": anomaly.DEFAULT_WINDOW,
                      "slow_links": sum(s.baseline_ms > 100 for s in series),
                      "spike_range": preset["spike_range"], "jitter": preset["jitter"]},
           "labelled_points": len(truth), "true_anomalies": sum(truth)}
    for name, pred in (("proposed", pred_p), ("baseline", pred_b)):
        c = confusion(pred, truth)
        out[name] = {"precision": round(c.precision, 4), "recall": round(c.recall, 4), "f1": round(c.f1, 4),
                     "true_positives": c.true_positives, "false_positives": c.false_positives,
                     "false_negatives": c.false_negatives}
    return out


# ---------------------------------------------------------------- remediation + verification

POLICIES = ["monitor_only", "recommend", "require_approval", "auto_remediate"]


def evaluate_remediation(seed: int, trials: int, workdir: Path, stuck_probability: float = 0.3) -> dict:
    rng = random.Random(seed)
    states: dict[str, ServiceState] = {}
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]

    def device_handler(request: httpx.Request) -> httpx.Response:
        dev = request.url.host.split(".")[0].upper()
        if request.method == "POST" and request.url.path == "/restart":
            states[dev].restart()
            return httpx.Response(200)
        return httpx.Response(404)

    def zabbix_handler(request: httpx.Request) -> httpx.Response:  # monitoring stand-in: reads true state
        body = json.loads(request.content)
        if body["method"] == "host.get":
            host = body["params"]["filter"]["host"][0]
            result = [{"hostid": host}] if host in states else []
        else:
            host = body["params"]["hostids"][0]
            result = [] if states[host].healthy else [{"eventid": "1", "name": "service down", "severity": "4"}]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": 1})

    settings = Settings(database_path=workdir / "rem.sqlite", profiles_dir=ROOT / "device-profiles",
                        verify_timeout_seconds=300)
    app = create_app(settings, remediation_transport=httpx.MockTransport(device_handler),
                     zabbix_api=ZabbixApiClient("http://zabbix.sim/api_jsonrpc.php", "sim",
                                                transport=httpx.MockTransport(zabbix_handler)),
                     clock=lambda: now[0])
    cases = []
    with TestClient(app) as client:
        for i in range(1, trials + 1):
            dev = f"SVC-{i:03d}"
            policy = rng.choice(POLICIES)
            stuck = rng.random() < stuck_probability
            states[dev] = ServiceState()
            states[dev].healthy, states[dev].stuck = False, stuck
            must(client.post("/devices", json=device_body(dev, "service", automation_policy=policy,
                                                         management_address=f"http://{dev.lower()}.lab:9100")), 201)
            eid = f"R{i:04d}"
            must(client.post("/events", json={"event_id": eid, "device_id": dev, "event_type": "service_down",
                                              "severity": "high", "started_at": now[0].isoformat(),
                                              "source": "simulator"}), 201)
            must(client.post("/incidents/sync"))
            inc = f"INC-{eid}"
            ex = must(client.post(f"/incidents/{inc}/remediation", json={"playbook_id": "restart_test_service"}), 201)
            if ex["status"] == "pending":
                ex = must(client.post(f"/executions/{ex['execution_id']}/approve",
                                      json={"approved_by": "simulated-approver"}))
            if ex["status"] == "completed":
                out = must(client.post(f"/executions/{ex['execution_id']}/verify"))
                if out["incident_status"] == "verifying":
                    now[0] += timedelta(seconds=301)
                    must(client.post(f"/executions/{ex['execution_id']}/verify"))
            final = must(client.get(f"/incidents/{inc}"))["status"]
            cases.append({"device": dev, "policy": policy, "stuck": stuck, "execution_status": ex["status"],
                          "final_incident_status": final, "actually_healthy": states[dev].healthy})
            now[0] += timedelta(seconds=600)

    executed = [c for c in cases if c["execution_status"] in ("completed", "failed")]
    blocked = [c for c in cases if c["execution_status"] == "rejected_by_policy"]
    resolved = [c for c in cases if c["final_incident_status"] == "resolved"]
    # Baseline "restart then close": ignores policy, closes the ticket when the restart call succeeds.
    baseline_unsafe = [c for c in cases if c["policy"] in ("monitor_only", "recommend")]
    baseline_false = [c for c in cases if c["stuck"]]
    return {
        "params": {"trials": trials, "stuck_probability": stuck_probability, "policies": POLICIES,
                   "verify_timeout_seconds": 300, "approvals": "simulated (always approve)"},
        "proposed": {
            "actions_executed": len(executed),
            "blocked_by_policy": len(blocked),
            "actions_on_non_executing_policy": sum(c["policy"] in ("monitor_only", "recommend") for c in executed),
            "verified_recovered": sum(c["actually_healthy"] for c in resolved),
            "false_resolutions": sum(not c["actually_healthy"] for c in resolved),
            "failed_recovery_escalated": sum(c["stuck"] and c["final_incident_status"] == "escalated" for c in executed),
            "failed_recovery_total": sum(c["stuck"] for c in executed),
            "remediation_success_rate": rate(sum(c["actually_healthy"] for c in executed), len(executed)),
        },
        "baseline": {
            "actions_executed": len(cases),
            "blocked_by_policy": 0,
            "actions_on_non_executing_policy": len(baseline_unsafe),
            "false_resolutions": len(baseline_false),
            "remediation_success_rate": rate(sum(not c["stuck"] for c in cases), len(cases)),
        },
        "cases": cases,
    }


# ---------------------------------------------------------------- recording

def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", ".", ":!experiments/runs"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()  # run outputs do not count
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def fmt(v) -> str:
    return "n/a" if v is None else (f"{v:.2%}" if isinstance(v, float) and v <= 1 else str(v))


def report(config: dict, results: dict) -> str:
    c, a, r = results["correlation"], results["anomaly"], results["remediation"]
    lines = [
        f"# Evaluation run {config['run_id']}",
        "",
        "**Simulated environment with injected, labelled faults.** Not a measurement of a production network.",
        f"Preset **{config['preset']}**, seed {config['seed']}, commit `{config['git_commit']}`, generated {config['created_at']}.",
        "",
        "## Correlation and probable RCA",
        "",
        f"{c['raw_alerts']} raw alerts from {c['params']['trials']} fault trials ({c['true_incidents']} true incidents).",
        "",
        "| Metric | Proposed | Baseline |",
        "|---|---|---|",
        f"| Incidents / tickets | {c['proposed']['incidents_or_tickets']} | {c['baseline']['incidents_or_tickets']} |",
        f"| Alert reduction | {c['proposed']['alert_reduction_percent']}% | 0% |",
        f"| Grouping precision | {fmt(c['proposed']['grouping']['precision'])} | {fmt(c['baseline']['grouping']['precision'])} |",
        f"| Grouping recall | {fmt(c['proposed']['grouping']['recall'])} | {fmt(c['baseline']['grouping']['recall'])} |",
        f"| RCA top-1 accuracy | {fmt(c['proposed']['rca_top1_accuracy'])} | {fmt(c['baseline']['rca_top1_accuracy'])} |",
        f"| RCA top-3 accuracy | {fmt(c['proposed']['rca_top3_accuracy'])} | {fmt(c['baseline']['rca_top3_accuracy'])} |",
        "",
        "| Fault kind | Cases | Proposed top-1 | Baseline top-1 |",
        "|---|---|---|---|",
        *[f"| {k} | {v['cases']} | {fmt(v['proposed_top1'])} | {fmt(v['baseline_top1'])} |" for k, v in c["by_kind"].items()],
        "",
        "## Anomaly detection (latency)",
        "",
        f"{a['labelled_points']} labelled points, {a['true_anomalies']} injected anomalies, "
        f"{a['params']['slow_links']} of {a['params']['series']} links normally slow. "
        f"Baseline: fixed threshold {a['params']['static_threshold_ms']} ms.",
        "",
        "| Metric | Proposed (robust_zscore_v1) | Baseline (static) |",
        "|---|---|---|",
        *[f"| {m} | {fmt(a['proposed'][m])} | {fmt(a['baseline'][m])} |" for m in ("precision", "recall", "f1")],
        f"| false positives | {a['proposed']['false_positives']} | {a['baseline']['false_positives']} |",
        "",
        "## Controlled remediation and verification",
        "",
        f"{r['params']['trials']} service faults, {r['params']['stuck_probability']:.0%} stuck (restart does not fix), "
        "random policy per device. Baseline: restart every time and close the ticket when the call succeeds.",
        "",
        "| Metric | Proposed | Baseline |",
        "|---|---|---|",
        f"| Actions executed | {r['proposed']['actions_executed']} | {r['baseline']['actions_executed']} |",
        f"| Actions on monitor_only/recommend devices | {r['proposed']['actions_on_non_executing_policy']} | {r['baseline']['actions_on_non_executing_policy']} |",
        f"| Blocked by policy | {r['proposed']['blocked_by_policy']} | 0 |",
        f"| False resolutions (closed while still down) | {r['proposed']['false_resolutions']} | {r['baseline']['false_resolutions']} |",
        f"| Failed recoveries escalated to humans | {r['proposed']['failed_recovery_escalated']} / {r['proposed']['failed_recovery_total']} | 0 |",
        "",
        "## Not measured in this run",
        "",
        "MTTD and MTTR need wall-clock timings from the live Zabbix deployment and are not reported here.",
        "",
    ]
    return "\n".join(lines)


def run(seed: int, trials: int, remediation_trials: int, out_dir: Path, preset_name: str = "easy") -> Path:
    preset = PRESETS[preset_name]
    created = datetime.now(timezone.utc)
    run_id = f"{created:%Y%m%dT%H%M%SZ}-{preset_name}-seed{seed}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        results = {
            "correlation": evaluate_correlation(seed, trials, work, preset),
            "anomaly": evaluate_anomaly(seed, preset),
            "remediation": evaluate_remediation(seed, remediation_trials, work),
        }
    config = {
        "run_id": run_id, "seed": seed, "created_at": created.isoformat(), "git_commit": git_commit(),
        "environment": "simulated", "preset": preset_name, "preset_params": preset,
        "methods": {"correlation": correlation.METHOD, "rca": rca.METHOD, "anomaly": anomaly.MODEL_VERSION},
        "trials": trials, "remediation_trials": remediation_trials,
    }
    target = out_dir / run_id
    target.mkdir(parents=True, exist_ok=False)
    (target / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (target / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (target / "report.md").write_text(report(config, results), encoding="utf-8")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--trials", type=int, default=200, help="correlation/RCA fault trials")
    ap.add_argument("--remediation-trials", type=int, default=60)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="easy")
    ap.add_argument("--out", type=Path, default=ROOT / "experiments" / "runs")
    a = ap.parse_args()
    target = run(a.seed, a.trials, a.remediation_trials, a.out, a.preset)
    print(f"Recorded run in {target}")
    print((target / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
