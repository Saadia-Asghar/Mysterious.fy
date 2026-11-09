"""M8: time- and topology-aware event correlation.

Method `time_window_and_topology_v1`: events (sorted by start time) join an existing group
when they start within `window_seconds` of that group's first event AND their device is
directly related (see Topology.related) to a device already in the group. Otherwise they
start a new group. Each group becomes one incident.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from intelligence.topology import Topology

METHOD = "time_window_and_topology_v1"
DEFAULT_WINDOW_SECONDS = 120


class EventLike(Protocol):
    event_id: str
    device_id: str
    started_at: datetime


@dataclass
class CorrelationGroup:
    events: list = field(default_factory=list)

    @property
    def first_at(self) -> datetime:
        return self.events[0].started_at

    @property
    def event_ids(self) -> list[str]:
        return [e.event_id for e in self.events]

    @property
    def devices(self) -> list[str]:
        return list(dict.fromkeys(e.device_id for e in self.events))


def correlate(
    events: list[EventLike], topology: Topology, window_seconds: int = DEFAULT_WINDOW_SECONDS
) -> list[CorrelationGroup]:
    groups: list[CorrelationGroup] = []
    for event in sorted(events, key=lambda e: (e.started_at, e.event_id)):
        target = None
        for group in groups:
            in_window = (event.started_at - group.first_at).total_seconds() <= window_seconds
            if in_window and any(topology.related(event.device_id, d) for d in group.devices):
                target = group
                break
        if target is None:
            target = CorrelationGroup()
            groups.append(target)
        target.events.append(event)
    return groups


def reason(group: CorrelationGroup, topology: Topology, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> str:
    devices = group.devices
    if len(devices) == 1:
        return f"Single device {devices[0]}; no related failures within {window_seconds}s"
    shared = set.intersection(*(topology.ancestors(d) | {d} for d in devices))
    via = f" sharing upstream {', '.join(sorted(shared))}" if shared else ""
    return f"{', '.join(devices)} failed within {window_seconds}s and are topologically related{via}"
