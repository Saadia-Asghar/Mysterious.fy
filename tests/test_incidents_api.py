"""M7–M9 through the integration API: topology edges + incidents with correlation and RCA."""
from pathlib import Path

from test_integration_api import CAMERA, make_client


def device(device_id: str, kind: str = "camera") -> dict:
    if kind == "switch":
        return {**CAMERA, "device_id": device_id, "name": device_id,
                "device_type": "network_switch", "profile_id": "network_switch_basic"}
    return {**CAMERA, "device_id": device_id, "name": device_id}


def event(event_id: str, device_id: str, second: int) -> dict:
    return {"event_id": event_id, "device_id": device_id, "event_type": "device_unreachable",
            "severity": "high", "started_at": f"2026-11-01T10:00:{second:02d}+00:00", "source": "test"}


def seed(client) -> None:
    for d in ["SWITCH-A", "SWITCH-B"]:
        assert client.post("/devices", json=device(d, "switch")).status_code == 201
    for cam, sw in [("CAM-001", "SWITCH-A"), ("CAM-002", "SWITCH-A"), ("CAM-004", "SWITCH-B")]:
        assert client.post("/devices", json=device(cam)).status_code == 201
        r = client.post("/topology/edges", json={"from_device_id": cam, "to_device_id": sw})
        assert r.status_code == 201, r.text


def test_switch_failure_is_one_incident_with_switch_as_top_cause(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        seed(client)
        for e in [event("E1", "SWITCH-A", 0), event("E2", "CAM-001", 4), event("E3", "CAM-002", 5),
                  event("E4", "CAM-004", 6)]:
            assert client.post("/events", json=e).status_code == 201
        incidents = client.get("/intelligence/incidents").json()
        assert len(incidents) == 2
        main, other = incidents
        assert main["event_ids"] == ["E1", "E2", "E3"]
        assert main["incident_id"] == "INC-E1"
        assert main["rca"]["method"] == "topology_time_v1"
        assert main["rca"]["ranked_causes"][0]["device_id"] == "SWITCH-A"
        assert other["affected_devices"] == ["CAM-004"]


def test_edge_validation(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        seed(client)
        edge = {"from_device_id": "CAM-001", "to_device_id": "SWITCH-A"}
        assert client.post("/topology/edges", json=edge).status_code == 409
        assert client.post("/topology/edges",
                           json={"from_device_id": "SWITCH-A", "to_device_id": "CAM-001"}).status_code == 422
        assert client.post("/topology/edges",
                           json={"from_device_id": "CAM-404", "to_device_id": "SWITCH-A"}).status_code == 404
        assert len(client.get("/topology/edges").json()) == 3


def test_window_parameter_validated(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/intelligence/incidents?window_seconds=0").status_code == 422


def test_partial_incident_is_continued_not_duplicated(tmp_path):
    """Live alerts arrive seconds apart: the first sync sees one camera, the next sees the
    switch and both cameras. The second sync must continue the first incident, not add one."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.settings import Settings
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    with TestClient(create_app(Settings(database_path=tmp_path / "n.sqlite", profiles_dir=root / "device-profiles"))) as c:
        base = {"organization_id": "O", "site_id": "S", "zone_id": "Z", "management_address": "<a>",
                "responsible_team": "t"}
        c.post("/devices", json={**base, "device_id": "SW", "name": "sw", "device_type": "network_switch",
                                 "profile_id": "network_switch_basic"})
        for cam in ("C1", "C2"):
            c.post("/devices", json={**base, "device_id": cam, "name": cam, "device_type": "ip_camera",
                                     "profile_id": "ip_camera_basic"})
            c.post("/topology/edges", json={"from_device_id": cam, "to_device_id": "SW"})
        ev = lambda eid, dev, t: {"event_id": eid, "device_id": dev, "event_type": "device_unreachable",  # noqa: E731
                                  "severity": "high", "started_at": f"2026-01-01T00:00:{t}Z", "source": "t"}
        c.post("/events", json=ev("E2", "C1", "05"))
        first = c.post("/incidents/sync").json()["incidents_created"]
        assert first == ["INC-E2"]
        c.post("/events", json=ev("E1", "SW", "02"))
        c.post("/events", json=ev("E3", "C2", "07"))
        r = c.post("/incidents/sync").json()
        assert r["incidents_created"] == [] and r["incidents_updated"] == ["INC-E2"]
        incs = c.get("/incidents").json()
        assert len(incs) == 1
        assert set(incs[0]["affected_devices"]) == {"SW", "C1", "C2"}
        assert incs[0]["rca"]["ranked_causes"][0]["device_id"] == "SW"
