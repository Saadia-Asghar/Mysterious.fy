# Evaluation run 20261109T094407Z-hard-seed42

**Simulated environment with injected, labelled faults.** Not a measurement of a production network.
Preset **hard**, seed 42, commit `4602afebeaa8d7e3debba719303646538cb033b9`, generated 2026-11-09T09:44:07.602302+00:00.

## Correlation and probable RCA

550 raw alerts from 200 fault trials (256 true incidents).

| Metric | Proposed v1 (time_window_and_topology_v1) | Proposed v2 (upstream_anchor_quorum_v2) | Baseline |
|---|---|---|---|
| Incidents / tickets | 196 | 199 | 550 |
| Alert reduction | 64.36% | 63.82% | 0% |
| Grouping precision | 41.47% | 44.28% | n/a |
| Grouping recall | 53.27% | 63.01% | 0.00% |
| Grouping f1 | 46.64% | 52.01% | n/a |
| RCA top-1 accuracy | 55.86% | 60.16% | 88.67% |
| RCA top-3 accuracy | 86.72% | 87.89% | 88.67% |

RCA is `topology_time_v1` in both columns; only the correlation method differs.

| Fault kind | Cases | v1 top-1 | v2 top-1 | Baseline top-1 |
|---|---|---|---|---|
| camera_failure | 167 | 43.11% | 40.12% | 100.00% |
| silent_switch_outage | 29 | 100.00% | 93.10% | 0.00% |
| switch_outage | 60 | 70.00% | 100.00% | 100.00% |

## Anomaly detection (latency)

2720 labelled points, 64 injected anomalies, 6 of 16 links normally slow. Baseline: fixed threshold 100.0 ms.

| Metric | Proposed (robust_zscore_v1) | Baseline (static) |
|---|---|---|
| precision | 100.00% | 2.35% |
| recall | 89.06% | 37.50% |
| f1 | 94.21% | 4.43% |
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
