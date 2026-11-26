"""M5: a Zabbix problem becomes a normalized event with a stable ID."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from test_integration_api import CAMERA, REPO_ROOT, make_client

PROBLEM = {
    "eventid": "4711",
    "host": "CAM-001",
    "nms_event_type": "device_unreachable",
    "severity": "High",
    "value": "1",
    "clock": "1730000000",
}
URL = "/integrations/zabbix/events"


def test_problem_becomes_normalized_event(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        r = client.post(URL, json=PROBLEM)
        assert r.status_code == 201, r.text
        event = r.json()["event"]
        assert event == {
            "event_id": "ZBX-4711",
            "device_id": "CAM-001",
            "event_type": "device_unreachable",
            "severity": "high",
            "started_at": "2024-10-27T03:33:20Z",
            "source": "zabbix",
        }
        assert [e["event_id"] for e in client.get("/events").json()] == ["ZBX-4711"]


def test_numeric_severity_maps_to_zabbix_names(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        r = client.post(URL, json={**PROBLEM, "severity": "5"})
        assert r.json()["event"]["severity"] == "disaster"


def test_redelivery_is_idempotent(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        assert client.post(URL, json=PROBLEM).status_code == 201
        again = client.post(URL, json=PROBLEM)
        assert again.status_code == 200
        assert again.json()["status"] == "duplicate"
        assert len(client.get("/events").json()) == 1


def test_recovery_is_acknowledged_not_stored(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        r = client.post(URL, json={**PROBLEM, "value": "0"})
        assert r.status_code == 202
        assert r.json() == {"status": "recovery_received", "event_id": "ZBX-4711", "verified": []}
        assert client.get("/events").json() == []


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post(URL, json=PROBLEM).status_code == 404


def test_event_type_must_be_in_profile(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        r = client.post(URL, json={**PROBLEM, "nms_event_type": "disk_full"})
        assert r.status_code == 422


def test_bad_severity_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post("/devices", json=CAMERA)
        assert client.post(URL, json={**PROBLEM, "severity": "urgent"}).status_code == 422


def test_webhook_token_enforced_when_configured(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "nms.sqlite",
        profiles_dir=REPO_ROOT / "device-profiles",
        zabbix_webhook_token="test-token",
    )
    with TestClient(create_app(settings)) as client:
        client.post("/devices", json=CAMERA)
        assert client.post(URL, json=PROBLEM).status_code == 401
        ok = client.post(URL, json=PROBLEM, headers={"X-NMS-Webhook-Token": "test-token"})
        assert ok.status_code == 201
