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
