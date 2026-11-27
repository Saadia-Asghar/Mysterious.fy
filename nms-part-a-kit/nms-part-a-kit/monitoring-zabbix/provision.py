"""Provision Zabbix for the NMS and onboard devices (Part A: monitoring and generic onboarding).

Commands
  setup    Once per Zabbix: a template group, one template per file in templates/ (items and triggers),
           the "NMS Integration" webhook media type, a media entry for the Zabbix Admin user, and the
           trigger action that sends every trigger carrying an `nms_event_type` tag to the integration API.
  onboard  For every device in the inventory file: register it in the integration API, create the Zabbix
           host (host name == device_id) linked to its profile's template, and register its topology edges.

Both commands only create what is missing, so running them again is safe. Settings come from the
environment or the repository's .env file (see .env.example). Run from the repository root:

  python monitoring-zabbix/provision.py setup
  python monitoring-zabbix/provision.py onboard
"""
import argparse
import ipaddress
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "integration-api"))

from app.zabbix_api import ZabbixApiClient, ZabbixApiError  # noqa: E402

TEMPLATES_DIR = HERE / "templates"
WEBHOOK_SCRIPT = HERE / "media-types" / "nms_webhook.js"
DEFAULT_INVENTORY = HERE / "inventory.json"
DEFAULT_ZABBIX_API_URL = "http://localhost:8080/api_jsonrpc.php"
# Zabbix runs in Docker; the integration API runs on the host. host.docker.internal is the host.
DEFAULT_WEBHOOK_URL = "http://host.docker.internal:8000/integrations/zabbix/events"
DEFAULT_NMS_URL = "http://127.0.0.1:8000"

TEMPLATE_GROUP = "NMS Templates"
MEDIA_TYPE = "NMS Integration"
ACTION = "NMS: send events to the integration API"
MEDIA_USER = "Admin"

# Readable names in templates/*.json -> numeric codes in the Zabbix API.
ITEM_TYPES = {"simple_check": 3, "http_agent": 19}
VALUE_TYPES = {"float": 0, "unsigned": 3}
SEVERITIES = {"not_classified": 0, "information": 1, "warning": 2, "average": 3, "high": 4, "disaster": 5}
REQUIRED_DEVICE_FIELDS = (
    "device_id", "name", "profile_id", "organization_id", "site_id", "zone_id",
    "management_address", "responsible_team",
)
DEVICE_FIELDS = REQUIRED_DEVICE_FIELDS + ("automation_policy",)  # automation_policy defaults to the profile's
HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")


class ProvisionError(RuntimeError):
    """A problem the person running the script can fix (bad input, missing prerequisite)."""


def template_name(profile_id: str) -> str:
    """Zabbix technical template name. No spaces, so trigger expressions need no quoting."""
    return f"NMS_{profile_id}"


def load_templates(directory: Path = TEMPLATES_DIR) -> dict[str, dict]:
    """Template definitions by profile_id."""
    specs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]
    return {spec["profile_id"]: spec for spec in specs}


# ---------------------------------------------------------------- setup


def ensure_group(zbx: ZabbixApiClient, kind: str, name: str) -> str:
    """Id of the template group or host group `name` (kind: templategroup | hostgroup), created if missing."""
    found = zbx.call(f"{kind}.get", {"filter": {"name": [name]}, "output": ["groupid"]})
    if found:
        return found[0]["groupid"]
    return zbx.call(f"{kind}.create", {"name": name})["groupids"][0]


def item_payload(template_id: str, item: dict) -> dict:
    payload = {k: v for k, v in item.items() if k not in ("key", "type", "value_type", "nms_metric")}
    payload.update(
        hostid=template_id,
        key_=item["key"],
        type=ITEM_TYPES[item["type"]],
        value_type=VALUE_TYPES[item["value_type"]],
    )
    if "nms_metric" in item:
        payload["tags"] = [{"tag": "nms_metric", "value": item["nms_metric"]}]
    return payload


