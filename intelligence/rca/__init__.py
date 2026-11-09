"""M9: probable root-cause ranking.

Method `topology_time_v1`. Candidates are the affected devices plus their nearest shared
upstream device(s), which may be silent (not alerting). Each candidate gets an explainable
weighted score:

    coverage  (0.70)  fraction of affected devices that are the candidate or downstream of it
    alerting  (0.20)  the candidate itself raised an event
    earliest  (0.10)  the candidate's event was the first in the incident

Scores are normalized to sum to 1 so they read as a ranking. They are heuristic ranks,
NOT calibrated probabilities. Accuracy must be measured in M14 from real runs.
"""
from dataclasses import dataclass

from intelligence.correlation import CorrelationGroup
from intelligence.topology import Topology

METHOD = "topology_time_v1"
W_COVERAGE, W_ALERTING, W_EARLIEST = 0.70, 0.20, 0.10


@dataclass(frozen=True)
class RankedCause:
    device_id: str
    score: float
    reason: str


def _nearest_shared_upstream(devices: list[str], topology: Topology) -> set[str]:
    shared = set.intersection(*(topology.ancestors(d) for d in devices))
    # keep only the nearest: drop any shared node that is upstream of another shared node
    return {s for s in shared if not any(topology.is_upstream_of(s, o) for o in shared if o != s)}


def rank(group: CorrelationGroup, topology: Topology) -> list[RankedCause]:
    affected = group.devices
    alerting = set(affected)
    earliest = group.events[0].device_id
    candidates = list(affected)
    if len(affected) > 1:
        candidates += sorted(_nearest_shared_upstream(affected, topology) - alerting)

    raw: list[tuple[str, float, str]] = []
    for c in candidates:
        covered = sum(topology.covers(c, d) for d in affected)
        coverage = covered / len(affected)
        is_alerting = c in alerting
        is_earliest = c == earliest
        score = W_COVERAGE * coverage + W_ALERTING * is_alerting + W_EARLIEST * is_earliest
        parts = [f"explains {covered}/{len(affected)} affected devices"]
        parts.append("raised an event" if is_alerting else "silent upstream device")
        if is_earliest:
            parts.append("failed first")
        raw.append((c, score, "; ".join(parts)))

    total = sum(s for _, s, _ in raw) or 1.0
    ranked = [RankedCause(c, round(s / total, 4), r) for c, s, r in raw]
    return sorted(ranked, key=lambda rc: (-rc.score, rc.device_id))
