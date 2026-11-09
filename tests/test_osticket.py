"""M6: incidents are persisted and an eligible incident opens one osTicket ticket."""
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.osticket import OsTicketClient
from app.settings import Settings
from test_incidents_api import event, seed
from test_integration_api import REPO_ROOT


class FakeOsTicket:
    """Stands in for osTicket's /api/tickets.json."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[dict] = []
        self.next = 100001

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tickets.json"
        assert request.headers["X-API-Key"] == "test-key"
        self.requests.append(json.loads(request.content))
        if self.status != 201:
            return httpx.Response(self.status, text="Unauthorized: valid API key required")
        number = str(self.next)
        self.next += 1
        return httpx.Response(201, text=number)


def client_with(tmp_path: Path, fake: FakeOsTicket, **overrides) -> TestClient:
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles", **overrides)
    provider = OsTicketClient(
        base_url="http://osticket.test",
        api_key="test-key",
        reporter_email="nms@example.invalid",
        transport=httpx.MockTransport(fake.handler),
    )
    return TestClient(create_app(settings, ticket_provider=provider))


def switch_outage(client) -> None:
    seed(client)
    for e in [event("E1", "SWITCH-A", 0), event("E2", "CAM-001", 4), event("E3", "CAM-002", 5)]:
        assert client.post("/events", json=e).status_code == 201


def test_switch_outage_opens_exactly_one_meaningful_ticket(tmp_path: Path) -> None:
    fake = FakeOsTicket()
    with client_with(tmp_path, fake) as client:
        switch_outage(client)
        r = client.post("/incidents/sync").json()
        assert r["ticketing"] == "enabled"
        assert r["incidents_created"] == ["INC-E1"]
        assert [t["external_ticket_id"] for t in r["tickets_created"]] == ["100001"]
        assert len(fake.requests) == 1
        sent = fake.requests[0]
        assert "INC-E1" in sent["subject"] and "probable cause SWITCH-A" in sent["subject"]
        assert "CAM-001" in sent["message"] and "topology_time_v1" in sent["message"]

        incident = client.get("/incidents/INC-E1").json()
        assert incident["status"] == "open"
        assert incident["ticket"]["provider"] == "osticket"
        assert incident["ticket"]["external_ticket_id"] == "100001"


def test_sync_is_idempotent_and_updates_growing_incident(tmp_path: Path) -> None:
    fake = FakeOsTicket()
    with client_with(tmp_path, fake) as client:
        switch_outage(client)
        client.post("/incidents/sync")
        client.post("/events", json=event("E5", "CAM-001", 30) | {"event_id": "E5", "event_type": "high_latency"})
        r = client.post("/incidents/sync").json()
        assert r["incidents_created"] == [] and r["incidents_updated"] == ["INC-E1"]
        assert r["tickets_created"] == []
        assert len(fake.requests) == 1
        assert "E5" in client.get("/incidents/INC-E1").json()["event_ids"]


def test_osticket_failure_keeps_incident_and_retries_later(tmp_path: Path) -> None:
    fake = FakeOsTicket(status=401)
    with client_with(tmp_path, fake) as client:
        switch_outage(client)
        r = client.post("/incidents/sync").json()
        assert "HTTP 401" in r["ticket_errors"]["INC-E1"]
        stored = client.get("/incidents/INC-E1").json()
        assert stored["ticket"] is None and "401" in stored["ticket_error"]

        fake.status = 201
        r = client.post("/incidents/sync").json()
        assert r["tickets_created"][0]["incident_id"] == "INC-E1"
        assert client.get("/incidents/INC-E1").json()["ticket_error"] is None


def test_low_severity_does_not_open_ticket(tmp_path: Path) -> None:
    fake = FakeOsTicket()
    with client_with(tmp_path, fake, ticket_min_severity="high") as client:
        seed(client)
        client.post("/events", json=event("E1", "CAM-004", 0) | {"severity": "warning"})
        r = client.post("/incidents/sync").json()
        assert r["incidents_created"] == ["INC-E1"] and r["tickets_created"] == []
        assert fake.requests == []


def test_ticketing_disabled_without_configuration(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings)) as client:
        seed(client)
        client.post("/events", json=event("E1", "CAM-004", 0))
        r = client.post("/incidents/sync").json()
        assert r["ticketing"] == "disabled" and r["incidents_created"] == ["INC-E1"]


def test_unknown_incident_404(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings)) as client:
        assert client.get("/incidents/INC-nope").status_code == 404
