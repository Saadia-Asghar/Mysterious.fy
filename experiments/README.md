# Experiments (M14)

Every reported number must come from a recorded run in `runs/`. Never type results into the report by hand.

## Run

```bash
python scripts/run_evaluation.py --seed 42 --preset easy
python scripts/run_evaluation.py --seed 42 --preset hard
```

Options: `--trials` (correlation fault trials, default 200), `--remediation-trials` (default 60), `--out`.

Each run creates `runs/<UTC time>-<preset>-seed<seed>/` with `config.json` (seed, preset parameters, methods, git commit; `-dirty` means uncommitted code), `results.json` (all metrics plus per-case details) and `report.md`. The same seed and code always give the same results.

## What is compared

The **proposed** pipeline is the real integration API run in-process. The **baseline** is a conventional NMS on the same inputs:

| Area | Proposed | Baseline |
|---|---|---|
| Incidents | `time_window_and_topology_v1` correlation | one ticket per alert |
| Root cause | `topology_time_v1` ranking | the alerting device |
| Anomalies | `robust_zscore_v1` per device | fixed 100 ms latency threshold |
| Remediation | policy + approval + Zabbix verification | restart every time, close ticket when the call succeeds |

Metrics: alert reduction, pairwise grouping precision/recall, RCA top-1 and top-3 accuracy (overall and by fault kind), anomaly precision/recall/F1, actions on non-executing policies, actions blocked, false resolutions (closed while still down), failed recoveries escalated.

## Presets

- **easy**: faults 15 min apart, every alert arrives within 30 s, spikes 3-6x. Shows the methods work as designed.
- **hard**: faults overlap (60 s apart), 10% of camera alerts never arrive, cascades up to 180 s (longer than the 120 s window), spikes 1.5-3x, noisier links.

## Reporting rules

- Always say **simulated environment with injected, labelled faults**.
- Report both presets. The hard preset shows real limitations (over-grouping of overlapping faults; unrelated camera failures on one switch blamed on the switch). Present them as limitations, not hide them.
- MTTD and MTTR are **not** measured here. They need timings from the live Zabbix deployment.
- The remediation approver is simulated (always approves).
