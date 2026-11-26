# Evaluation run 20261109T083513Z-easy-seed42

**Simulated environment with injected, labelled faults.** Not a measurement of a production network.
Preset **easy**, seed 42, commit `47031eb93e0a851b7cbc6a973aa6c0039b07a380`, generated 2026-11-09T08:35:13.416524+00:00.

## Correlation and probable RCA

611 raw alerts from 200 fault trials (263 true incidents).

| Metric | Proposed | Baseline |
|---|---|---|
| Incidents / tickets | 263 | 611 |
| Alert reduction | 56.96% | 0% |
| Grouping precision | 100.00% | n/a |
| Grouping recall | 100.00% | 0.00% |
| RCA top-1 accuracy | 100.00% | 86.31% |
| RCA top-3 accuracy | 100.00% | 86.31% |

| Fault kind | Cases | Proposed top-1 | Baseline top-1 |
|---|---|---|---|
| camera_failure | 167 | 100.00% | 100.00% |
| silent_switch_outage | 36 | 100.00% | 0.00% |
| switch_outage | 60 | 100.00% | 100.00% |

## Anomaly detection (latency)

2720 labelled points, 64 injected anomalies, 6 of 16 links normally slow. Baseline: fixed threshold 100.0 ms.

| Metric | Proposed (robust_zscore_v1) | Baseline (static) |
|---|---|---|
| precision | 100.00% | 3.95% |
| recall | 100.00% | 64.06% |
| f1 | 100.00% | 7.45% |
| false positives | 0 | 996 |

## Controlled remediation and verification

60 service faults, 30% stuck (restart does not fix), random policy per device. Baseline: restart every time and close the ticket when the call succeeds.

| Metric | Proposed | Baseline |
|---|---|---|
| Actions executed | 29 | 60 |
| Actions on monitor_only/recommend devices | 0 | 31 |
| Blocked by policy | 31 | 0 |
| False resolutions (closed while still down) | 0 | 22 |
| Failed recoveries escalated to humans | 14 / 14 | 0 |

## Not measured in this run

MTTD and MTTR need wall-clock timings from the live Zabbix deployment and are not reported here.
