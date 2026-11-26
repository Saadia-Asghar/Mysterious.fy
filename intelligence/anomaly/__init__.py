"""M10: interpretable anomaly detection on normalized telemetry.

Model `robust_zscore_v1`. For each reading of one (device, metric) series, compare it to the
previous `window` readings only (no look-ahead, so it works online):

    median   = median(baseline)
    MAD      = median(|x - median|)                 (spread that ignores outliers)
    robust_z = 0.6745 * (value - median) / MAD       (Iglewicz & Hoaglin modified z-score)

A reading is anomalous when |robust_z| >= threshold (default 3.5, the usual cut-off).
`anomaly_score` = |z| / (|z| + threshold), so it is 0 for normal, exactly 0.5 at the
threshold, and approaches 1 for extreme values. It is a monotone severity scale, not a
probability. No score is produced until `min_baseline` readings exist.

If the baseline has zero spread (MAD = 0, e.g. latency always 1 ms), a small floor
`min_spread` (in the metric's own unit) is used so a tiny jitter is not flagged as extreme.
"""
from dataclasses import dataclass
from datetime import datetime
from statistics import median

MODEL_VERSION = "robust_zscore_v1"
DEFAULT_WINDOW = 30
DEFAULT_MIN_BASELINE = 10
DEFAULT_THRESHOLD = 3.5
DEFAULT_MIN_SPREAD = 1.0
MAD_TO_Z = 0.6745


@dataclass(frozen=True)
class Reading:
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class AnomalyResult:
    timestamp: datetime
    value: float
    baseline_median: float
    robust_z: float
    anomaly_score: float
    is_anomaly: bool
    direction: str  # "high", "low" or "normal"
    model_version: str = MODEL_VERSION


def score_series(
    readings: list[Reading],
    window: int = DEFAULT_WINDOW,
    min_baseline: int = DEFAULT_MIN_BASELINE,
    threshold: float = DEFAULT_THRESHOLD,
    min_spread: float = DEFAULT_MIN_SPREAD,
) -> list[AnomalyResult]:
    if min_baseline < 3 or window < min_baseline or threshold <= 0 or min_spread <= 0:
        raise ValueError("need min_baseline >= 3, window >= min_baseline, threshold > 0, min_spread > 0")
    ordered = sorted(readings, key=lambda r: r.timestamp)
    results: list[AnomalyResult] = []
    for i, r in enumerate(ordered):
        baseline = [b.value for b in ordered[max(0, i - window):i]]
        if len(baseline) < min_baseline:
            continue
        med = median(baseline)
        mad = median(abs(x - med) for x in baseline)
        spread = max(mad, min_spread * MAD_TO_Z)
        z = MAD_TO_Z * (r.value - med) / spread
        flagged = abs(z) >= threshold
        results.append(
            AnomalyResult(
                timestamp=r.timestamp,
                value=r.value,
                baseline_median=med,
                robust_z=round(z, 4),
                anomaly_score=round(abs(z) / (abs(z) + threshold), 4),
                is_anomaly=flagged,
                direction=("high" if z > 0 else "low") if flagged else "normal",
            )
        )
    return results
