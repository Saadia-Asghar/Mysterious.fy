"""Live monitoring wiring, tested against a fake Zabbix API (no Docker needed)."""
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.zabbix_api import ZabbixApiClient
from tests._creds import pw

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeZabbix:
    """Enough of the Zabbix JSON-RPC API for provisioning and problem checks."""

    def __init__(self, template=True):
        self.groups: dict[str, str] = {}
        self.hosts: dict[str, dict] = {}
        self.problems: dict[str, list] = {}
        self.template = template

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        m, p = body["method"], body["params"]
        if m == "hostgroup.get":
            name = p["filter"]["name"][0]
            result = [{"groupid": self.groups[name]}] if name in self.groups else []
        elif m == "hostgroup.create":
            self.groups[p["name"]] = str(len(self.groups) + 1)
            result = {"groupids": [self.groups[p["name"]]]}
        elif m == "template.get":
            result = [{"templateid": "900"}] if self.template else []
        elif m == "host.get":
            h = self.hosts.get(p["filter"]["host"][0])
            result = [{"hostid": h["hostid"], "interfaces": [{"interfaceid": "1", "type": "1", "main": "1"}]}] if h else []
        elif m == "host.create":
            self.hosts[p["host"]] = {**p, "hostid": str(100 + len(self.hosts))}
            result = {"hostids": [self.hosts[p["host"]]["hostid"]]}
        elif m == "host.update":
            h = next(h for h in self.hosts.values() if h["hostid"] == p["hostid"])
            h.update(p)
            result = {"hostids": [p["hostid"]]}
        elif m == "hostinterface.update":
            next(iter(self.hosts.values()))["interfaces"] = [p]
            result = {"interfaceids": ["1"]}
        elif m == "problem.get":
            host = next(k for k, v in self.hosts.items() if v["hostid"] == p["hostids"][0])
            result = self.problems.get(host, [])
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "error": {"message": f"unexpected {m}"}, "id": 1})
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": 1})


def app_with(tmp_path, fake):
    s = Settings(database_path=tmp_path / "n.sqlite", profiles_dir=REPO_ROOT / "device-profiles", portal_secret="s")
    client = ZabbixApiClient("http://zbx/api_jsonrpc.php", "tok", transport=httpx.MockTransport(fake))
    return TestClient(create_app(s, zabbix_api=client))


