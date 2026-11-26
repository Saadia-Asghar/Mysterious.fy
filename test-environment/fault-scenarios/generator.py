"""Seeded, labelled fault scenarios for M14 (simulated environment).

Everything is reproducible from (seed, parameters). The ground truth is known because the
faults are injected, which is what makes simulated evaluation possible. Results from these
scenarios must be reported as SIMULATED, never as measurements of a real network.

Topology (device-generic: switches and cameras are just profiles):

    CORE
    ├── SW-1 ── CAM-101 .. CAM-104
    ├── SW-2 ── CAM-201 .. CAM-204
    ├── SW-3 ── CAM-301 .. CAM-304
    └── SW-4 ── CAM-401 .. CAM-404
"""
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SWITCHES = [f"SW-{s}" for s in range(1, 5)]
CAMERAS = {sw: [f"CAM-{s}{c:02d}" for c in range(1, 5)] for s, sw in enumerate(SWITCHES, 1)}

TRIAL_KINDS = {  # kind: weight
    "switch_outage": 0.30,         # switch alerts, then all its cameras
    "silent_switch_outage": 0.20,  # switch not monitored/alerting; only its cameras alert
    "single_camera": 0.30,
    "two_unrelated_cameras": 0.20,  # different switches, same time window
}


@dataclass
class Scenario:
    seed: int
    devices: list[dict]
    edges: list[tuple[str, str]]
    events: list[dict]
    truth_groups: list[list[str]]          # event_ids that form one real incident
    truth_causes: dict[str, str]           # first event_id of a truth group -> real root cause
    trial_kinds: list[str]
    params: dict = field(default_factory=dict)


def topology() -> tuple[list[dict], list[tuple[str, str]]]:
    devices = [{"device_id": "CORE", "kind": "switch"}]
    edges = []
    for sw in SWITCHES:
        devices.append({"device_id": sw, "kind": "switch"})
        edges.append((sw, "CORE"))
        for cam in CAMERAS[sw]:
            devices.append({"device_id": cam, "kind": "camera"})
            edges.append((cam, sw))
    return devices, edges


PRESETS = {
    # Clean: faults far apart, every alert arrives quickly. Shows the method works as designed.
    "easy": {"spacing_seconds": 900, "max_cascade_delay": 30, "missing_alert_probability": 0.0,
             "spike_range": (3.0, 6.0), "jitter": 0.10},
    # Realistic stress: faults overlap in time, some alerts never arrive, some cascades are slower
    # than the 120 s correlation window, smaller spikes on noisier links.
    "hard": {"spacing_seconds": 60, "max_cascade_delay": 180, "missing_alert_probability": 0.10,
             "spike_range": (1.5, 3.0), "jitter": 0.25},
}


def correlation_scenario(seed: int, trials: int, noise_probability: float = 0.2,
                         spacing_seconds: int = 900, max_cascade_delay: int = 30,
                         missing_alert_probability: float = 0.0) -> Scenario:
    rng = random.Random(seed)
    devices, edges = topology()
    events: list[dict] = []
    groups: list[list[str]] = []
    causes: dict[str, str] = {}
    kinds: list[str] = []
    counter = 0

    def emit(device: str, at: datetime) -> str:
        nonlocal counter
        counter += 1
        eid = f"E{counter:05d}"
        events.append({"event_id": eid, "device_id": device, "event_type": "device_unreachable",
                       "severity": "high", "started_at": at.isoformat(), "source": "simulator"})
        return eid

    for i in range(trials):
        start = T0 + timedelta(seconds=i * spacing_seconds)
        kind = rng.choices(list(TRIAL_KINDS), weights=list(TRIAL_KINDS.values()))[0]
        kinds.append(kind)
        if kind in ("switch_outage", "silent_switch_outage"):
            sw = rng.choice(SWITCHES)
            group = []
            if kind == "switch_outage":
                group.append(emit(sw, start))
            for cam in CAMERAS[sw]:
                if rng.random() < missing_alert_probability:  # alert lost / camera not monitored
                    continue
                group.append(emit(cam, start + timedelta(seconds=rng.randint(1, max_cascade_delay))))
            if not group:
                continue
            group.sort()
            groups.append(group)
            causes[group[0]] = sw
            if rng.random() < noise_probability:  # unrelated camera elsewhere, same window
                other = rng.choice([s for s in SWITCHES if s != sw])
                e = emit(rng.choice(CAMERAS[other]), start + timedelta(seconds=rng.randint(0, max_cascade_delay)))
                groups.append([e])
                causes[e] = events[-1]["device_id"]
        elif kind == "single_camera":
            cam = rng.choice(CAMERAS[rng.choice(SWITCHES)])
            e = emit(cam, start)
            groups.append([e])
            causes[e] = cam
        else:
            sw_a, sw_b = rng.sample(SWITCHES, 2)
            for sw, delay in ((sw_a, 0), (sw_b, rng.randint(0, 20))):
                cam = rng.choice(CAMERAS[sw])
                e = emit(cam, start + timedelta(seconds=delay))
                groups.append([e])
                causes[e] = cam

    return Scenario(seed, devices, edges, events, groups, causes, kinds, params={
        "trials": trials, "noise_probability": noise_probability,
        "spacing_seconds": spacing_seconds, "max_cascade_delay": max_cascade_delay,
        "missing_alert_probability": missing_alert_probability, "trial_weights": TRIAL_KINDS,
    })


@dataclass
class LabelledSeries:
    device_id: str
    baseline_ms: float
    values: list[float]
    anomalous: list[bool]


def latency_series(seed: int, devices: int = 16, length: int = 200, anomalies_per_series: int = 4,
                   high_latency_link_probability: float = 0.25, jitter: float = 0.10,
                   spike_range: tuple[float, float] = (3.0, 6.0), warmup: int = 30) -> list[LabelledSeries]:
    """Latency per device with injected spikes. Some links are normally slow (e.g. wireless or
    remote sites), which is where a single fixed threshold struggles."""
    rng = random.Random(seed)
    out = []
    for d in range(devices):
        slow = rng.random() < high_latency_link_probability
        base = rng.uniform(120, 200) if slow else rng.uniform(5, 40)
        values = [base * (1 + rng.uniform(-jitter, jitter)) for _ in range(length)]
        labels = [False] * length
        for idx in rng.sample(range(warmup, length), anomalies_per_series):
            values[idx] = base * rng.uniform(*spike_range)
            labels[idx] = True
        out.append(LabelledSeries(f"DEV-{d + 1:02d}", round(base, 2), values, labels))
    return out
