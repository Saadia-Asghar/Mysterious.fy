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


# ---------------------------------------------------------------------------------------------
# Method `upstream_anchor_quorum_v2` (kept alongside v1 so both can be evaluated).
#
# v1 groups any directly related devices that start within one window of the group's first
# event. Under overlapping faults that merges unrelated sibling failures (two cameras that
# happen to fail on the same switch). v2 requires an explanation for every grouping:
#   1. Anchored: an event joins the group of an alerting ANCESTOR whose event is within
#      `window_seconds` of it (before or after). The nearest such ancestor event wins.
#   2. Silent upstream: events with no alerting ancestor are clustered per shared immediate
#      parent (each within the window of the cluster's first event). The cluster becomes one
#      group only if at least `quorum` of that parent's known children failed and at least two
#      distinct devices are involved; otherwise every event stays its own incident.
# Quorum is fixed a priori at 0.5 (a majority-or-half of dependants), not tuned on results.
METHOD_V2 = "upstream_anchor_quorum_v2"
DEFAULT_QUORUM = 0.5
METHODS = (METHOD, METHOD_V2)
DEFAULT_METHOD = METHOD_V2  # API default; v1 stays selectable for comparison


def correlate_v2(events: list[EventLike], topology: Topology, window_seconds: int = DEFAULT_WINDOW_SECONDS,
                 quorum: float = DEFAULT_QUORUM) -> list[CorrelationGroup]:
    ordered = sorted(events, key=lambda e: (e.started_at, e.event_id))
    anchor: dict[str, str] = {}  # event_id -> event_id of the alerting ancestor that explains it
    for e in ordered:
        ups = topology.ancestors(e.device_id)
        best = None
        for other in ordered:
            if other.device_id in ups:
                gap = abs((e.started_at - other.started_at).total_seconds())
                if gap <= window_seconds and (best is None or gap < best[0]):
                    best = (gap, other.event_id)
        if best:
            anchor[e.event_id] = best[1]

    def root(eid: str) -> str:
        seen = set()
        while eid in anchor and eid not in seen:
            seen.add(eid)
            eid = anchor[eid]
        return eid

    groups: dict[str, CorrelationGroup] = {}
    rooted = set(anchor) | set(anchor.values())  # explained events and the ancestors explaining them
    for e in ordered:
        if e.event_id in rooted:
            groups.setdefault(root(e.event_id), CorrelationGroup()).events.append(e)

    # silent-upstream clusters among events nothing explains
    rest = [e for e in ordered if e.event_id not in rooted]
    children: dict[str, int] = {}
    for dev in topology.devices():
        for p in topology.parents(dev):
            children[p] = children.get(p, 0) + 1
    clusters: list[tuple[str, list]] = []
    for e in rest:
        placed = False
        for parent, members in clusters:
            if parent in topology.parents(e.device_id) and \
                    (e.started_at - members[0].started_at).total_seconds() <= window_seconds:
                members.append(e)
                placed = True
                break
        if not placed:
            parents = sorted(topology.parents(e.device_id))
            clusters.append((parents[0] if parents else "", [e]))
    for parent, members in clusters:
        devices = {m.device_id for m in members}
        if parent and len(devices) >= 2 and len(devices) / children.get(parent, len(devices)) >= quorum:
            groups[members[0].event_id] = CorrelationGroup(events=list(members))
        else:
            for m in members:
                groups[m.event_id] = CorrelationGroup(events=[m])
    out = list(groups.values())
    for g in out:
        g.events.sort(key=lambda e: (e.started_at, e.event_id))
    return sorted(out, key=lambda g: (g.first_at, g.event_ids[0]))


def correlate_with(method: str, events: list[EventLike], topology: Topology,
                   window_seconds: int = DEFAULT_WINDOW_SECONDS) -> list[CorrelationGroup]:
    if method == METHOD:
        return correlate(events, topology, window_seconds)
    if method == METHOD_V2:
        return correlate_v2(events, topology, window_seconds)
    raise ValueError(f"unknown correlation method {method!r}; expected one of {METHODS}")
