from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path):
    s = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles",
                 portal_secret="test-secret")
    with TestClient(create_app(s)) as c:
        staff = c.post("/portal/setup", json={"organization": {"organization_id": "NMS", "name": "Our NOC"},
                                              "email": "staff@nms.test", "full_name": "Staff", "password": "staff-pass"})
        S = {"Authorization": f"Bearer {staff.json()['token']}"}
        c.post("/portal/organizations", headers=S, json={"organization_id": "MALL", "name": "City Mall"})
        c.post("/portal/users?organization_id=MALL", headers=S,
               json={"email": "it@mall.test", "full_name": "Mall IT", "password": "mall-pass", "role": "admin"})
        tok = c.post("/portal/login", json={"email": "it@mall.test", "password": "mall-pass"}).json()["token"]
        yield c, S, {"Authorization": f"Bearer {tok}"}


def test_company_table_shows_health(env):
    c, S, M = env
    c.post("/portal/sites", headers=M, json={"site_id": "G", "name": "Ground"})
    for i in (1, 2):
        c.post("/portal/devices", headers=M, json={"device_id": f"MC-{i}", "name": "cam", "profile_id": "ip_camera_basic",
                                                   "site_id": "G", "management_address": "<authorized-address>"})
    c.post("/events", json={"event_id": "E1", "device_id": "MC-1", "event_type": "device_unreachable",
                            "severity": "high", "started_at": "2026-01-01T00:00:00Z", "source": "t"})
    c.post("/incidents/sync")
    rows = {r["organization_id"]: r for r in c.get("/portal/admin/companies", headers=S).json()}
    mall = rows["MALL"]
    assert (mall["users"], mall["sites"], mall["devices"], mall["devices_problem"], mall["open_incidents"]) == (1, 1, 2, 1, 1)
    assert mall["health"] == "critical" and rows["NMS"]["health"] == "no_devices"
    assert c.get("/portal/admin/companies", headers=M).status_code == 403


def test_suspend_blocks_company_users(env):
    c, S, M = env
    assert c.patch("/portal/admin/companies/MALL", headers=S, json={"active": False}).json()["active"] is False
    assert c.get("/portal/me", headers=M).status_code == 403
    assert c.post("/portal/login", json={"email": "it@mall.test", "password": "mall-pass"}).status_code == 403
    assert c.patch("/portal/admin/companies/NMS", headers=S, json={"active": False}).status_code == 409
    c.patch("/portal/admin/companies/MALL", headers=S, json={"active": True, "name": "City Mall Ltd"})
    assert c.get("/portal/me", headers=M).status_code == 200
    assert c.get("/portal/organizations", headers=M).json()[0]["name"] == "City Mall Ltd"


def test_support_conversation(env):
    c, S, M = env
    r = c.post("/portal/support", headers=M, json={"subject": "Gate camera offline", "message": "Since 9am", "priority": "high"})
    assert r.status_code == 201
    rid = r.json()["request_id"]
    assert r.json()["organization_id"] == "MALL" and r.json()["status"] == "open"

    inbox = c.get("/portal/support?status=open", headers=S).json()
    assert [x["request_id"] for x in inbox] == [rid] and inbox[0]["organization_name"] == "City Mall"

    r = c.post(f"/portal/support/{rid}/messages", headers=S, json={"message": "Please power-cycle the PoE port"})
    assert r.json()["status"] == "waiting_customer" and r.json()["messages"][-1]["from_staff"] is True
    r = c.post(f"/portal/support/{rid}/messages", headers=M, json={"message": "Done, works now"})
    assert r.json()["status"] == "open" and len(r.json()["messages"]) == 3
    assert c.patch(f"/portal/support/{rid}", headers=M, json={"status": "in_progress"}).status_code == 403
    assert c.patch(f"/portal/support/{rid}", headers=M, json={"status": "resolved"}).json()["status"] == "resolved"

    c.post("/portal/organizations", headers=S, json={"organization_id": "SCH", "name": "School"})
    c.post("/portal/users?organization_id=SCH", headers=S,
           json={"email": "a@sch.test", "full_name": "A", "password": "sch-pass1", "role": "admin"})
    tok = c.post("/portal/login", json={"email": "a@sch.test", "password": "sch-pass1"}).json()["token"]
    o = {"Authorization": f"Bearer {tok}"}
    assert c.get(f"/portal/support/{rid}", headers=o).status_code == 404
    assert c.get("/portal/support", headers=o).json() == []


