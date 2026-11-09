"""M14: evaluation metrics, scenario generator and the recorded-run tooling."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from intelligence.evaluation import alert_reduction, grouping_scores, rate, top_k_hit
from test_integration_api import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "test-environment" / "fault-scenarios"))
from generator import PRESETS, correlation_scenario, latency_series  # noqa: E402


def load_runner():
    spec = importlib.util.spec_from_file_location("run_evaluation", REPO_ROOT / "scripts" / "run_evaluation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- metrics -------------------------------------------------------------

def test_grouping_perfect_and_split():
    truth = [["a", "b", "c"], ["d"]]
    assert grouping_scores(truth, truth).f1 == 1.0
    split = grouping_scores(truth, [["a", "b"], ["c"], ["d"]])
    assert split.precision == 1.0 and split.recall == pytest.approx(1 / 3, abs=1e-4)


def test_grouping_over_merge_hurts_precision():
    s = grouping_scores([["a", "b"], ["c"]], [["a", "b", "c"]])
    assert s.recall == 1.0 and s.precision == pytest.approx(1 / 3, abs=1e-4)


def test_grouping_undefined_when_nothing_grouped():
    s = grouping_scores([["a", "b"]], [["a"], ["b"]])
    assert s.precision is None and s.recall == 0.0 and s.f1 is None


def test_topk_reduction_rate():
    assert top_k_hit(["SW-1", "CAM-101"], "CAM-101", 2) and not top_k_hit(["SW-1", "CAM-101"], "CAM-101", 1)
    assert alert_reduction(10, 4) == 60.0 and alert_reduction(0, 0) == 0.0
    assert rate(1, 4) == 0.25 and rate(0, 0) is None


# ---- generator -----------------------------------------------------------

def test_scenarios_are_reproducible_and_labelled():
    a, b = correlation_scenario(5, 30), correlation_scenario(5, 30)
    assert a.events == b.events and a.truth_groups == b.truth_groups
    all_ids = {e["event_id"] for e in a.events}
    grouped = [eid for g in a.truth_groups for eid in g]
    assert sorted(grouped) == sorted(all_ids)  # every event belongs to exactly one truth incident
    assert set(a.truth_causes) == {g[0] for g in a.truth_groups}


def test_hard_preset_drops_some_alerts():
    hard = PRESETS["hard"]
    sc = correlation_scenario(1, 200, spacing_seconds=hard["spacing_seconds"],
                              max_cascade_delay=hard["max_cascade_delay"],
                              missing_alert_probability=hard["missing_alert_probability"])
    outages = [g for g in sc.truth_groups if sc.truth_causes[g[0]].startswith("SW-")]
    assert any(len(g) < 5 for g in outages)


def test_latency_labels_match_injected_points():
    for s in latency_series(3, devices=4):
        assert sum(s.anomalous) == 4 and not any(s.anomalous[:30])


# ---- recorded run --------------------------------------------------------

@pytest.mark.parametrize("preset", ["easy", "hard"])
def test_run_records_everything_and_keeps_safety_invariants(tmp_path: Path, preset: str):
    target = load_runner().run(seed=11, trials=25, remediation_trials=12, out_dir=tmp_path, preset_name=preset)
    assert {p.name for p in target.iterdir()} == {"config.json", "results.json", "report.md"}
    config = json.loads((target / "config.json").read_text(encoding="utf-8"))
    results = json.loads((target / "results.json").read_text(encoding="utf-8"))
    assert config["environment"] == "simulated" and config["preset"] == preset and config["seed"] == 11
    assert config["methods"] == {"correlation": "time_window_and_topology_v1", "rca": "topology_time_v1",
                                 "anomaly": "robust_zscore_v1"}

    c = results["correlation"]
    assert c["baseline"]["incidents_or_tickets"] == c["raw_alerts"]
    assert len(c["cases"]) == c["true_incidents"]

    r = results["remediation"]["proposed"]
    # Safety invariants that must hold whatever the scenario:
    assert r["actions_on_non_executing_policy"] == 0
    assert r["false_resolutions"] == 0
    assert r["failed_recovery_escalated"] == r["failed_recovery_total"]

    report = (target / "report.md").read_text(encoding="utf-8")
    assert "Simulated environment" in report and "MTTD and MTTR" in report


def test_same_seed_same_results(tmp_path: Path):
    runner = load_runner()
    a = runner.run(seed=3, trials=15, remediation_trials=6, out_dir=tmp_path / "a")
    b = runner.run(seed=3, trials=15, remediation_trials=6, out_dir=tmp_path / "b")
    ra = json.loads((a / "results.json").read_text(encoding="utf-8"))
    rb = json.loads((b / "results.json").read_text(encoding="utf-8"))
    assert ra == rb
