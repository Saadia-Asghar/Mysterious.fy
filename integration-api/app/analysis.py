"""Glue between stored NMS records and the intelligence layer (intelligence/ package)."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from intelligence import correlation, rca  # noqa: E402
from intelligence.topology import Topology, TopologyCycle  # noqa: E402

from app.schemas import (  # noqa: E402
    CorrelationOut,
    Event,
    IncidentAnalysis,
    RankedCauseOut,
    RcaOut,
    TopologyEdge,
)

__all__ = ["DEFAULT_WINDOW_SECONDS", "TopologyCycle", "analyze", "build_topology"]

DEFAULT_WINDOW_SECONDS = correlation.DEFAULT_WINDOW_SECONDS
SEVERITY_ORDER = ["not_classified", "information", "warning", "average", "high", "disaster"]


def build_topology(edges: list[TopologyEdge]) -> Topology:
    return Topology((e.from_device_id, e.to_device_id) for e in edges if e.relationship == "depends_on")


def analyze(events: list[Event], edges: list[TopologyEdge], window_seconds: int) -> list[IncidentAnalysis]:
    topology = build_topology(edges)
    incidents = []
    for group in correlation.correlate(events, topology, window_seconds):
        ranked = rca.rank(group, topology)
        incidents.append(
            IncidentAnalysis(
                incident_id=f"INC-{group.event_ids[0]}",
                event_ids=group.event_ids,
                affected_devices=group.devices,
                severity=max((e.severity for e in group.events), key=SEVERITY_ORDER.index),
                status="open",
                created_at=group.first_at,
                correlation=CorrelationOut(
                    method=correlation.METHOD, reason=correlation.reason(group, topology, window_seconds)
                ),
                rca=RcaOut(
                    method=rca.METHOD,
                    ranked_causes=[RankedCauseOut(device_id=r.device_id, score=r.score, reason=r.reason) for r in ranked],
                ),
            )
        )
    return incidents
