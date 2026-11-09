"""M13: Grafana feeds and the provisioned NMS Operations dashboard.
Grafana itself needs Docker; these tests check what can be checked without it."""
import importlib.util
import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from test_incidents_api import event, seed
from test_integration_api import REPO_ROOT
from test_verification import env, remediated  # noqa: F401  (env is a pytest fixture)

DASH = REPO_ROOT / "visualization-grafana" / "dashboards" / "nms-operations.json"
PROV = REPO_ROOT / "visualization-grafana" / "provisioning"


def load_builder():
    spec = importlib.util.spec_from_file_location("builder", REPO_ROOT / "scripts" / "build_grafana_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- feeds ---------------------------------------------------------------

def test_feeds_follow_one_incident_through_the_lifecycle(env):  # noqa: F811
    client, state, _, _ = env
    inc, ex = remediated(client, state)
    client.post(f"/executions/{ex}/verify")

    summary = client.get("/grafana/summary").json()
    assert len(summary) == 1
    s = summary[0]
    assert s["incidents_total"] == 1 and s["resolved"] == 1 and s["open"] == 0
    assert s["remediations_completed"] == 1 and s["verified_healthy"] == 1

    rows = client.get("/grafana/incidents").json()
    assert rows[0]["incident_id"] == inc
    assert rows[0]["top_cause"] == "SVC-001"
    assert rows[0]["remediation_status"] == "completed" and rows[0]["verified_healthy"] is True
    assert client.get("/grafana/incidents?status=open").json() == []

    execs = client.get("/grafana/executions").json()
    assert execs[0]["execution_id"] == ex and execs[0]["healthy"] is True
    assert "no open problems" in execs[0]["last_verification"]


def test_alert_reduction(env):  # noqa: F811
    client, _, _, _ = env
    seed(client)
    for e in [event("E1", "SWITCH-A", 0), event("E2", "CAM-001", 4), event("E3", "CAM-002", 5),
              event("E4", "CAM-004", 6)]:
        client.post("/events", json=e)
    client.post("/incidents/sync")
    s = client.get("/grafana/summary").json()[0]
    assert s["raw_events"] == 4 and s["incidents_total"] == 2
    assert s["alert_reduction_percent"] == 50.0


def test_empty_summary(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "n.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    with TestClient(create_app(settings)) as client:
        s = client.get("/grafana/summary").json()[0]
        assert s["incidents_total"] == 0 and s["alert_reduction_percent"] == 0.0


# ---- dashboard -----------------------------------------------------------

def test_committed_dashboard_matches_builder():
    assert json.loads(DASH.read_text(encoding="utf-8")) == load_builder().build(), \
        "run: python scripts/build_grafana_dashboard.py"


def provisioned_uids() -> set[str]:
    uids = set()
    for f in (PROV / "datasources").glob("*.yml"):
        for ds in yaml.safe_load(f.read_text(encoding="utf-8"))["datasources"]:
            uids.add(ds["uid"])
    return uids


def all_targets(dash: dict):
    for p in dash["panels"]:
        for t in p.get("targets", []):
            yield p, t


def test_every_panel_uses_a_provisioned_datasource():
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    uids = provisioned_uids()
    assert uids == {"zabbix", "nms-api"}
    for p, t in all_targets(dash):
        assert t["datasource"]["uid"] in uids, p["title"]
    for v in dash["templating"]["list"]:
        assert v["datasource"]["uid"] in uids


def test_every_nms_url_is_a_real_api_route(tmp_path: Path):
    settings = Settings(database_path=tmp_path / "n.sqlite", profiles_dir=REPO_ROOT / "device-profiles")
    routes = {r.path for r in create_app(settings).routes}
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    urls = [t["url"] for _, t in all_targets(dash) if t["datasource"]["uid"] == "nms-api"]
    assert urls
    for url in urls:
        assert url.split("?")[0] in routes, url


def test_layout_has_unique_ids_and_no_overlaps():
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))
    cells = set()
    for p in dash["panels"]:
        g = p["gridPos"]
        assert g["x"] + g["w"] <= 24, p["title"]
        for x in range(g["x"], g["x"] + g["w"]):
            for y in range(g["y"], g["y"] + g["h"]):
                assert (x, y) not in cells, f"overlap at {p['title']}"
                cells.add((x, y))


def test_dashboard_is_device_generic():
    text = DASH.read_text(encoding="utf-8").lower()
    assert "cam-" not in text and "camera" not in text
    names = {v["name"] for v in json.loads(text)["templating"]["list"]}
    assert names == {"group", "host"}


def test_grafana_service_installs_both_plugins():
    compose = yaml.safe_load((REPO_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    plugins = compose["services"]["grafana"]["environment"]["GF_INSTALL_PLUGINS"]
    assert "alexanderzobnin-zabbix-app" in plugins and "yesoreyeram-infinity-datasource" in plugins