def trigger_payload(profile_id: str, trigger: dict, trigger_ids: dict[str, str]) -> dict:
    payload = {
        "description": trigger["name"],
        "expression": trigger["expression"].replace("{TEMPLATE}", template_name(profile_id)),
        "priority": SEVERITIES[trigger["severity"]],
        "tags": [{"tag": "nms_event_type", "value": trigger["nms_event_type"]}],
    }
    if "depends_on" in trigger:
        payload["dependencies"] = [{"triggerid": trigger_ids[trigger["depends_on"]]}]
    return payload


def ensure_template(zbx: ZabbixApiClient, spec: dict, group_id: str, log: Callable[[str], None]) -> None:
    profile_id, name = spec["profile_id"], template_name(spec["profile_id"])
    found = zbx.call("template.get", {"filter": {"host": [name]}, "output": ["templateid"]})
    if found:
        template_id = found[0]["templateid"]
    else:
        template_id = zbx.call("template.create", {
            "host": name,
            "name": f"NMS {profile_id}",
            "description": spec["description"],
            "groups": [{"groupid": group_id}],
            "macros": spec.get("macros", []),
        })["templateids"][0]
        log(f"template {name}: created")
    have_items = {i["key_"] for i in zbx.call("item.get", {"templateids": [template_id], "output": ["key_"]})}
    for item in spec["items"]:
        if item["key"] not in have_items:
            zbx.call("item.create", item_payload(template_id, item))
            log(f"  item {item['key']}: created")
    trigger_ids = {
        t["description"]: t["triggerid"]
        for t in zbx.call("trigger.get", {"templateids": [template_id], "output": ["description"]})
    }
    by_type: dict[str, str] = {}
    for trigger in spec["triggers"]:
        if trigger["name"] not in trigger_ids:
            payload = trigger_payload(profile_id, trigger, by_type)
            trigger_ids[trigger["name"]] = zbx.call("trigger.create", payload)["triggerids"][0]
            log(f"  trigger {trigger['nms_event_type']}: created")
        by_type[trigger["nms_event_type"]] = trigger_ids[trigger["name"]]


def webhook_parameters(webhook_url: str, webhook_token: str) -> list[dict]:
    values = {
        "url": webhook_url,
        "token": webhook_token,
        "eventid": "{EVENT.ID}",
        "host": "{HOST.HOST}",
        "nms_event_type": "{EVENT.TAGS.nms_event_type}",
        "severity": "{EVENT.NSEVERITY}",
        "value": "{EVENT.VALUE}",
    }
    return [{"name": k, "value": v} for k, v in values.items()]


def ensure_media_type(zbx: ZabbixApiClient, webhook_url: str, webhook_token: str, log: Callable[[str], None]) -> str:
    """Create the webhook media type, or refresh its script and parameters (so URL changes apply)."""
    definition = {
        "script": WEBHOOK_SCRIPT.read_text(encoding="utf-8"),
        "parameters": webhook_parameters(webhook_url, webhook_token),
    }
    found = zbx.call("mediatype.get", {"filter": {"name": [MEDIA_TYPE]}, "output": ["mediatypeid"]})
    if found:
        media_type_id = found[0]["mediatypeid"]
        zbx.call("mediatype.update", {"mediatypeid": media_type_id, **definition})
        log(f"media type {MEDIA_TYPE}: updated")
        return media_type_id
    templates = [
        {"eventsource": 0, "recovery": 0, "subject": "NMS problem: {EVENT.NAME}", "message": "{EVENT.NAME}"},
        {"eventsource": 0, "recovery": 1, "subject": "NMS recovery: {EVENT.NAME}", "message": "{EVENT.NAME}"},
    ]
    created = zbx.call("mediatype.create", {
        "name": MEDIA_TYPE, "type": 4, "timeout": "30s", "message_templates": templates, **definition,
    })
    log(f"media type {MEDIA_TYPE}: created")
    return created["mediatypeids"][0]