def owner(c):
    t = c.post("/portal/setup", json={"organization": {"organization_id": "ACME", "name": "Acme"},
                                      "email": "o@acme.test", "full_name": "O", "password": pw("owner")}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    c.post("/portal/sites", headers=h, json={"site_id": "HQ", "name": "HQ"})
    return h


def add(c, h, dev, prof, addr, parent=None):
    return c.post("/portal/devices", headers=h, json={
        "device_id": dev, "name": dev, "profile_id": prof, "site_id": "HQ", "management_address": addr,
        **({"parent_device_id": parent} if parent else {})}).json()


def event(eid, dev, ts):
    return {"event_id": eid, "device_id": dev, "event_type": "device_unreachable", "severity": "high",
            "started_at": f"2026-01-01T{ts}Z", "source": "zabbix"}


def test_portal_device_becomes_zabbix_host(tmp_path):
    fake = FakeZabbix()
    with app_with(tmp_path, fake) as c:
        h = owner(c)
        assert add(c, h, "CAM-1", "ip_camera_basic", "10.0.0.5")["monitoring"] == "monitored"
        host = fake.hosts["CAM-1"]
        assert host["interfaces"][0]["ip"] == "10.0.0.5" and host["interfaces"][0]["useip"] == 1
        assert set(fake.groups) == {"NMS/ACME", "NMS/ACME/HQ"}
        assert {"tag": "nms_device_type", "value": "ip_camera"} in host["tags"]
        # DNS names work too; disabling pauses the host in Zabbix
        d = c.patch("/portal/devices/CAM-1", headers=h, json={"management_address": "cam1.local", "enabled": False}).json()
        assert d["monitoring"] == "paused" and fake.hosts["CAM-1"]["status"] == 1
        assert fake.hosts["CAM-1"]["interfaces"][0]["dns"] == "cam1.local"
        # placeholder addresses are not sent to Zabbix
        assert add(c, h, "CAM-2", "ip_camera_basic", "<authorized-address>")["monitoring"] == "skipped"
        assert "CAM-2" not in fake.hosts
        assert "monitoring.synced" in {a["action"] for a in c.get("/portal/audit", headers=h).json()}


def test_zabbix_error_does_not_block_saving_and_can_retry(tmp_path):
    fake = FakeZabbix(template=False)
    with app_with(tmp_path, fake) as c:
        h = owner(c)
        d = add(c, h, "SW-1", "network_switch_basic", "10.0.0.1")
        assert d["monitoring"] == "error" and "zabbix_bootstrap" in d["monitoring_error"]
        fake.template = True
        assert c.post("/portal/devices/SW-1/monitoring-sync", headers=h).json()["monitoring"] == "monitored"


def test_recovery_sweep_resolves_only_when_zabbix_sees_all_devices_healthy(tmp_path):
    fake = FakeZabbix()
    with app_with(tmp_path, fake) as c:
        h = owner(c)
        add(c, h, "SW-1", "network_switch_basic", "sw1.lan")
        add(c, h, "CAM-1", "ip_camera_basic", "cam1.lan", parent="SW-1")
        # a device that Zabbix does not know (e.g. old demo data) must never be auto-resolved
        c.post("/devices", json={"device_id": "GHOST", "name": "g", "device_type": "ip_camera",
                                 "profile_id": "ip_camera_basic", "organization_id": "ACME", "site_id": "HQ",
                                 "zone_id": "z", "management_address": "<a>", "responsible_team": "t"})
        for e in (event("E1", "SW-1", "00:00:01"), event("E2", "CAM-1", "00:00:02"), event("E9", "GHOST", "05:00:00")):
            c.post("/events", json=e)
        c.post("/incidents/sync")
        fake.problems = {"SW-1": [{"eventid": "1", "name": "down", "severity": "4"}]}
        assert c.post("/monitoring/recovery-sweep").json() == {"resolved": [], "still_open": ["INC-E1"]}
        fake.problems = {}
        assert c.post("/monitoring/recovery-sweep").json()["resolved"] == ["INC-E1"]
        statuses = {i["incident_id"]: i["status"] for i in c.get("/incidents").json()}
        assert statuses == {"INC-E1": "resolved", "INC-E9": "open"}


def test_ticket_title_follows_widened_incident(tmp_path):
    with app_with(tmp_path, FakeZabbix()) as c:
        h = owner(c)
        add(c, h, "SW-1", "network_switch_basic", "<a>")
        add(c, h, "CAM-1", "ip_camera_basic", "<a>", parent="SW-1")
        c.post("/events", json=event("E2", "CAM-1", "00:00:05"))
        c.post("/incidents/sync")
        t = c.get("/portal/tickets", headers=h).json()[0]
        assert "1 device(s)" in t["title"]
        c.post("/events", json=event("E1", "SW-1", "00:00:02"))
        c.post("/incidents/sync")
        t = c.get(f"/portal/tickets/{t['ticket_id']}", headers=h).json()
        assert "2 device(s) affected, probable cause SW-1" in t["title"] and t["device_id"] == "SW-1"
        assert t["history"][-1]["kind"] == "details"
        assert len(c.get("/portal/tickets?view=all", headers=h).json()) == 1


def test_settings_read_dotenv_and_ignore_placeholders(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("NMS_ZABBIX_API_URL=http://z/api_jsonrpc.php\nNMS_ZABBIX_API_TOKEN=abc\n"
                   "NMS_OSTICKET_API_KEY=change_me\nNMS_AUTO_SYNC_SECONDS=20\n# comment\n", encoding="utf-8")
    for k in ("NMS_ZABBIX_API_URL", "NMS_ZABBIX_API_TOKEN", "NMS_OSTICKET_API_KEY", "NMS_AUTO_SYNC_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(env)
    assert (s.zabbix_api_url, s.zabbix_api_token, s.osticket_api_key, s.auto_sync_seconds) == \
        ("http://z/api_jsonrpc.php", "abc", None, 20)
    monkeypatch.setenv("NMS_ZABBIX_API_TOKEN", "from-env")  # real environment wins over .env
    assert Settings.from_env(env).zabbix_api_token == "from-env"
