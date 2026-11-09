# Fault scenarios

`generator.py` creates seeded, labelled scenarios for M14 on a 4-switch, 16-camera topology:

- `switch_outage`: the switch alerts, then its cameras
- `silent_switch_outage`: only the cameras alert (switch unmonitored)
- `single_camera`
- `two_unrelated_cameras`: on different switches, same time window
- plus random unrelated noise failures during outages

`latency_series()` creates per-device latency with injected spikes (labels known), including normally slow links. `PRESETS` holds the `easy` and `hard` settings. Used by `scripts/run_evaluation.py`; see `experiments/README.md`.
