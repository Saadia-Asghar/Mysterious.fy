"""M7–M9 unit tests using the specification's fault scenarios."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from intelligence.correlation import correlate
from intelligence.rca import rank
from intelligence.topology import Topology, TopologyCycle

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


@dataclass
class Ev:
    event_id: str
    device_id: str
    started_at: datetime


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def topo() -> Topology:
    #        CORE
    #       /    \
    #  SWITCH-A  SWITCH-B
    #  CAM-1..3  CAM-4..5
    return Topology(
        [
            ("SWITCH-A", "CORE"),
            ("SWITCH-B", "CORE"),
            ("CAM-001", "SWITCH-A"),
            ("CAM-002", "SWITCH-A"),
            ("CAM-003", "SWITCH-A"),
            ("CAM-004", "SWITCH-B"),
            ("CAM-005", "SWITCH-B"),
        ]
    )


# --- M7 topology ---------------------------------------------------------

def test_ancestors(topo):
    assert topo.ancestors("CAM-001") == {"SWITCH-A", "CORE"}


def test_cycle_rejected(topo):
    with pytest.raises(TopologyCycle):
        topo.add("CORE", "CAM-001")
    with pytest.raises(TopologyCycle):
        topo.add("CAM-001", "CAM-001")


def test_related_rules(topo):
    assert topo.related("CAM-001", "SWITCH-A")  # upstream
    assert topo.related("CAM-001", "CAM-002")  # siblings
    assert not topo.related("CAM-001", "CAM-004")  # only share distant CORE


# --- M8 correlation ------------------------------------------------------

def test_switch_failure_becomes_one_incident(topo):
    events = [
        Ev("E1", "SWITCH-A", at(0)),
        Ev("E2", "CAM-001", at(5)),
        Ev("E3", "CAM-002", at(6)),
        Ev("E4", "CAM-003", at(8)),
    ]
    groups = correlate(events, topo)
    assert len(groups) == 1
    assert groups[0].event_ids == ["E1", "E2", "E3", "E4"]


def test_unrelated_cameras_stay_apart(topo):
    groups = correlate([Ev("E1", "CAM-001", at(0)), Ev("E2", "CAM-004", at(3))], topo)
    assert len(groups) == 2


def test_same_device_outside_window_is_new_incident(topo):
    groups = correlate([Ev("E1", "CAM-001", at(0)), Ev("E2", "CAM-002", at(600))], topo, window_seconds=120)
    assert len(groups) == 2


def test_input_order_does_not_matter(topo):
    events = [Ev("E3", "CAM-002", at(6)), Ev("E1", "SWITCH-A", at(0)), Ev("E2", "CAM-001", at(5))]
    assert correlate(events, topo)[0].event_ids == ["E1", "E2", "E3"]


# --- M9 RCA --------------------------------------------------------------

def test_rca_ranks_alerting_switch_first(topo):
    events = [Ev("E1", "SWITCH-A", at(0)), Ev("E2", "CAM-001", at(5)), Ev("E3", "CAM-002", at(6))]
    ranked = rank(correlate(events, topo)[0], topo)
    assert ranked[0].device_id == "SWITCH-A"
    assert abs(sum(r.score for r in ranked) - 1) < 1e-3


def test_rca_finds_silent_upstream_switch(topo):
    # switch itself not monitored / not alerting; only its cameras fail
    events = [Ev("E1", "CAM-001", at(0)), Ev("E2", "CAM-002", at(2)), Ev("E3", "CAM-003", at(4))]
    ranked = rank(correlate(events, topo)[0], topo)
    assert ranked[0].device_id == "SWITCH-A"
    assert "silent upstream" in ranked[0].reason


def test_rca_single_device(topo):
    ranked = rank(correlate([Ev("E1", "CAM-004", at(0))], topo)[0], topo)
    assert [r.device_id for r in ranked] == ["CAM-004"]
    assert ranked[0].score == 1.0


def test_rca_without_topology_falls_back_to_first_failure():
    empty = Topology()
    events = [Ev("E1", "X", at(0)), Ev("E2", "X", at(1))]
    ranked = rank(correlate(events, empty)[0], empty)
    assert ranked[0].device_id == "X"


# ---- correlation v2 (upstream_anchor_quorum_v2) ---------------------------

def _v2_topology():
    from intelligence.topology import Topology
    edges = [("SW-1", "CORE"), ("SW-2", "CORE")]
    edges += [(f"CAM-1{i}", "SW-1") for i in range(1, 5)] + [(f"CAM-2{i}", "SW-2") for i in range(1, 5)]
    return Topology(edges)


def _ev(eid, dev, sec):
    from dataclasses import dataclass
    from datetime import datetime, timedelta, timezone

    @dataclass
    class E:
        event_id: str
        device_id: str
        started_at: datetime
    return E(eid, dev, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=sec))


def test_v2_siblings_below_quorum_stay_separate():
    from intelligence.correlation import correlate, correlate_v2
    events = [_ev("E1", "CAM-11", 0), _ev("E2", "CAM-12", 30)]
    assert len(correlate(events, _v2_topology())) == 1                 # v1 always merges siblings
    assert len(correlate_v2(events, _v2_topology())) == 1              # 2 of 4 = 0.5 meets the default quorum
    assert len(correlate_v2(events, _v2_topology(), quorum=0.75)) == 2  # below quorum: separate incidents


def test_v2_silent_upstream_needs_quorum():
    from intelligence.correlation import correlate_v2
    events = [_ev("E1", "CAM-11", 0), _ev("E2", "CAM-12", 20), _ev("E3", "CAM-13", 40)]
    groups = correlate_v2(events, _v2_topology())
    assert [g.event_ids for g in groups] == [["E1", "E2", "E3"]]


def test_v2_anchors_to_alerting_upstream_even_after_slow_cascade():
    from intelligence.correlation import correlate_v2
    events = [_ev("E1", "SW-1", 0), _ev("E2", "CAM-11", 100), _ev("E3", "CAM-21", 50)]
    groups = {tuple(g.event_ids) for g in correlate_v2(events, _v2_topology())}
    assert groups == {("E1", "E2"), ("E3",)}


def test_unknown_method_rejected():
    import pytest
    from intelligence.correlation import correlate_with
    with pytest.raises(ValueError):
        correlate_with("nope", [], _v2_topology())
