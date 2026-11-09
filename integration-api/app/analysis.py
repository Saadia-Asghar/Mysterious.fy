"""Glue between stored NMS records and the intelligence layer (intelligence/ package)."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from intelligence import anomaly, correlation, rca  # noqa: E402
from intelligence.topology import Topology, TopologyCycle  # noqa: E402

from app.schemas import (  # noqa: E402
    AnomalyOut,
    CorrelationOut,
    Event,
    IncidentAnalysis,
    RankedCauseOut,
    RcaOut,
    Telemetry,
    TopologyEdge,
)

__all__ = ["DEFAULT_WINDOW_SECONDS", "TopologyCycle", "analyze", "build_topology", "score_anomalies", "severity_at_least", "ticket_text"]

DEFAULT_WINDOW_SECONDS = correlation.DEFAULT_WINDOW_SECONDS
SEVERITY_ORDER = ["not_classified", "information", "warning", "average", "high", "disaster"]


def build_topology(edges: list[TopologyEdge]) -> Topology:
    return Topology((e.from_device_id, e.to_device_id) for e in edges if e.relationship == "depends_on")


def analyze(events: list[Event], edges: list[TopologyEdge], window_seconds: int,
            method: str = correlation.DEFAULT_METHOD) -> list[IncidentAnalysis]:
    topology = build_topology(edges)
    incidents = []
    for group in correlation.correlate_with(method, events, topology, window_seconds):
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
                    method=method, reason=correlation.reason(group, topology, window_seconds)
                ),
                rca=RcaOut(
                    method=rca.METHOD,
                    ranked_causes=[RankedCauseOut(device_id=r.device_id, score=r.score, reason=r.reason) for r in ranked],
                ),
            )
        )
    return incidents


def severity_at_least(severity: str, minimum: str) -> bool:
    return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(minimum)


def ticket_text(inc: IncidentAnalysis, note: str | None = None) -> tuple[str, str]:
    """Human-readable ticket subject and body. Everything an engineer needs to start."""
    top = inc.rca.ranked_causes[0] if inc.rca.ranked_causes else None
    subject = f"[NMS {inc.severity.upper()}] {inc.incident_id}: {len(inc.affected_devices)} device(s) affected"
    if top:
        subject += f", probable cause {top.device_id}"
    lines = [
        f"Incident: {inc.incident_id}",
        f"Severity: {inc.severity}",
        f"Started: {inc.created_at.isoformat()}",
        f"Affected devices: {', '.join(inc.affected_devices)}",
        f"Events: {', '.join(inc.event_ids)}",
        "",
        f"Correlation ({inc.correlation.method}): {inc.correlation.reason}",
        "",
        f"Probable root causes ({inc.rca.method}, ranked; scores are heuristic ranks, not probabilities):",
    ]
    for i, cause in enumerate(inc.rca.ranked_causes[:5], 1):
        lines.append(f"  {i}. {cause.device_id}  score {cause.score:.2f}  - {cause.reason}")
    if note:
        lines += ["", note]
    lines += ["", "Opened automatically by the NMS integration service. Automation policy: human handling."]
    return subject, "\n".join(lines)


def score_anomalies(telemetry: list[Telemetry], window: int, threshold: float) -> list[AnomalyOut]:
    """Score every (device, metric) series separately, oldest first."""
    series: dict[tuple[str, str], list[anomaly.Reading]] = {}
    for t in telemetry:
        series.setdefault((t.device_id, t.metric_name), []).append(anomaly.Reading(t.timestamp, t.value))
    out: list[AnomalyOut] = []
    for (device_id, metric_name), readings in sorted(series.items()):
        for r in anomaly.score_series(readings, window=window, threshold=threshold):
            out.append(AnomalyOut(device_id=device_id, metric_name=metric_name, **r.__dict__))
    return out
