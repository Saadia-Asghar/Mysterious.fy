"""Part A: Zabbix provisioning (templates, media type, action) and device onboarding.

A fake Zabbix API keeps these tests offline. It enforces the required fields and the trigger-expression
rule that provision.py depends on, but only a live Zabbix can confirm that the real API accepts every call
(see docs/part-a/STEP_BY_STEP_GUIDE.md, step "Run setup")."""
import itertools
import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import provision
from app.main import create_app
from app.settings import Settings
from app.zabbix_api import ZabbixApiClient
from test_integration_api import REPO_ROOT

TOKEN = "zbx-test-token"
TRIGGER_REFERENCE = re.compile(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?=[,)])")


class FakeZabbix:
    """In-memory stand-in for the Zabbix JSON-RPC API (only the methods provision.py uses)."""

    def __init__(self) -> None:
        self.ids = itertools.count(100)
        self.rows: dict[str, list[dict]] = {
            k: [] for k in ("templategroup", "hostgroup", "template", "item", "trigger", "mediatype", "action", "host")
        }
        self.users = [{"userid": "1", "username": "Admin", "medias": []}]
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> ZabbixApiClient:
        return ZabbixApiClient("http://zabbix.test/api_jsonrpc.php", TOKEN, transport=self.transport())

    def creates(self) -> list[str]:
        return [c for c in self.calls if c.endswith(".create")]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        body = json.loads(request.content)
        self.calls.append(body["method"])
        handler = getattr(self, "m_" + body["method"].replace(".", "_"), None)
        if handler is None:
            return httpx.Response(200, json={"jsonrpc": "2.0", "error": {"message": "Method not found"}, "id": 1})
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": handler(body["params"]), "id": 1})

    def _add(self, table: str, row: dict, id_key: str) -> dict:
        row = {**row, id_key: str(next(self.ids))}
        self.rows[table].append(row)
        return row

    def _find(self, table: str, field: str, value: str) -> list[dict]:
        return [r for r in self.rows[table] if r.get(field) == value]

    @staticmethod
    def _require(params: dict, *fields: str) -> None:
        missing = [f for f in fields if f not in params]
        assert not missing, f"Zabbix would reject this call: missing {missing}"

    def _create_group(self, table: str, params: dict) -> dict:
        self._require(params, "name")
        return {"groupids": [self._add(table, params, "groupid")["groupid"]]}

    def _get_by(self, table: str, params: dict, field: str) -> list[dict]:
        wanted = params["filter"][field]
        return [r for r in self.rows[table] if r[field] in wanted]

    def m_templategroup_get(self, params):
        return self._get_by("templategroup", params, "name")

    def m_templategroup_create(self, params):
        return self._create_group("templategroup", params)

    def m_hostgroup_get(self, params):
        return self._get_by("hostgroup", params, "name")

    def m_hostgroup_create(self, params):
        return self._create_group("hostgroup", params)

    def m_template_get(self, params):
        return self._get_by("template", params, "host")

    def m_template_create(self, params):
        self._require(params, "host", "groups")
        return {"templateids": [self._add("template", params, "templateid")["templateid"]]}

    def m_item_get(self, params):
        return [r for r in self.rows["item"] if r["hostid"] in params["templateids"]]

    def m_item_create(self, params):
        self._require(params, "hostid", "name", "key_", "type", "value_type", "delay")
        assert params["type"] in (3, 19) and params["value_type"] in (0, 3)
        assert any(t["templateid"] == params["hostid"] for t in self.rows["template"])
        if params["type"] == 19:
            self._require(params, "url")
        return {"itemids": [self._add("item", params, "itemid")["itemid"]]}

    def m_trigger_get(self, params):
        return [r for r in self.rows["trigger"] if r["templateid"] in params["templateids"]]

    def m_trigger_create(self, params):
        self._require(params, "description", "expression", "priority", "tags")
        references = TRIGGER_REFERENCE.findall(params["expression"])
        assert references, f"no item reference in {params['expression']}"
        template_names = {r[0] for r in references}
        assert len(template_names) == 1
        template = self._find("template", "host", template_names.pop())[0]
        keys = {i["key_"] for i in self.rows["item"] if i["hostid"] == template["templateid"]}
        for _, key in references:
            assert key in keys, f"Zabbix would reject this trigger: item {key} does not exist"
        for dep in params.get("dependencies", []):
            assert self._find("trigger", "triggerid", dep["triggerid"])
        row = self._add("trigger", {**params, "templateid": template["templateid"]}, "triggerid")
        return {"triggerids": [row["triggerid"]]}

    def m_mediatype_get(self, params):
        return self._get_by("mediatype", params, "name")

    def m_mediatype_create(self, params):
        self._require(params, "name", "type", "script", "parameters")
        assert params["type"] == 4
        return {"mediatypeids": [self._add("mediatype", params, "mediatypeid")["mediatypeid"]]}

    def m_mediatype_update(self, params):
        row = self._find("mediatype", "mediatypeid", params["mediatypeid"])[0]
        row.update(params)
        return {"mediatypeids": [row["mediatypeid"]]}

    def m_user_get(self, params):
        return [u for u in self.users if u["username"] in params["filter"]["username"]]

    def m_user_update(self, params):
        next(u for u in self.users if u["userid"] == params["userid"])["medias"] = params["medias"]
        return {"userids": [params["userid"]]}

    def m_action_get(self, params):
        return self._get_by("action", params, "name")

    def m_action_create(self, params):
        self._require(params, "name", "eventsource", "esc_period", "filter", "operations", "recovery_operations")
        return {"actionids": [self._add("action", params, "actionid")["actionid"]]}

    def m_host_get(self, params):
        return self._get_by("host", params, "host")

    def m_host_create(self, params):
        self._require(params, "host", "groups", "interfaces", "templates")
        for template in params["templates"]:
            assert self._find("template", "templateid", template["templateid"])
        return {"hostids": [self._add("host", params, "hostid")["hostid"]]}