def ensure_user_media(zbx: ZabbixApiClient, media_type_id: str, log: Callable[[str], None]) -> str:
    """Zabbix only runs a media type for a user who has that media. Returns the user's id."""
    users = zbx.call("user.get", {
        "filter": {"username": [MEDIA_USER]},
        "output": ["userid"],
        "selectMedias": ["mediatypeid", "sendto", "active", "severity", "period"],
    })
    if not users:
        raise ProvisionError(f"Zabbix user {MEDIA_USER} not found")
    user = users[0]
    if not any(m["mediatypeid"] == media_type_id for m in user["medias"]):
        medias = user["medias"] + [{
            "mediatypeid": media_type_id, "sendto": "nms", "active": 0, "severity": 63,
            "period": "1-7,00:00-24:00",
        }]
        zbx.call("user.update", {"userid": user["userid"], "medias": medias})
        log(f"user {MEDIA_USER}: media {MEDIA_TYPE} added")
    return user["userid"]


def ensure_action(zbx: ZabbixApiClient, media_type_id: str, user_id: str, log: Callable[[str], None]) -> None:
    if zbx.call("action.get", {"filter": {"name": [ACTION]}, "output": ["actionid"]}):
        return
    send = {
        "operationtype": 0,
        "opmessage": {"mediatypeid": media_type_id, "default_msg": 1},
        "opmessage_usr": [{"userid": user_id}],
    }
    zbx.call("action.create", {
        "name": ACTION,
        "eventsource": 0,
        "esc_period": "1h",
        # conditiontype 25 = event tag name, operator 0 = equals
        "filter": {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "nms_event_type"}]},
        "operations": [send],
        "recovery_operations": [send],
    })
    log(f"action '{ACTION}': created")


def setup(zbx: ZabbixApiClient, webhook_url: str, webhook_token: str, log: Callable[[str], None]) -> None:
    group_id = ensure_group(zbx, "templategroup", TEMPLATE_GROUP)
    for spec in load_templates().values():
        ensure_template(zbx, spec, group_id, log)
    media_type_id = ensure_media_type(zbx, webhook_url, webhook_token, log)
    user_id = ensure_user_media(zbx, media_type_id, log)
    ensure_action(zbx, media_type_id, user_id, log)


# ---------------------------------------------------------------- onboard


def zabbix_interface(address: str) -> dict:
    """Zabbix agent-type interface for a management address (an IP, a host name, or an http(s) URL).
    ICMP and HTTP checks only need the address; the port is not used by them."""
    host = urlparse(address).hostname if "://" in address else address
    try:
        ipaddress.ip_address(host or "")
        is_ip = True
    except ValueError:
        is_ip = False
    if not host or not (is_ip or HOSTNAME.match(host)):
        raise ProvisionError(f"'{address}' is not a usable address; replace the placeholder in the inventory")
    return {"type": 1, "main": 1, "useip": int(is_ip), "ip": host if is_ip else "", "dns": "" if is_ip else host, "port": "10050"}


def load_inventory(path: Path) -> dict:
    if not path.is_file():
        raise ProvisionError(f"Inventory {path} not found. Copy inventory.example.json to inventory.json and edit it.")
    inventory = json.loads(path.read_text(encoding="utf-8"))
    for device in inventory.get("devices", []):
        missing = [f for f in REQUIRED_DEVICE_FIELDS if f not in device]
        if missing:
            raise ProvisionError(f"Device {device.get('device_id', '?')}: missing {', '.join(missing)}")
    return inventory


def register_device(nms: httpx.Client, device: dict, log: Callable[[str], None]) -> None:
    profile = nms.get(f"/profiles/{device['profile_id']}")
    if profile.status_code == 404:
        raise ProvisionError(f"{device['device_id']}: unknown profile_id {device['profile_id']}")
    profile.raise_for_status()
    body = {k: device[k] for k in DEVICE_FIELDS if k in device}
    body["device_type"] = profile.json()["device_type"]
    response = nms.post("/devices", json=body)
    if response.status_code == 409:
        log(f"{device['device_id']}: already registered in the integration API")
    elif response.status_code == 201:
        log(f"{device['device_id']}: registered in the integration API")
    else:
        raise ProvisionError(f"{device['device_id']}: integration API returned {response.status_code} {response.text}")


