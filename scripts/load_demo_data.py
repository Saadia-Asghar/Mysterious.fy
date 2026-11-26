"""Fill a separate DEMO database so the Grafana dashboard has something to show.

    python scripts/load_demo_data.py                 # writes data/demo.sqlite (replaces it)
    NMS_DATABASE_PATH=data/demo.sqlite uvicorn app.main:app --app-dir integration-api --host 0.0.0.0

Everything here is SIMULATED demo data, spread over the last 7 days:
- 4 switches at 4 sites, 16 cameras, seeded faults (switch outages, silent switch outages,
  single and simultaneous camera failures) from the M14 scenario generator;
- latency telemetry with a few injected spikes (feeds the anomaly table);
- lab services remediated through the real policy engine, with a monitoring stand-in that
  reports the service's true state, so MTTR comes only from verified recoveries.

Never point this at a real database and never present these numbers as results.
"""
import argparse
import json
import random
import sys
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
from generator import CAMERAS, SWITCHES, T0, correlation_scenario, latency_series  # noqa: E402
from test_service import ServiceState  # noqa: E402

DAYS = 7
SITES = {sw: f"SITE-{chr(64 + i)}" for i, sw in enumerate(SWITCHES, 1)}
PROFILES = {"switch": ("network_switch_basic", "network_switch"), "camera": ("ip_camera_basic", "ip_camera"),
            "service": ("test_service_basic", "test_service")}


def device(device_id: str, kind: str, site: str, **extra) -> dict:
    profile, dtype = PROFILES[kind]
    return {"device_id": device_id, "name": device_id, "device_type": dtype, "profile_id": profile,
            "organization_id": "DEMO", "site_id": site, "zone_id": "DEMO",
            "management_address": "<demo>", "responsible_team": "demo-noc", **extra}


def ok(r: httpx.Response) -> dict | list:
    if r.status_code >= 300:
        raise RuntimeError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text}")
    return r.json()


def load(db: Path, seed: int, trials: int, services: int) -> dict:
    rng = random.Random(seed)
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=DAYS)
    shift = start - T0
    sc = correlation_scenario(seed, trials, spacing_seconds=DAYS * 86400 // trials,
                              max_cascade_delay=60, missing_alert_probability=0.1)

    states: dict[str, ServiceState] = {}
    now = [start]

    def device_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/restart":
            states[request.url.host.split(".")[0].upper()].restart()
            return httpx.Response(200)
        return httpx.Response(404)

    def zabbix_handler(request: httpx.Request) -> httpx.Response:  # demo stand-in: reports true state
        body = json.loads(request.content)
        if body["method"] == "host.get":
            host = body["params"]["filter"]["host"][0]
            result = [{"hostid": host}] if host in states else []
        else:
            host = body["params"]["hostids"][0]
            result = [] if states[host].healthy else [{"eventid": "1", "name": "service down", "severity": "4"}]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": 1})

    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    app = create_app(Settings(database_path=db, profiles_dir=ROOT / "device-profiles", verify_timeout_seconds=300),
                     remediation_transport=httpx.MockTransport(device_handler),
                     zabbix_api=ZabbixApiClient("http://zabbix.demo/api_jsonrpc.php", "demo",
                                                transport=httpx.MockTransport(zabbix_handler)),
                     clock=lambda: now[0])
    with TestClient(app) as client:
        ok(client.post("/devices", json=device("CORE", "switch", "SITE-CORE")))
        for sw in SWITCHES:
            ok(client.post("/devices", json=device(sw, "switch", SITES[sw])))
            for cam in CAMERAS[sw]:
                ok(client.post("/devices", json=device(cam, "camera", SITES[sw])))
        for child, parent in sc.edges:
            ok(client.post("/topology/edges", json={"from_device_id": child, "to_device_id": parent}))
        for e in sc.events:
            at = datetime.fromisoformat(e["started_at"]) + shift
            ok(client.post("/events", json={**e, "started_at": at.isoformat(), "source": "demo"}))
        ok(client.post("/incidents/sync"))

        # Latency telemetry for 4 cameras, one reading every 30 min, with injected spikes.
        for series, cam in zip(latency_series(seed, devices=4, length=DAYS * 48, anomalies_per_series=3),
                               ["CAM-101", "CAM-202", "CAM-303", "CAM-404"]):
            for k, value in enumerate(series.values):
                ok(client.post("/telemetry", json={
                    "device_id": cam, "metric_name": "latency_ms", "value": round(value, 2), "unit": "ms",
                    "timestamp": (start + timedelta(minutes=30 * k)).isoformat(), "source": "demo"}))

        # Lab services: real policy engine + verification, varied repair times.
        for i in range(1, services + 1):
            dev = f"SVC-{i:03d}"
            now[0] = start + timedelta(hours=rng.uniform(2, DAYS * 24 - 2))
            states[dev] = ServiceState()
            states[dev].healthy, states[dev].stuck = False, rng.random() < 0.2
            policy = rng.choice(["require_approval", "auto_remediate", "monitor_only"])
            ok(client.post("/devices", json=device(dev, "service", rng.choice(list(SITES.values())),
                                                   automation_policy=policy,
                                                   management_address=f"http://{dev.lower()}.lab:9100")))
            eid = f"D{i:04d}"
            ok(client.post("/events", json={"event_id": eid, "device_id": dev, "event_type": "service_down",
                                            "severity": "high", "started_at": now[0].isoformat(), "source": "demo"}))
            ok(client.post("/incidents/sync"))
            ex = ok(client.post(f"/incidents/INC-{eid}/remediation", json={"playbook_id": "restart_test_service"}))
            now[0] += timedelta(minutes=rng.uniform(2, 25))      # time to notice / approve
            if ex["status"] == "pending":
                ex = ok(client.post(f"/executions/{ex['execution_id']}/approve", json={"approved_by": "demo-operator"}))
            if ex["status"] == "completed":
                now[0] += timedelta(minutes=rng.uniform(1, 6))   # time for monitoring to re-check
                out = ok(client.post(f"/executions/{ex['execution_id']}/verify"))
                if out["incident_status"] == "verifying":
                    now[0] += timedelta(seconds=301)
                    ok(client.post(f"/executions/{ex['execution_id']}/verify"))
        summary = ok(client.get("/grafana/summary"))[0]
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "demo.sqlite")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--services", type=int, default=15)
    args = ap.parse_args()
    s = load(args.db, args.seed, args.trials, args.services)
    print(f"Demo data in {args.db} (SIMULATED): {s['incidents_total']} incidents from {s['raw_events']} alerts, "
          f"{s['resolved']} resolved, {s['escalated']} escalated, {s['open']} open.")


if __name__ == "__main__":
    main()
