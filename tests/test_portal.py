from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.portal import check_password, hash_password, make_token, read_token
from app.settings import Settings
from tests._creds import pw

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER = {"organization": {"organization_id": "ACME", "name": "Acme"}, "email": "owner@acme.test",
         "full_name": "Owner", "password": pw("owner1")}


@pytest.fixture
def client(tmp_path):
    s = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles",
                 portal_secret="test-secret")
    with TestClient(create_app(s)) as c:
        yield c


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def setup_owner(client):
    r = client.post("/portal/setup", json=OWNER)
    assert r.status_code == 201
    return r.json()["token"]


def login(client, email, password):
    r = client.post("/portal/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_password_and_token_helpers():
    h = hash_password(pw("hash"))
    assert check_password(pw("hash"), h) and not check_password("wrong", h)
    t = make_token(7, b"k")
    assert read_token(t, b"k") == 7
    assert read_token(t, b"other") is None
    assert read_token("garbage", b"k") is None
    assert read_token(make_token(7, b"k", now=0), b"k") is None  # expired


def test_setup_only_once_and_login(client):
    assert client.get("/portal/setup").json() == {"needed": True}
    token = setup_owner(client)
    assert client.get("/portal/setup").json() == {"needed": False}
    assert client.post("/portal/setup", json=OWNER).status_code == 409
    assert client.get("/portal/me", headers=auth(token)).json()["role"] == "super_admin"
    assert client.post("/portal/login", json={"email": "owner@acme.test", "password": pw("nope")}).status_code == 401
    assert client.get("/portal/me").status_code == 401


def test_sites_devices_and_overview(client):
    h = auth(setup_owner(client))
    assert client.post("/portal/sites", headers=h, json={"site_id": "LHR", "name": "Lahore"}).status_code == 201
    bad = {"device_id": "SW-1", "name": "Switch", "profile_id": "network_switch_basic", "site_id": "NOPE",
           "management_address": "<authorized-address>"}
    assert client.post("/portal/devices", headers=h, json=bad).status_code == 422  # unknown site
    r = client.post("/portal/devices", headers=h, json={**bad, "site_id": "LHR"})
    assert r.status_code == 201 and r.json()["organization_id"] == "ACME" and r.json()["status"] == "ok"
    cam = {"device_id": "CAM-1", "name": "Gate", "profile_id": "ip_camera_basic", "site_id": "LHR",
           "management_address": "<authorized-address>", "parent_device_id": "SW-1"}
    r = client.post("/portal/devices", headers=h, json=cam)
    assert r.json()["parent_device_id"] == "SW-1" and r.json()["device_type"] == "ip_camera"
    edges = client.get("/topology/edges").json()
    assert {"from_device_id": "CAM-1", "to_device_id": "SW-1", "relationship": "depends_on"} in edges

    r = client.patch("/portal/devices/CAM-1", headers=h, json={"name": "Main gate", "enabled": False})
    assert r.json()["name"] == "Main gate" and r.json()["status"] == "disabled"
    assert [d["device_id"] for d in client.get("/portal/devices?device_type=ip_camera", headers=h).json()] == ["CAM-1"]

    o = client.get("/portal/overview", headers=h).json()
    assert (o["devices"], o["devices_ok"], o["devices_disabled"], o["sites"]) == (2, 1, 1, 1)
    assert client.delete("/portal/sites/LHR", headers=h).status_code == 409  # still has devices


def test_problem_status_from_open_incident(client):
    h = auth(setup_owner(client))
    client.post("/portal/sites", headers=h, json={"site_id": "S1", "name": "Site 1"})
    client.post("/portal/devices", headers=h, json={"device_id": "CAM-9", "name": "c", "profile_id": "ip_camera_basic",
                                                    "site_id": "S1", "management_address": "<authorized-address>"})
    client.post("/events", json={"event_id": "E1", "device_id": "CAM-9", "event_type": "device_unreachable",
                                 "severity": "high", "started_at": "2026-01-01T00:00:00Z", "source": "test"})
    client.post("/incidents/sync")
    d = client.get("/portal/devices/CAM-9", headers=h).json()
    assert d["status"] == "problem" and d["open_incidents"] == 1
    assert client.get("/portal/overview", headers=h).json()["open_incidents"] == 1


def test_roles_and_tenant_isolation(client):
    h = auth(setup_owner(client))
    assert client.post("/portal/organizations", headers=h,
                       json={"organization_id": "BETA", "name": "Beta"}).status_code == 201
    client.post("/portal/sites?organization_id=BETA", headers=h, json={"site_id": "B1", "name": "Beta site"})
    client.post("/portal/devices?organization_id=BETA", headers=h,
                json={"device_id": "B-CAM", "name": "b", "profile_id": "ip_camera_basic", "site_id": "B1",
                      "management_address": "<authorized-address>"})
    assert client.post("/portal/users", headers=h, json={"email": "v@acme.test", "full_name": "V",
                                                          "password": pw("viewer"), "role": "viewer"}).status_code == 201
    v = auth(login(client, "v@acme.test", pw("viewer")))
    assert client.post("/portal/sites", headers=v, json={"site_id": "X", "name": "x"}).status_code == 403
    assert client.get("/portal/devices", headers=v).json() == []
    assert client.get("/portal/devices?organization_id=BETA", headers=v).status_code == 403
    assert client.get("/portal/devices/B-CAM", headers=v).status_code == 404
    assert [d["device_id"] for d in client.get("/portal/devices?organization_id=BETA", headers=h).json()] == ["B-CAM"]

    client.post("/portal/users", headers=h, json={"email": "a@acme.test", "full_name": "A",
                                                   "password": pw("admin"), "role": "admin"})
    a = auth(login(client, "a@acme.test", pw("admin")))
    assert client.post("/portal/users", headers=a, json={"email": "x@acme.test", "full_name": "X",
                                                          "password": pw("xxxxxxxx"), "role": "super_admin"}).status_code == 403
    assert client.post("/portal/organizations", headers=a, json={"organization_id": "C", "name": "C"}).status_code == 403


def test_portal_page_served(client):
    r = client.get("/app")
    assert r.status_code == 200 and "NMS Portal" in r.text
