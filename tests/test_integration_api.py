import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMERA = {
    "device_id": "CAM-001",
    "name": "Entrance camera",
    "device_type": "ip_camera",
    "profile_id": "ip_camera_basic",
    "organization_id": "ORG-1",
    "site_id": "SITE-1",
    "zone_id": "ZONE-1",
    "management_address": "<authorized-address>",
    "responsible_team": "network_team",
    "enabled": True,
}


def make_client(tmp_path: Path, profiles_dir: Path | None = None) -> TestClient:
    settings = Settings(
        database_path=tmp_path / "nms.sqlite",
        profiles_dir=profiles_dir or REPO_ROOT / "device-profiles",
    )
    return TestClient(create_app(settings))


def test_health_loads_shipped_camera_profile(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "nms-integration"
    assert body["profiles"] >= 1
    assert body["devices"] == 0


def test_camera_profile_is_data(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/profiles/ip_camera_basic")
    assert response.status_code == 200
    body = response.json()
    assert body["device_type"] == "ip_camera"
    assert body["connectors"] == ["icmp"]
    assert body["default_policy"] == "monitor_only"
    assert "device_unreachable" in body["triggers"]


def test_register_device_uses_profile_policy(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post("/devices", json=CAMERA)
        assert created.status_code == 201
        assert created.json()["automation_policy"] == "monitor_only"
        listed = client.get("/devices/CAM-001")
    assert listed.status_code == 200
    assert listed.json()["profile_id"] == "ip_camera_basic"


def test_unknown_profile_and_type_mismatch_are_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        unknown = client.post("/devices", json={**CAMERA, "profile_id": "missing_profile"})
        mismatch = client.post("/devices", json={**CAMERA, "device_id": "CAM-002", "device_type": "router"})
        duplicate = client.post("/devices", json=CAMERA)
        duplicate_again = client.post("/devices", json=CAMERA)
    assert unknown.status_code == 404
    assert mismatch.status_code == 422
    assert duplicate.status_code == 201
    assert duplicate_again.status_code == 409


def test_events_and_telemetry_follow_the_device_profile(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/devices", json=CAMERA).status_code == 201
        missing_device = client.post(
            "/events",
            json={
                "device_id": "NO-SUCH",
                "event_type": "device_unreachable",
                "severity": "high",
                "started_at": "2026-11-01T10:01:01+05:00",
                "source": "zabbix",
            },
        )
        bad_type = client.post(
            "/events",
            json={
                "device_id": "CAM-001",
                "event_type": "disk_full",
                "severity": "high",
                "started_at": "2026-11-01T10:01:01+05:00",
                "source": "zabbix",
            },
        )
        event = client.post(
            "/events",
            json={
                "event_id": "EVT-1001",
                "device_id": "CAM-001",
                "event_type": "device_unreachable",
                "severity": "high",
                "started_at": "2026-11-01T10:01:01+05:00",
                "source": "zabbix",
            },
        )
        bad_metric = client.post(
            "/telemetry",
            json={
                "device_id": "CAM-001",
                "metric_name": "cpu_percent",
                "value": 10,
                "unit": "percent",
                "timestamp": "2026-11-01T10:00:00+05:00",
                "source": "zabbix",
            },
        )
        reading = client.post(
            "/telemetry",
            json={
                "device_id": "CAM-001",
                "metric_name": "latency_ms",
                "value": 42,
                "unit": "ms",
                "timestamp": "2026-11-01T10:00:00+05:00",
                "source": "zabbix",
            },
        )
        events = client.get("/events")
        telemetry = client.get("/telemetry", params={"device_id": "CAM-001"})
    assert missing_device.status_code == 404
    assert bad_type.status_code == 422
    assert event.status_code == 201
    assert event.json()["event_id"] == "EVT-1001"
    assert bad_metric.status_code == 422
    assert reading.status_code == 201
    assert events.json()[0]["device_id"] == "CAM-001"
    assert telemetry.json()[0]["metric_name"] == "latency_ms"


def test_core_accepts_a_non_camera_profile(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "router_lab.json").write_text(
        json.dumps(
            {
                "profile_id": "router_lab",
                "device_type": "router",
                "connectors": ["snmp"],
                "metrics": [{"metric_name": "reachability", "unit": "bool"}],
                "triggers": ["device_unreachable"],
                "dashboard": "router_lab",
                "default_policy": "monitor_only",
            }
        ),
        encoding="utf-8",
    )
    with make_client(tmp_path, profiles) as client:
        created = client.post(
            "/devices",
            json={
                **CAMERA,
                "device_id": "RTR-001",
                "name": "Lab router",
                "device_type": "router",
                "profile_id": "router_lab",
            },
        )
    assert created.status_code == 201
    assert created.json()["device_type"] == "router"
