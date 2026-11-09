"""M10 unit tests. Synthetic, seeded series check the detector's logic only; they are NOT
an evaluation result. Real precision/recall comes from recorded runs in M14."""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from intelligence.anomaly import Reading, score_series
from intelligence.anomaly.evaluate import confusion
from test_integration_api import CAMERA, make_client

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def series(values: list[float]) -> list[Reading]:
    return [Reading(T0 + timedelta(minutes=i), v) for i, v in enumerate(values)]


def jitter(n: int, base: float = 20.0, spread: float = 2.0, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    return [base + rng.uniform(-spread, spread) for _ in range(n)]


def test_normal_jitter_raises_no_anomalies():
    assert not any(r.is_anomaly for r in score_series(series(jitter(200))))


def test_latency_spike_is_flagged_high():
    values = jitter(60)
    values[40] = 250.0
    flagged = [r for r in score_series(series(values)) if r.is_anomaly]
    assert [r.value for r in flagged] == [250.0]
    assert flagged[0].direction == "high" and flagged[0].anomaly_score > 0.9


def test_drop_is_flagged_low():
    values = jitter(40, base=100, spread=1)
    values[30] = 40.0
    flagged = [r for r in score_series(series(values)) if r.is_anomaly]
    assert flagged[0].direction == "low"


def test_no_scores_before_min_baseline():
    results = score_series(series(jitter(15)), min_baseline=10)
    assert len(results) == 5
    assert results[0].timestamp == T0 + timedelta(minutes=10)


def test_no_lookahead_future_spike_does_not_change_earlier_scores():
    values = jitter(50)
    before = score_series(series(values))
    values[49] = 999.0
    after = score_series(series(values))
    assert [r.robust_z for r in before[:-1]] == [r.robust_z for r in after[:-1]]


def test_score_is_half_at_threshold():
    # flat baseline of 10 with MAD floor 1.0: z = 0.6745*(v-10)/(0.6745*1.0) = v-10
    results = score_series(series([10.0] * 10 + [13.5]), min_spread=1.0, threshold=3.5)
    assert results[-1].robust_z == pytest.approx(3.5)
    assert results[-1].anomaly_score == pytest.approx(0.5)
    assert results[-1].is_anomaly


def test_flat_baseline_tiny_jitter_not_extreme():
    results = score_series(series([1.0] * 20 + [1.2]))
    assert not results[-1].is_anomaly


def test_sustained_degradation_detected_then_becomes_new_normal():
    values = jitter(40) + [80.0] * 40
    flags = [r.is_anomaly for r in score_series(series(values), window=30)]
    assert flags[30]  # first degraded reading (index 40 in input, 30 in output)
    assert not flags[-1]  # after a full window the new level is the baseline


def test_bad_parameters_rejected():
    with pytest.raises(ValueError):
        score_series(series(jitter(20)), window=5, min_baseline=10)


def test_confusion_metrics():
    s = confusion([True, True, False, False], [True, False, True, False])
    assert (s.true_positives, s.false_positives, s.false_negatives, s.true_negatives) == (1, 1, 1, 1)
    assert s.precision == 0.5 and s.recall == 0.5 and s.f1 == 0.5
    assert confusion([False], [False]).f1 == 0.0
    with pytest.raises(ValueError):
        confusion([True], [])


def test_anomalies_api(tmp_path: Path):
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        values = jitter(30)
        values[25] = 300.0
        for i, v in enumerate(values):
            r = client.post("/telemetry", json={
                "device_id": "CAM-001", "metric_name": "latency_ms", "value": v, "unit": "ms",
                "timestamp": (T0 + timedelta(minutes=i)).isoformat(), "source": "test"})
            assert r.status_code == 201
        all_scores = client.get("/intelligence/anomalies?device_id=CAM-001").json()
        assert len(all_scores) == 20
        flagged = client.get("/intelligence/anomalies?only_anomalies=true").json()
        assert len(flagged) == 1
        a = flagged[0]
        assert a["value"] == 300.0 and a["metric_name"] == "latency_ms"
        assert a["model_version"] == "robust_zscore_v1" and a["is_anomaly"]
        assert client.get("/intelligence/anomalies?window=5").status_code == 422
        assert client.get("/intelligence/anomalies?device_id=NOPE").status_code == 404