@pytest.fixture
def zabbix() -> FakeZabbix:
    return FakeZabbix()


def run_setup(zabbix: FakeZabbix, token: str = "") -> list[str]:
    log: list[str] = []
    provision.setup(zabbix.client(), "http://nms.test/integrations/zabbix/events", token, log.append)
    return log


# ---------------------------------------------------------------- template files


def profile_files() -> dict[str, dict]:
    paths = sorted((REPO_ROOT / "device-profiles").glob("*.json"))
    return {d["profile_id"]: d for d in (json.loads(p.read_text(encoding="utf-8")) for p in paths)}


def test_every_profile_has_a_zabbix_template():
    assert set(provision.load_templates()) == set(profile_files())


@pytest.mark.parametrize("profile_id", sorted(profile_files()))
def test_template_only_uses_what_its_profile_declares(profile_id):
    profile, spec = profile_files()[profile_id], provision.load_templates()[profile_id]
    event_types = [t["nms_event_type"] for t in spec["triggers"]]
    assert set(event_types) <= set(profile["triggers"])
    assert len(event_types) == len(set(event_types))
    metrics = {i["nms_metric"] for i in spec["items"] if "nms_metric" in i}
    assert metrics <= {m["metric_name"] for m in profile["metrics"]}
    keys = [i["key"] for i in spec["items"]]
    assert len(keys) == len(set(keys))
    for trigger in spec["triggers"]:
        assert trigger["severity"] in provision.SEVERITIES
        assert {key for _, key in TRIGGER_REFERENCE.findall(trigger["expression"])} <= set(keys)
        if "depends_on" in trigger:
            assert trigger["depends_on"] in event_types[: event_types.index(trigger["nms_event_type"])]