def create_host(zbx: ZabbixApiClient, device: dict, templates: dict[str, dict], log: Callable[[str], None]) -> None:
    device_id, profile_id = device["device_id"], device["profile_id"]
    if zbx.call("host.get", {"filter": {"host": [device_id]}, "output": ["hostid"]}):
        log(f"{device_id}: Zabbix host already exists")
        return
    spec = templates.get(profile_id)
    if spec is None:
        raise ProvisionError(f"{device_id}: no Zabbix template for profile {profile_id} (add templates/{profile_id}.json)")
    found = zbx.call("template.get", {"filter": {"host": [template_name(profile_id)]}, "output": ["templateid"]})
    if not found:
        raise ProvisionError(f"{device_id}: template {template_name(profile_id)} is missing in Zabbix; run 'setup' first")
    address = device.get("monitoring_address") or device["management_address"]
    macros = [{"macro": spec["address_macro"], "value": address}] if "address_macro" in spec else []
    group_id = ensure_group(zbx, "hostgroup", f"NMS/{device['organization_id']}/{device['site_id']}")
    zbx.call("host.create", {
        "host": device_id,
        "name": device["name"],
        "interfaces": [zabbix_interface(address)],
        "groups": [{"groupid": group_id}],
        "templates": [{"templateid": found[0]["templateid"]}],
        "macros": macros,
        "tags": [
            {"tag": "nms_organization", "value": device["organization_id"]},
            {"tag": "nms_site", "value": device["site_id"]},
            {"tag": "nms_zone", "value": device["zone_id"]},
            {"tag": "nms_profile", "value": profile_id},
        ],
    })
    log(f"{device_id}: Zabbix host created")


def register_edge(nms: httpx.Client, edge: dict, log: Callable[[str], None]) -> None:
    body = {"from_device_id": edge["from"], "to_device_id": edge["to"]}
    response = nms.post("/topology/edges", json=body)
    if response.status_code not in (201, 409):
        raise ProvisionError(f"edge {edge['from']} -> {edge['to']}: {response.status_code} {response.text}")
    log(f"edge {edge['from']} depends_on {edge['to']}: {'registered' if response.status_code == 201 else 'already registered'}")


def onboard(zbx: ZabbixApiClient, nms: httpx.Client, inventory: dict, log: Callable[[str], None]) -> None:
    templates = load_templates()
    for device in inventory.get("devices", []):
        register_device(nms, device, log)
        create_host(zbx, device, templates, log)
    for edge in inventory.get("topology", []):
        register_edge(nms, edge, log)


# ---------------------------------------------------------------- command line


def zabbix_client() -> ZabbixApiClient:
    token = os.environ.get("NMS_ZABBIX_API_TOKEN", "")
    if not token or token.startswith("change"):
        raise ProvisionError("Set NMS_ZABBIX_API_TOKEN in .env (Zabbix: Users > API tokens)")
    return ZabbixApiClient(url=os.environ.get("NMS_ZABBIX_API_URL", DEFAULT_ZABBIX_API_URL), token=token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision Zabbix for the NMS and onboard devices")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="create templates, media type and action in Zabbix")
    onboard_cmd = commands.add_parser("onboard", help="register devices and create their Zabbix hosts")
    onboard_cmd.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    onboard_cmd.add_argument("--nms-url", default=DEFAULT_NMS_URL, help="integration API address as seen from this machine")
    args = parser.parse_args(argv)

    load_dotenv(REPO_ROOT / ".env")
    try:
        zbx = zabbix_client()
        if args.command == "setup":
            webhook_url = os.environ.get("NMS_ZABBIX_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)
            setup(zbx, webhook_url, os.environ.get("NMS_ZABBIX_WEBHOOK_TOKEN", ""), print)
        else:
            with httpx.Client(base_url=args.nms_url, timeout=10) as nms:
                onboard(zbx, nms, load_inventory(args.inventory), print)
    except (ProvisionError, ZabbixApiError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
