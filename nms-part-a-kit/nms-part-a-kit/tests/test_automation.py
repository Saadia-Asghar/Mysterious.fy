"""Part A: the automation cycle (sync -> choose an approved playbook -> verify with Zabbix).

The cycle never decides what is allowed to run: the device's automation policy does (M11)."""
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.osticket import OsTicketClient
from app.settings import Settings
from app.zabbix_api import ZabbixApiClient
from test_integration_api import CAMERA, REPO_ROOT
from test_osticket import FakeOsTicket
from test_remediation import SERVICE, service_transport
from test_service import ServiceState
from test_verification import Clock, fake_zabbix


def build(tmp_path: Path, *, zabbix: bool = True, zabbix_down: bool = False, interval: int = 0):
    state, calls, clock, tickets = ServiceState(), [], Clock(), FakeOsTicket()
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles",
                        verify_timeout_seconds=300, ticket_min_severity="disaster",
                        automation_interval_seconds=interval)
    app = create_app(
        settings,
        ticket_provider=OsTicketClient("http://osticket.test", "test-key", "nms@example.invalid",
                                       transport=httpx.MockTransport(tickets.handler)),
        remediation_transport=service_transport(state, calls),
        zabbix_api=ZabbixApiClient("http://zabbix.test/api_jsonrpc.php", "zbx-test-token",
                                   transport=fake_zabbix(state, known_hosts=("SVC-001", "CAM-001"), fail=zabbix_down))
        if zabbix else None,
        clock=clock,
    )
    return TestClient(app), state, calls, clock, tickets


@pytest.fixture
def env(tmp_path: Path):
    client, state, calls, clock, tickets = build(tmp_path)
    with client:
        yield client, state, calls, clock, tickets


def report(client, device: dict, policy: str, event_type: str = "service_down") -> str:
    """What Zabbix does: the device exists and a problem event arrives. Nobody calls /incidents/sync."""
    assert client.post("/devices", json={**device, "automation_policy": policy}).status_code == 201
    event = {"event_id": f"E-{device['device_id']}", "device_id": device["device_id"], "event_type": event_type,
             "severity": "high", "started_at": "2026-11-01T10:00:00+00:00", "source": "zabbix"}
    assert client.post("/events", json=event).status_code == 201
    return f"INC-E-{device['device_id']}"


def test_auto_remediate_heals_and_resolves_in_one_cycle(env):
    client, state, calls, _, tickets = env
    state.healthy = False
    incident = report(client, SERVICE, "auto_remediate")

    result = client.post("/automation/run").json()

    assert result["sync"]["incidents_created"] == [incident]
    assert [e["status"] for e in result["remediations"]] == ["completed"]
    assert [v["incident_status"] for v in result["verifications"]] == ["resolved"]
    assert result["errors"] == {}
    assert calls == ["POST /restart"]
    assert client.get(f"/incidents/{incident}").json()["status"] == "resolved"
    assert tickets.requests == []


def test_require_approval_waits_once_then_heals_after_approval(env):
    client, state, calls, _, _ = env
    state.healthy = False
    incident = report(client, SERVICE, "require_approval")

    first = client.post("/automation/run").json()
    [pending] = first["remediations"]
    assert pending["status"] == "pending" and calls == []
    assert client.get(f"/incidents/{incident}").json()["status"] == "action_pending"

    again = client.post("/automation/run").json()
    assert again["remediations"] == [] and len(client.get("/executions").json()) == 1

    assert client.post(f"/executions/{pending['execution_id']}/approve", json={"approved_by": "ali"}).status_code == 200
    client.post("/automation/run")
    assert calls == ["POST /restart"]
    assert client.get(f"/incidents/{incident}").json()["status"] == "resolved"


@pytest.mark.parametrize("policy", ["monitor_only", "recommend"])
def test_non_executing_policies_record_a_blocked_decision_and_touch_nothing(env, policy):
    client, state, calls, _, _ = env
    state.healthy = False
    incident = report(client, SERVICE, policy)

    result = client.post("/automation/run").json()

    assert [e["status"] for e in result["remediations"]] == ["rejected_by_policy"]
    assert calls == [] and client.get(f"/incidents/{incident}").json()["status"] == "open"
    assert client.post("/automation/run").json()["remediations"] == []


def test_profile_without_playbooks_is_left_to_humans(env):
    client, _, calls, _, _ = env
    report(client, CAMERA, "auto_remediate", event_type="device_unreachable")
    result = client.post("/automation/run").json()
    assert result["remediations"] == [] and result["errors"] == {} and calls == []
    assert client.get("/executions").json() == []


def test_stuck_service_is_escalated_to_a_ticket_after_the_timeout(env):
    client, state, _, clock, tickets = env
    state.healthy, state.stuck = False, True
    incident = report(client, SERVICE, "auto_remediate")

    first = client.post("/automation/run").json()
    assert [v["incident_status"] for v in first["verifications"]] == ["verifying"]
    assert tickets.requests == []

    clock.advance(301)
    second = client.post("/automation/run").json()
    assert [v["incident_status"] for v in second["verifications"]] == ["escalated"]
    assert len(tickets.requests) == 1
    assert client.get(f"/incidents/{incident}").json()["status"] == "escalated"


def test_zabbix_outage_is_reported_and_does_not_stop_the_cycle(tmp_path: Path):
    client, state, calls, _, _ = build(tmp_path, zabbix_down=True)
    with client:
        state.healthy = False
        incident = report(client, SERVICE, "auto_remediate")
        result = client.post("/automation/run").json()
        assert calls == ["POST /restart"] and result["verifications"] == []
        assert incident in result["errors"]
        assert client.get(f"/incidents/{incident}").json()["status"] == "verifying"


def test_without_zabbix_api_the_cycle_still_remediates(tmp_path: Path):
    client, state, calls, _, _ = build(tmp_path, zabbix=False)
    with client:
        state.healthy = False
        report(client, SERVICE, "auto_remediate")
        result = client.post("/automation/run").json()
        assert calls == ["POST /restart"] and result["verifications"] == [] and result["errors"] == {}


def test_background_loop_runs_the_cycle_by_itself(tmp_path: Path):
    client, state, calls, _, _ = build(tmp_path, interval=1)
    with client:
        state.healthy = False
        incident = report(client, SERVICE, "auto_remediate")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and client.get(f"/incidents/{incident}").json().get("status") != "resolved":
            time.sleep(0.2)  # the incident only exists once the loop's first cycle has synced it
        assert client.get(f"/incidents/{incident}").json()["status"] == "resolved"
        assert calls == ["POST /restart"]
