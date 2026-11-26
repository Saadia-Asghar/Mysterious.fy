"""Running without anyone watching: email alerts, background tickets, natural-recovery MTTR, backups."""
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.notify import Notifier, SmtpConfig
from app.settings import Settings
from app.store import Store
from app.zabbix_api import ZabbixApiClient
from tests._creds import pw
from tests.test_live_monitoring import FakeZabbix

REPO_ROOT = Path(__file__).resolve().parents[1]


class Outbox:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, msg):
        if self.fail:
            raise OSError("mail server down")
        self.sent.append(msg)


def make(tmp_path, outbox=None, fake=None, **kw):
    s = Settings(database_path=tmp_path / "n.sqlite", profiles_dir=REPO_ROOT / "device-profiles", portal_secret="s",
                 backup_dir=tmp_path / "backups", **kw)
    notifier = None
    if outbox is not None:
        notifier = Notifier(Store(s.database_path), SmtpConfig(host="smtp.test", sender="nms@test.invalid"),
                            send=outbox, background=False)
    zbx = ZabbixApiClient("http://zbx/api_jsonrpc.php", "tok", transport=httpx.MockTransport(fake)) if fake else None
    return TestClient(create_app(s, zabbix_api=zbx, notifier=notifier))


def company(c):
    """Owner, a technician in team 'cctv', and a camera routed to that team."""
    t = c.post("/portal/setup", json={"organization": {"organization_id": "ACME", "name": "Acme"},
                                      "email": "o@acme.test", "full_name": "O", "password": pw("owner")}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    c.post("/portal/sites", headers=h, json={"site_id": "HQ", "name": "HQ"})
    uid = c.post("/portal/users", headers=h, json={"email": "tech@acme.test", "full_name": "Tech",
                                                    "password": pw("tech"), "role": "technician"}).json()["user_id"]
    team = c.post("/portal/teams", headers=h, json={"name": "cctv"}).json()["team_id"]
    c.put(f"/portal/teams/{team}/members", headers=h, json={"user_ids": [uid]})
    c.post("/portal/devices", headers=h, json={"device_id": "CAM-1", "name": "c", "profile_id": "ip_camera_basic",
                                                "site_id": "HQ", "management_address": "cam1.lan",
                                                "responsible_team": "cctv"})
    return h, uid


def outage(c, eid="E1"):
    c.post("/events", json={"event_id": eid, "device_id": "CAM-1", "event_type": "device_unreachable",
                            "severity": "high", "started_at": "2026-01-01T00:00:01Z", "source": "zabbix"})


def test_background_cycle_opens_ticket_and_emails_the_team(tmp_path):
    box = Outbox()
    with make(tmp_path, box) as c:
        h, _ = company(c)
        outage(c)
        c.app.state.auto_cycle()  # nobody has the portal open
        assert len(box.sent) == 1
        msg = box.sent[0]
        assert msg["To"] == "tech@acme.test" and "New ticket" in msg["Subject"] and "CAM-1" in msg.get_content()
        log = c.get("/portal/notifications", headers=h).json()
        assert [(n["recipient"], n["status"]) for n in log] == [("tech@acme.test", "sent")]
        c.app.state.auto_cycle()
        assert len(box.sent) == 1  # no duplicate alert for the same ticket


def test_failed_email_is_kept_and_retried(tmp_path):
    box = Outbox(fail=True)
    with make(tmp_path, box) as c:
        h, _ = company(c)
        outage(c)
        c.app.state.auto_cycle()
        n = c.get("/portal/notifications", headers=h).json()[0]
        assert n["status"] == "failed" and "mail server down" in n["error"]
        box.fail = False
        c.app.state.auto_cycle()
        assert c.get("/portal/notifications", headers=h).json()[0]["status"] == "sent" and len(box.sent) == 1


def test_assignment_emails_the_assignee_not_the_person_assigning(tmp_path):
    box = Outbox()
    with make(tmp_path, box) as c:
        h, uid = company(c)
        tid = c.post("/portal/tickets", headers=h, json={"title": "Check lens", "priority": "low"}).json()["ticket_id"]
        assert box.sent == []  # unassigned: nobody to tell
        c.patch(f"/portal/tickets/{tid}", headers=h, json={"assignee_id": uid})
        assert [m["To"] for m in box.sent] == ["tech@acme.test"] and "assigned to you" in box.sent[0]["Subject"]


def test_without_smtp_alerts_are_recorded_not_sent(tmp_path):
    with make(tmp_path) as c:
        h, _ = company(c)
        outage(c)
        c.app.state.auto_cycle()
        assert [n["status"] for n in c.get("/portal/notifications", headers=h).json()] == ["disabled"]


def test_natural_recovery_counts_in_mttr_and_emails_resolution(tmp_path):
    box, fake = Outbox(), FakeZabbix()
    with make(tmp_path, box, fake) as c:
        company(c)
        outage(c)
        fake.problems = {"CAM-1": [{"eventid": "1", "name": "down", "severity": "4"}]}
        c.app.state.auto_cycle()
        assert c.get("/grafana/analytics/recovery").json() == []
        fake.problems = {}
        c.app.state.auto_cycle()
        rows = c.get("/grafana/analytics/recovery").json()
        assert len(rows) == 1 and rows[0]["recovered_by"] == "itself"
        assert "Ticket resolved" in box.sent[-1]["Subject"]


def test_scheduled_backup_runs_once_per_interval(tmp_path):
    with make(tmp_path, backup_hours=24) as c:
        company(c)
        c.app.state.auto_cycle()
        c.app.state.auto_cycle()
        assert len(list((tmp_path / "backups").glob("n-*.sqlite"))) == 1