@pytest.mark.parametrize("profile_id", ["ip_camera_basic", "network_switch_basic"])
def test_icmp_templates_cover_the_whole_profile(profile_id):
    profile, spec = profile_files()[profile_id], provision.load_templates()[profile_id]
    assert {t["nms_event_type"] for t in spec["triggers"]} == set(profile["triggers"])
    assert {i["nms_metric"] for i in spec["items"]} == {m["metric_name"] for m in profile["metrics"]}
    # Names Saadia's dashboard queries (scripts/build_grafana_dashboard.py in the full repository)
    assert {i["name"] for i in spec["items"]} == {"ICMP ping", "ICMP response time", "ICMP loss"}


def test_webhook_script_and_parameters_agree():
    names = {p["name"] for p in provision.webhook_parameters("u", "t")}
    script = provision.WEBHOOK_SCRIPT.read_text(encoding="utf-8")
    assert set(re.findall(r"\bp\.([a-z_]+)", script)) == names


def test_nothing_uses_a_macro_missing_from_zabbix_7_0():
    # {EVENT.TIMESTAMP} arrived in Zabbix 7.2; the compose file pins 7.0 LTS.
    script = provision.WEBHOOK_SCRIPT.read_text(encoding="utf-8")
    values = " ".join(p["value"] for p in provision.webhook_parameters("u", "t"))
    assert "EVENT.TIMESTAMP" not in values
    assert "{EVENT.TIMESTAMP}" not in script


# ---------------------------------------------------------------- setup


def test_setup_creates_templates_media_type_user_media_and_action(zabbix):
    run_setup(zabbix, token="secret-token")
    assert [g["name"] for g in zabbix.rows["templategroup"]] == [provision.TEMPLATE_GROUP]
    for profile_id, spec in provision.load_templates().items():
        template = zabbix.rows["template"][[t["host"] for t in zabbix.rows["template"]].index(f"NMS_{profile_id}")]
        items = [i for i in zabbix.rows["item"] if i["hostid"] == template["templateid"]]
        triggers = [t for t in zabbix.rows["trigger"] if t["templateid"] == template["templateid"]]
        assert [i["key_"] for i in items] == [i["key"] for i in spec["items"]]
        assert len(triggers) == len(spec["triggers"])
        assert all(t["tags"][0]["tag"] == "nms_event_type" for t in triggers)

    camera = next(t for t in zabbix.rows["template"] if t["host"] == "NMS_ip_camera_basic")
    by_name = {t["description"]: t for t in zabbix.rows["trigger"] if t["templateid"] == camera["templateid"]}
    unreachable = next(t for n, t in by_name.items() if "unreachable" in n)
    degraded = [t for n, t in by_name.items() if "unreachable" not in n]
    assert len(degraded) == 2 and all(d["dependencies"] == [{"triggerid": unreachable["triggerid"]}] for d in degraded)
    assert "dependencies" not in unreachable

    [media_type] = zabbix.rows["mediatype"]
    params = {p["name"]: p["value"] for p in media_type["parameters"]}
    assert params["url"] == "http://nms.test/integrations/zabbix/events" and params["token"] == "secret-token"
    assert params["host"] == "{HOST.HOST}" and params["nms_event_type"] == "{EVENT.TAGS.nms_event_type}"
    assert media_type["script"] == provision.WEBHOOK_SCRIPT.read_text(encoding="utf-8")

    assert [m["mediatypeid"] for m in zabbix.users[0]["medias"]] == [media_type["mediatypeid"]]
    [action] = zabbix.rows["action"]
    assert action["filter"]["conditions"] == [{"conditiontype": 25, "operator": 0, "value": "nms_event_type"}]
    assert action["operations"] == action["recovery_operations"]
    assert action["operations"][0]["opmessage"]["mediatypeid"] == media_type["mediatypeid"]
    assert action["operations"][0]["opmessage_usr"] == [{"userid": "1"}]


