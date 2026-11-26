import csv
import io
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests._creds import pw

REPO_ROOT = Path(__file__).resolve().parents[1]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def env(tmp_path):
    s = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles",
                 portal_secret="test-secret")
    with TestClient(create_app(s)) as c:
        staff = H(c.post("/portal/setup", json={"organization": {"organization_id": "NMS", "name": "NOC"},
                                                "email": "staff@nms.test", "full_name": "Staff",
                                                "password": pw("staff")}).json()["token"])
        c.post("/portal/admin/companies", headers=staff, json={
            "organization_id": "MALL", "name": "City Mall", "admin_name": "Ayesha",
            "admin_email": "admin@mall.test", "admin_password": pw("admin")})
        ids = {}
        for email, name, role in [("tech@mall.test", "Tariq", "technician"), ("tech2@mall.test", "Bilal", "technician"),
                                  ("ops@mall.test", "Omar", "operator"), ("view@mall.test", "Vera", "viewer")]:
            ids[role if email != "tech2@mall.test" else "tech2"] = c.post(
                "/portal/users?organization_id=MALL", headers=staff,
                json={"email": email, "full_name": name, "password": pw("1234"), "role": role}).json()["user_id"]

        def login(email, label="1234"):
            return H(c.post("/portal/login", json={"email": email, "password": pw(label)}).json()["token"])

        a = login("admin@mall.test", "admin")
        c.post("/portal/sites", headers=a, json={"site_id": "G", "name": "Ground"})
        c.post("/portal/devices", headers=a, json={"device_id": "SW-1", "name": "sw", "profile_id": "network_switch_basic",
                                                   "site_id": "G", "management_address": "<authorized-address>",
                                                   "responsible_team": "network"})
        c.post("/portal/devices", headers=a, json={"device_id": "CAM-1", "name": "gate", "profile_id": "ip_camera_basic",
                                                   "site_id": "G", "management_address": "<authorized-address>",
                                                   "responsible_team": "cctv-team", "parent_device_id": "SW-1"})
        yield {"c": c, "staff": staff, "admin": a, "tech": login("tech@mall.test"), "tech2": login("tech2@mall.test"),
               "ops": login("ops@mall.test"), "view": login("view@mall.test"), "ids": ids, "db": s.database_path}


def incident_on_camera(c):
    c.post("/events", json={"event_id": "E1", "device_id": "CAM-1", "event_type": "device_unreachable",
                            "severity": "high", "started_at": "2026-01-01T00:00:00Z", "source": "t"})
    c.post("/incidents/sync")


def test_incident_opens_ticket_routed_to_team(env):
    c, a = env["c"], env["admin"]
    team = c.post("/portal/teams", headers=a, json={"name": "CCTV-team"}).json()
    c.put(f"/portal/teams/{team['team_id']}/members", headers=a, json={"user_ids": [env["ids"]["technician"]]})
    incident_on_camera(c)
    ts = c.get("/portal/tickets", headers=a).json()
    assert len(ts) == 1
    t = ts[0]
    assert (t["source"], t["device_id"], t["team_name"], t["status"], t["priority"]) == \
        ("incident", "CAM-1", "CCTV-team", "assigned", "high")
    # SLA deadlines come from the incident start and the priority
    assert datetime.fromisoformat(t["resolve_due"]) - datetime.fromisoformat(t["created_at"]) == \
        datetime.fromisoformat("2026-01-01T08:00:00+00:00") - datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    assert t["resolve_breached"] is True  # an incident from January is far past its deadline
    # syncing again does not duplicate
    assert len(c.get("/portal/tickets?view=all", headers=a).json()) == 1
    # technician in the team sees it; one outside the team does not
    assert [x["ticket_id"] for x in c.get("/portal/tickets?view=my_teams", headers=env["tech"]).json()] == [t["ticket_id"]]
    assert c.get("/portal/tickets", headers=env["tech2"]).json() == []
    assert c.get(f"/portal/tickets/{t['ticket_id']}", headers=env["tech2"]).status_code == 404


def test_monitoring_resolution_closes_ticket(env, monkeypatch):
    c, a = env["c"], env["admin"]
    incident_on_camera(c)
    tid = c.get("/portal/tickets", headers=a).json()[0]["ticket_id"]
    # mark the incident resolved the way verification does
    con = sqlite3.connect(env["db"])
    con.execute("UPDATE incidents SET status='resolved'")
    con.commit()
    con.close()
    t = c.get(f"/portal/tickets/{tid}", headers=a).json()
    assert t["status"] == "resolved" and t["incident_status"] == "resolved"
    last = t["history"][-1]
    assert last["actor_name"] == "NMS monitoring" and last["detail"]["reason"] == "monitoring confirmed recovery"


