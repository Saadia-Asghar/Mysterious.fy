"""M11: controlled self-healing. Policy decides, only approved playbooks run, and a finished
action moves the incident to `verifying`, never straight to `resolved`."""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from test_integration_api import CAMERA, REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "test-environment" / "simulators"))
from test_service import ServiceState, create_app as create_service  # noqa: E402

SERVICE_ADDR = "http://lab-service.test:9100"
SERVICE = {
    **CAMERA,
    "device_id": "SVC-001",
    "name": "Lab test service",
    "device_type": "test_service",
    "profile_id": "test_service_basic",
    "management_address": SERVICE_ADDR,
}


def service_transport(state: ServiceState, calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(SERVICE_ADDR)
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST" and request.url.path == "/restart":
            state.restart()
            return httpx.Response(200, json={"restarted": True})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def lab(tmp_path: Path):
    state, calls = ServiceState(), []
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings, remediation_transport=service_transport(state, calls))) as client:
        yield client, state, calls


def open_incident(client, device: dict, policy: str | None = None, event_type: str = "service_down") -> str:
    body = {**device, **({"automation_policy": policy} if policy else {})}
    assert client.post("/devices", json=body).status_code == 201
    ev = {"event_id": f"E-{device['device_id']}", "device_id": device["device_id"], "event_type": event_type,
          "severity": "high", "started_at": "2026-11-01T10:00:00+00:00", "source": "test"}
    assert client.post("/events", json=ev).status_code == 201
    client.post("/incidents/sync")
    return f"INC-E-{device['device_id']}"


def remediate(client, incident_id: str, playbook: str = "restart_test_service", **extra):
    return client.post(f"/incidents/{incident_id}/remediation", json={"playbook_id": playbook, **extra})


def test_require_approval_waits_then_runs_after_approval(lab):
    client, state, calls = lab
    state.healthy = False
    inc = open_incident(client, SERVICE)  # profile default: require_approval
    r = remediate(client, inc)
    assert r.status_code == 201
    ex = r.json()
    assert ex["status"] == "pending" and ex["policy"] == "require_approval"
    assert calls == []
    assert client.get(f"/incidents/{inc}").json()["status"] == "action_pending"

    done = client.post(f"/executions/{ex['execution_id']}/approve", json={"approved_by": "operator-1"}).json()
    assert done["status"] == "completed" and done["approved_by"] == "operator-1"
    assert calls == ["POST /restart"] and state.restarts == 1
    assert done["timestamps"]["started_at"] and done["timestamps"]["finished_at"]
    # A finished action is NOT recovery: monitoring must verify (M12).
    assert client.get(f"/incidents/{inc}").json()["status"] == "verifying"


def test_auto_remediate_runs_immediately(lab):
    client, state, calls = lab
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    ex = remediate(client, inc).json()
    assert ex["status"] == "completed" and calls == ["POST /restart"]


@pytest.mark.parametrize("policy", ["monitor_only", "recommend"])
def test_non_executing_policies_never_call_the_device(lab, policy):
    client, _, calls = lab
    inc = open_incident(client, SERVICE, policy=policy)
    ex = remediate(client, inc).json()
    assert ex["status"] == "rejected_by_policy" and policy in ex["reason"]
    assert calls == []


def test_playbook_not_allowed_for_camera_profile(lab):
    client, _, calls = lab
    inc = open_incident(client, CAMERA, policy="auto_remediate", event_type="device_unreachable")
    ex = remediate(client, inc).json()
    assert ex["status"] == "rejected_by_policy" and "not allowed by profile" in ex["reason"]
    assert calls == []


def test_unknown_playbook_is_404_and_runs_nothing(lab):
    client, _, calls = lab
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    assert remediate(client, inc, playbook="rm_rf_everything").status_code == 404
    assert calls == []


def test_target_must_belong_to_the_incident(lab):
    client, _, _ = lab
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    client.post("/devices", json={**SERVICE, "device_id": "SVC-OTHER"})
    assert remediate(client, inc, device_id="SVC-OTHER").status_code == 422


def test_failed_action_escalates(lab):
    client, _, _ = lab
    bad = {**SERVICE, "device_id": "SVC-BAD", "management_address": "http://lab-service.test:9100/missing"}
    inc = open_incident(client, bad, policy="auto_remediate")
    ex = remediate(client, inc).json()
    assert ex["status"] == "failed" and "404" in ex["detail"]
    assert client.get(f"/incidents/{inc}").json()["status"] == "escalated"


def test_reject_escalates_and_blocks_double_approval(lab):
    client, _, calls = lab
    inc = open_incident(client, SERVICE)
    ex = remediate(client, inc).json()
    assert remediate(client, inc).status_code == 409  # one pending action at a time
    rej = client.post(f"/executions/{ex['execution_id']}/reject", json={"approved_by": "operator-2"}).json()
    assert rej["status"] == "rejected_by_policy" and "operator-2" in rej["reason"]
    assert client.post(f"/executions/{ex['execution_id']}/approve", json={"approved_by": "x"}).status_code == 409
    assert client.get(f"/incidents/{inc}").json()["status"] == "escalated"
    assert calls == []


def test_stuck_service_still_reports_completed_action(lab):
    """The restart call succeeds but the service stays down. M11 must not claim recovery;
    M12 verification is what detects this."""
    client, state, _ = lab
    state.healthy, state.stuck = False, True
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    assert remediate(client, inc).json()["status"] == "completed"
    assert state.healthy is False
    assert client.get(f"/incidents/{inc}").json()["status"] == "verifying"


def test_executions_listing_and_playbooks(lab):
    client, _, _ = lab
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    ex = remediate(client, inc).json()
    assert [e["execution_id"] for e in client.get(f"/executions?incident_id={inc}").json()] == [ex["execution_id"]]
    assert client.get(f"/executions/{ex['execution_id']}").json()["status"] == "completed"
    assert client.get("/executions/EXE-nope").status_code == 404
    assert [p["playbook_id"] for p in client.get("/playbooks").json()] == ["restart_test_service"]


def test_simulator_http_behaviour():
    with TestClient(create_service()) as svc:
        assert svc.get("/health").status_code == 200
        svc.post("/fault/break")
        assert svc.get("/health").status_code == 503
        svc.post("/restart")
        assert svc.get("/health").status_code == 200
        svc.post("/fault/stuck")
        svc.post("/restart")
        assert svc.get("/health").status_code == 503
        svc.post("/fault/clear")
        assert svc.get("/health").json()["healthy"] is True
