# Anomaly detection

Model `robust_zscore_v1` (see `__init__.py`). Each reading of a device metric is compared with that series' previous 30 readings:

- median and MAD (median absolute deviation) give a baseline that one outlier cannot distort
- `robust_z = 0.6745 × (value − median) / MAD`; anomalous when `|z| ≥ 3.5` (Iglewicz & Hoaglin)
- `anomaly_score = |z| / (|z| + 3.5)`: 0 normal, 0.5 at the threshold, near 1 extreme. A severity scale, not a probability
- no look-ahead, so it works online; no score until 10 readings exist
- zero-spread baselines use a 1-unit floor so tiny jitter is not flagged

Why this model: it is interpretable (every flag can be explained by value vs. median), needs no training data, and is a sensible first baseline. More complex models can be compared against it in M14.

API: `GET /intelligence/anomalies?device_id=&metric_name=&only_anomalies=&window=&threshold=`

`evaluate.py` computes precision, recall and F1 from predicted vs. labelled anomalies. Only report numbers from recorded runs.

Status: implemented and unit-tested on synthetic seeded series (`tests/test_anomaly.py`). Those tests check logic only; they are not an evaluation. Real evaluation is M14.