def test_manual_ticket_assignment_history_and_roles(env):
    c, a, ops, tech, view, ids = env["c"], env["admin"], env["ops"], env["tech"], env["view"], env["ids"]
    t = c.post("/portal/tickets", headers=ops, json={"title": "Lens dirty at gate", "device_id": "CAM-1",
                                                     "priority": "low"}).json()
    assert t["status"] == "new" and t["created_by"] == "Omar"
    tid = t["ticket_id"]
    t = c.patch(f"/portal/tickets/{tid}", headers=ops, json={"assignee_id": ids["technician"]}).json()
    assert t["status"] == "assigned" and t["assignee_name"] == "Tariq" and t["first_response_at"]
    # technician works it but cannot reassign
    assert c.patch(f"/portal/tickets/{tid}", headers=tech, json={"assignee_id": ids["tech2"]}).status_code == 403
    c.post(f"/portal/tickets/{tid}/comments", headers=tech, json={"body": "Cleaned the lens"})
    t = c.patch(f"/portal/tickets/{tid}", headers=tech, json={"status": "resolved"}).json()
    assert t["status"] == "resolved" and t["resolved_at"]
    kinds = [h["kind"] for h in t["history"]]
    assert kinds == ["created", "status", "assignee", "comment", "status"]  # new->assigned is logged too
    # viewers read only; viewers cannot be assignees; unknown device rejected
    assert c.post("/portal/tickets", headers=view, json={"title": "x y z"}).status_code == 403
    assert c.patch(f"/portal/tickets/{tid}", headers=ops, json={"assignee_id": ids["viewer"]}).status_code == 422
    assert c.post("/portal/tickets", headers=ops, json={"title": "abc", "device_id": "NOPE"}).status_code == 422
    # reopen clears resolved_at
    t = c.patch(f"/portal/tickets/{tid}", headers=ops, json={"status": "in_progress"}).json()
    assert t["resolved_at"] is None
    # another company cannot reach this ticket
    assert c.get(f"/portal/tickets/{tid}?organization_id=NMS", headers=env["staff"]).status_code == 404


def test_nothing_is_ever_lost(env):
    c, a = env["c"], env["admin"]
    tid = c.post("/portal/tickets", headers=a, json={"title": "Keep me"}).json()["ticket_id"]
    con = sqlite3.connect(env["db"])
    for sql in ("DELETE FROM tickets", "DELETE FROM ticket_events", "UPDATE ticket_events SET detail='{}'",
                "DELETE FROM audit_log", "UPDATE audit_log SET actor_name='x'"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    con.close()
    # archiving a team keeps it and its tickets
    team = c.post("/portal/teams", headers=a, json={"name": "old"}).json()
    c.patch(f"/portal/tickets/{tid}", headers=a, json={"team_id": team["team_id"]})
    assert c.post(f"/portal/teams/{team['team_id']}/archive", headers=a).json()["active"] is False
    assert c.get(f"/portal/tickets/{tid}", headers=a).json()["team_name"] == "old"
    # removing a user keeps them on record (soft delete) and logs it
    c.delete(f"/portal/users/{env['ids']['viewer']}?organization_id=MALL", headers=env["staff"])
    actions = [x["action"] for x in c.get("/portal/audit", headers=a).json()]
    assert "user.deactivated" in actions and "team.archived" in actions and "ticket.created" in actions


def test_activity_log_seen_by_company_and_staff(env):
    c, a, staff = env["c"], env["admin"], env["staff"]
    c.patch("/portal/devices/CAM-1", headers=a, json={"name": "Main gate"})
    mine = c.get("/portal/audit", headers=a).json()
    assert mine[0]["action"] == "device.updated" and "name: gate -> Main gate" in mine[0]["detail"]
    assert all(x["organization_id"] == "MALL" for x in mine)
    assert {"company.created", "device.created"} <= {x["action"] for x in mine}
    assert c.get("/portal/audit", headers=env["ops"]).status_code == 403
    every = c.get("/portal/admin/audit", headers=staff).json()
    assert {x["organization_id"] for x in every} == {"MALL"}
    assert c.get("/portal/admin/audit", headers=a).status_code == 403


def test_reports_and_exports(env):
    c, a = env["c"], env["admin"]
    team = c.post("/portal/teams", headers=a, json={"name": "cctv-team"}).json()
    incident_on_camera(c)
    t = c.post("/portal/tickets", headers=a, json={"title": "Manual one", "team_id": team["team_id"]}).json()
    c.patch(f"/portal/tickets/{t['ticket_id']}", headers=a, json={"status": "resolved"})
    r = c.get("/portal/reports/tickets?days=36500", headers=a).json()
    assert (r["opened"], r["resolved"], r["from_monitoring"], r["sla_met_pct"]) == (2, 1, 1, 100)
    assert r["by_team"][0]["name"] == "cctv-team" and r["by_team"][0]["opened"] == 2
    assert r["top_devices"] == [{"device_id": "CAM-1", "tickets": 1}]

    res = c.get("/portal/export/tickets.csv", headers=a)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert {row["title"] for row in rows} >= {"Manual one"} and len(rows) == 2
    for kind in ("ticket_history", "devices", "incidents", "audit", "sites", "teams"):
        assert c.get(f"/portal/export/{kind}.csv", headers=a).status_code == 200
    assert c.get("/portal/export/tickets.csv", headers=env["ops"]).status_code == 403
    assert "data.exported" in {x["action"] for x in c.get("/portal/audit", headers=a).json()}


def test_backup_and_restore(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import backup_db
    db = tmp_path / "nms.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    out = tmp_path / "backups"
    first = backup_db.backup(db, out, keep=2)
    assert sqlite3.connect(first).execute("SELECT x FROM t").fetchall() == [(1,)]
    # change the live db, then restore: old copy comes back and the changed db is kept aside
    con = sqlite3.connect(db)
    con.execute("DELETE FROM t")
    con.commit()
    con.close()
    saved = backup_db.restore(first, db)
    assert sqlite3.connect(db).execute("SELECT x FROM t").fetchall() == [(1,)]
    assert saved.exists() and sqlite3.connect(saved).execute("SELECT count(*) FROM t").fetchone() == (0,)