def test_setup_twice_creates_nothing_new_and_refreshes_the_media_type(zabbix):
    run_setup(zabbix)
    first = len(zabbix.creates())
    zabbix.calls.clear()
    log = run_setup(zabbix, token="rotated")
    assert zabbix.creates() == [] and first > 0
    assert "mediatype.update" in zabbix.calls and "user.update" not in zabbix.calls
    assert log == [f"media type {provision.MEDIA_TYPE}: updated"]
    assert {p["name"]: p["value"] for p in zabbix.rows["mediatype"][0]["parameters"]}["token"] == "rotated"


def test_setup_completes_a_half_created_template(zabbix):
    group_id = provision.ensure_group(zabbix.client(), "templategroup", provision.TEMPLATE_GROUP)
    spec = provision.load_templates()["ip_camera_basic"]
    zabbix.client().call("template.create", {"host": "NMS_ip_camera_basic", "groups": [{"groupid": group_id}]})
    run_setup(zabbix)
    camera = next(t for t in zabbix.rows["template"] if t["host"] == "NMS_ip_camera_basic")
    assert len([i for i in zabbix.rows["item"] if i["hostid"] == camera["templateid"]]) == len(spec["items"])
    assert len([t for t in zabbix.rows["trigger"] if t["templateid"] == camera["templateid"]]) == len(spec["triggers"])
    assert [t["host"] for t in zabbix.rows["template"]].count("NMS_ip_camera_basic") == 1


def test_setup_needs_the_admin_user(zabbix):
    zabbix.users.clear()
    with pytest.raises(provision.ProvisionError, match="Admin"):
        run_setup(zabbix)


# ---------------------------------------------------------------- onboarding


