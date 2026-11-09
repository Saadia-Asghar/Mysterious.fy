"""M12: Zabbix verification after remediation. Only monitoring decides recovery."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.osticket import OsTicketClient
from app.settings import Settings
from app.zabbix_api import ZabbixApiClient
from test_integration_api import REPO_ROOT
from test_osticket import FakeOsTicket
from test_remediation import SERVICE, open_incident, remediate, service_transport
from test_service import ServiceState


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def fake_zabbix(state: ServiceState, known_hosts=("SVC-001",), fail: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer zbx-test-token"
        if fail:
            return httpx.Response(500)
        body = json.loads(request.content)
        if body["method"] == "host.get":
            host = body["params"]["filter"]["host"][0]
            result = [{"hostid": "10500"}] if host in known_hosts else []
        else:
            result = [] if state.healthy else [{"eventid": "77", "name": "Service down", "severity": "4"}]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": body["id"]})

    return httpx.MockTransport(handler)


@pytest.fixture
def env(tmp_path: Path):
    state, calls, clock, tickets = ServiceState(), [], Clock(), FakeOsTicket()
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles",
                        verify_timeout_seconds=300, ticket_min_severity="disaster")  # no ticket at sync time
    app = create_app(
        settings,
        ticket_provider=OsTicketClient("http://osticket.test", "test-key", "nms@example.invalid",
                                       transport=httpx.MockTransport(tickets.handler)),
        remediation_transport=service_transport(state, calls),
        zabbix_api=ZabbixApiClient("http://zabbix.test/api_jsonrpc.php", "zbx-test-token",
                                   transport=fake_zabbix(state)),
        clock=clock,
    )
    with TestClient(app) as client:
        yield client, state, clock, tickets


def remediated(client, state, broken="break"):
    state.healthy, state.stuck = False, broken == "stuck"
    inc = open_incident(client, SERVICE, policy="auto_remediate")
    ex = remediate(client, inc).json()
    assert ex["status"] == "completed"
    return inc, ex["execution_id"]


def test_successful_restart_is_verified_and_resolved(env):
    client, state, _, tickets = env
    inc, ex = remediated(client, state)
    assert state.healthy  # restart really fixed it
    out = client.post(f"/executions/{ex}/verify").json()
    assert out["incident_status"] == "resolved"
    v = out["verification"]
    assert v["healthy"] and v["source"] == "zabbix" and v["execution_id"] == ex
    assert client.get(f"/incidents/{inc}").json()["status"] == "resolved"
    assert [x["healthy"] for x in client.get(f"/verifications?incident_id={inc}").json()] == [True]
    assert tickets.requests == []


def test_stuck_service_stays_verifying_then_escalates_with_ticket(env):
    client, state, clock, tickets = env
    inc, ex = remediated(client, state, broken="stuck")

    early = client.post(f"/executions/{ex}/verify").json()
    assert early["incident_status"] == "verifying"
    assert not early["verification"]["healthy"] and "Service down" in early["verification"]["summary"]
    assert tickets.requests == []

    clock.advance(301)
    late = client.post(f"/executions/{ex}/verify").json()
    assert late["incident_status"] == "escalated"
    assert late["ticket"]["external_ticket_id"] == "100001"
    assert len(tickets.requests) == 1
    assert "still reports SVC-001 unhealthy" in tickets.requests[0]["message"]
    assert client.get(f"/incidents/{inc}").json()["status"] == "escalated"
    # Escalated incidents are no longer awaiting verification
    assert client.post(f"/executions/{ex}/verify").status_code == 409


def test_zabbix_recovery_webhook_resolves(env):
    client, state, _, _ = env
    inc, _ = remediated(client, state)
    r = client.post("/integrations/zabbix/events", json={
        "eventid": "900", "host": "SVC-001", "nms_event_type": "service_down",
        "severity": "4", "value": "0", "clock": "1730000000"})
    assert r.status_code == 202
    assert r.json()["verified"] == [{"incident_id": inc, "incident_status": "resolved"}]
    assert client.get(f"/incidents/{inc}").json()["status"] == "resolved"


def test_recovery_for_other_host_does_not_resolve(env):
    client, state, _, _ = env
    inc, _ = remediated(client, state)
    r = client.post("/integrations/zabbix/events", json={
        "eventid": "901", "host": "CAM-001", "nms_event_type": "device_unreachable",
        "severity": "4", "value": "0", "clock": "1730000000"})
    assert r.json()["verified"] == []
    assert client.get(f"/incidents/{inc}").json()["status"] == "verifying"


def test_sweep_verifies_all_waiting(env):
    client, state, _, _ = env
    remediated(client, state)
    outcomes = client.post("/verification/sweep").json()
    assert [o["incident_status"] for o in outcomes] == ["resolved"]
    assert client.post("/verification/sweep").json() == []


def test_pending_execution_cannot_be_verified(env):
    client, _, _, _ = env
    inc = open_incident(client, SERVICE)  # require_approval -> pending
    ex = remediate(client, inc).json()["execution_id"]
    assert client.post(f"/executions/{ex}/verify").status_code == 409
    assert client.post("/executions/EXE-nope/verify").status_code == 404


def test_zabbix_errors_do_not_change_state(tmp_path: Path):
    state = ServiceState()
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    app = create_app(settings, remediation_transport=service_transport(state, []),
                     zabbix_api=ZabbixApiClient("http://zabbix.test/api_jsonrpc.php", "zbx-test-token",
                                                transport=fake_zabbix(state, fail=True)))
    with TestClient(app) as client:
        inc, ex = remediated(client, state)
        assert client.post(f"/executions/{ex}/verify").status_code == 502
        assert client.get(f"/incidents/{inc}").json()["status"] == "verifying"
        assert client.get("/verifications").json() == []


def test_unmonitored_host_and_unconfigured_api(tmp_path: Path):
    state = ServiceState()
    settings = Settings(database_path=tmp_path / "a.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    app = create_app(settings, remediation_transport=service_transport(state, []),
                     zabbix_api=ZabbixApiClient("http://zabbix.test/api_jsonrpc.php", "zbx-test-token",
                                                transport=fake_zabbix(state, known_hosts=())))
    with TestClient(app) as client:
        _, ex = remediated(client, state)
        r = client.post(f"/executions/{ex}/verify")
        assert r.status_code == 502 and "not monitored" in r.json()["detail"]

    settings = Settings(database_path=tmp_path / "b.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings, remediation_transport=service_transport(state, []))) as client:
        _, ex = remediated(client, state)
        assert client.post(f"/executions/{ex}/verify").status_code == 503