def test_notices_reach_the_right_companies(env):
    c, S, M = env
    c.post("/portal/admin/notices", headers=S, json={"title": "Maintenance", "body": "Sunday 2am", "level": "warning"})
    c.post("/portal/admin/notices", headers=S, json={"title": "For mall", "body": "x", "organization_id": "MALL"})
    c.post("/portal/organizations", headers=S, json={"organization_id": "SCH", "name": "School"})
    n = c.post("/portal/admin/notices", headers=S, json={"title": "For school", "body": "y", "organization_id": "SCH"}).json()
    assert [x["title"] for x in c.get("/portal/notices", headers=M).json()] == ["For mall", "Maintenance"]
    assert c.post("/portal/admin/notices", headers=M, json={"title": "t", "body": "b"}).status_code == 403
    assert c.post("/portal/admin/notices", headers=S,
                  json={"title": "t", "body": "b", "organization_id": "NOPE"}).status_code == 404
    assert c.delete(f"/portal/admin/notices/{n['notice_id']}", headers=S).status_code == 204
    assert len(c.get("/portal/notices", headers=S).json()) == 2


def test_old_database_gets_active_column(tmp_path):
    import sqlite3
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE organizations (organization_id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    con.execute("INSERT INTO organizations VALUES ('OLD', 'Old Co')")
    con.commit()
    con.close()
    with TestClient(create_app(Settings(database_path=db, profiles_dir=REPO_ROOT / "device-profiles"))):
        pass
    con = sqlite3.connect(db)
    assert con.execute("SELECT active FROM organizations WHERE organization_id='OLD'").fetchone() == (1,)
    con.close()


def test_staff_create_company_with_login_and_only_staff_issue_logins(env):
    c, S, M = env
    r = c.post("/portal/admin/companies", headers=S, json={
        "organization_id": "SCH", "name": "City School", "admin_name": "Sana",
        "admin_email": "it@school.test", "admin_password": "school-pass"})
    assert r.status_code == 201 and r.json()["users"] == 1
    assert c.post("/portal/admin/companies", headers=S, json={
        "organization_id": "SCH2", "name": "x", "admin_name": "y",
        "admin_email": "it@school.test", "admin_password": "xxxxxxxx"}).status_code == 409  # email taken
    assert c.post("/portal/admin/companies", headers=M, json={
        "organization_id": "Z", "name": "z", "admin_name": "z",
        "admin_email": "z@z.test", "admin_password": "zzzzzzzz"}).status_code == 403

    # same sign-in endpoint for the customer as for staff
    login = c.post("/portal/login", json={"email": "it@school.test", "password": "school-pass"})
    assert login.status_code == 200 and login.json()["user"]["role"] == "admin"
    sch = {"Authorization": "Bearer " + login.json()["token"]}

    # company admins can list their users but cannot create, reset or remove logins
    assert [u["email"] for u in c.get("/portal/users", headers=sch).json()] == ["it@school.test"]
    assert c.post("/portal/users", headers=sch, json={"email": "n@school.test", "full_name": "N",
                                                      "password": "nnnnnnnn"}).status_code == 403
    uid = login.json()["user"]["user_id"]
    assert c.post(f"/portal/users/{uid}/password", headers=sch, json={"password": "hijacked1"}).status_code == 403

    # staff reset the password; the old one stops working
    assert c.post(f"/portal/users/{uid}/password?organization_id=SCH", headers=S,
                  json={"password": "new-school-pass"}).status_code == 204
    assert c.post("/portal/login", json={"email": "it@school.test", "password": "school-pass"}).status_code == 401
    assert c.post("/portal/login", json={"email": "it@school.test", "password": "new-school-pass"}).status_code == 200
    # a user id from another company is not reachable through this company's scope
    assert c.post(f"/portal/users/{uid}/password?organization_id=MALL", headers=S,
                  json={"password": "whatever1"}).status_code == 404