@pytest.fixture
def nms(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "nms.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings)) as client:
        yield client


def inventory() -> dict:
    return json.loads((REPO_ROOT / "monitoring-zabbix" / "inventory.example.json").read_text(encoding="utf-8"))


def camera_inventory() -> dict:
    text = (REPO_ROOT / "monitoring-zabbix" / "inventory.camera.example.json").read_text(encoding="utf-8")
    return json.loads(text.replace("<authorized-address>", "192.0.2.10", 1).replace("<authorized-address>", "192.0.2.11"))


def test_onboard_test_service_registers_device_and_creates_host(zabbix, nms):
    run_setup(zabbix)
    log: list[str] = []
    provision.onboard(zabbix.client(), nms, inventory(), log.append)

    device = nms.get("/devices/SVC-001").json()
    assert device["device_type"] == "test_service" and device["automation_policy"] == "require_approval"
    assert device["management_address"] == "http://127.0.0.1:9100"

    [host] = zabbix.rows["host"]
    assert host["host"] == "SVC-001" and host["name"] == "Lab test service"
    assert host["interfaces"][0]["dns"] == "host.docker.internal" and host["interfaces"][0]["useip"] == 0
    # Zabbix reaches the service through the Docker host, not through the API's 127.0.0.1
    assert host["macros"] == [{"macro": "{$NMS.BASE_URL}", "value": "http://host.docker.internal:9100"}]
    assert [g["name"] for g in zabbix.rows["hostgroup"]] == ["NMS/LAB/LAB-SITE"]
    assert {t["tag"]: t["value"] for t in host["tags"]} == {
        "nms_organization": "LAB", "nms_site": "LAB-SITE", "nms_zone": "BENCH", "nms_profile": "test_service_basic",
    }
    template = next(t for t in zabbix.rows["template"] if t["host"] == "NMS_test_service_basic")
    assert host["templates"] == [{"templateid": template["templateid"]}]
    assert log == ["SVC-001: registered in the integration API", "SVC-001: Zabbix host created"]


def test_onboard_cameras_with_topology(zabbix, nms):
    run_setup(zabbix)
    provision.onboard(zabbix.client(), nms, camera_inventory(), lambda _: None)
    assert {h["host"] for h in zabbix.rows["host"]} == {"SWITCH-A", "CAM-001"}
    camera = next(h for h in zabbix.rows["host"] if h["host"] == "CAM-001")
    assert camera["interfaces"][0] == {"type": 1, "main": 1, "useip": 1, "ip": "192.0.2.11", "dns": "", "port": "10050"}
    assert camera["macros"] == []
    assert nms.get("/devices/CAM-001").json()["automation_policy"] == "monitor_only"
    assert nms.get("/devices/SWITCH-A").json()["automation_policy"] == "monitor_only"  # the profile default
    assert nms.get("/topology/edges").json() == [
        {"from_device_id": "CAM-001", "to_device_id": "SWITCH-A", "relationship": "depends_on"}
    ]


def test_onboard_twice_changes_nothing(zabbix, nms):
    run_setup(zabbix)
    provision.onboard(zabbix.client(), nms, camera_inventory(), lambda _: None)
    zabbix.calls.clear()
    log: list[str] = []
    provision.onboard(zabbix.client(), nms, camera_inventory(), log.append)
    assert "host.create" not in zabbix.calls
    assert len(nms.get("/devices").json()) == 2 and len(nms.get("/topology/edges").json()) == 1
    assert "CAM-001: already registered in the integration API" in log
    assert "edge CAM-001 depends_on SWITCH-A: already registered" in log


def test_onboard_before_setup_says_what_to_do(zabbix, nms):
    with pytest.raises(provision.ProvisionError, match="run 'setup' first"):
        provision.onboard(zabbix.client(), nms, inventory(), lambda _: None)


def test_onboard_rejects_placeholder_address_and_unknown_profile(zabbix, nms):
    run_setup(zabbix)
    placeholder = json.loads((REPO_ROOT / "monitoring-zabbix" / "inventory.camera.example.json").read_text("utf-8"))
    with pytest.raises(provision.ProvisionError, match="replace the placeholder"):
        provision.onboard(zabbix.client(), nms, placeholder, lambda _: None)
    unknown = inventory()
    unknown["devices"][0]["profile_id"] = "no_such_profile"
    with pytest.raises(provision.ProvisionError, match="unknown profile_id"):
        provision.onboard(zabbix.client(), nms, unknown, lambda _: None)


@pytest.mark.parametrize(
    ("address", "ip", "dns", "useip"),
    [
        ("192.0.2.5", "192.0.2.5", "", 1),
        ("camera1.lab.example", "", "camera1.lab.example", 0),
        ("http://192.0.2.5:8080/x", "192.0.2.5", "", 1),
        ("http://host.docker.internal:9100", "", "host.docker.internal", 0),
    ],
)
def test_zabbix_interface(address, ip, dns, useip):
    interface = provision.zabbix_interface(address)
    assert (interface["ip"], interface["dns"], interface["useip"]) == (ip, dns, useip)


@pytest.mark.parametrize("address", ["<authorized-address>", "", "http://", "bad address"])
def test_zabbix_interface_rejects_unusable_addresses(address):
    with pytest.raises(provision.ProvisionError):
        provision.zabbix_interface(address)


def test_inventory_problems_are_reported(tmp_path: Path):
    with pytest.raises(provision.ProvisionError, match="not found"):
        provision.load_inventory(tmp_path / "nope.json")
    incomplete = tmp_path / "inv.json"
    incomplete.write_text(json.dumps({"devices": [{"device_id": "X-1"}]}), encoding="utf-8")
    with pytest.raises(provision.ProvisionError, match="X-1: missing name, profile_id"):
        provision.load_inventory(incomplete)


def test_command_line_reports_errors_instead_of_tracebacks(monkeypatch, capsys):
    monkeypatch.setattr(provision, "load_dotenv", lambda *_: None)
    monkeypatch.delenv("NMS_ZABBIX_API_TOKEN", raising=False)
    assert provision.main(["setup"]) == 1
    assert "NMS_ZABBIX_API_TOKEN" in capsys.readouterr().err
    monkeypatch.setenv("NMS_ZABBIX_API_TOKEN", "change_me")
    assert provision.main(["setup"]) == 1
