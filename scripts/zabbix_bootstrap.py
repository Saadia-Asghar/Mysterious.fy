"""One-time Zabbix setup for the NMS. Safe to run again (it updates what exists).

    python scripts/zabbix_bootstrap.py                     # Zabbix at http://localhost:8080, user Admin
    python scripts/zabbix_bootstrap.py --url http://localhost:8080 --user Admin
    (password: --password, or env ZABBIX_ADMIN_PASSWORD, default "zabbix" for a fresh local install)

Creates in Zabbix:
1. template group "Templates/NMS" and template "NMS ICMP device":
   ping / loss / latency simple checks every 30 s, and triggers tagged nms_event_type:
   device_unreachable (3 failed pings in a row), high_packet_loss (>20% for 5 min),
   high_latency (>200 ms average for 5 min)
2. webhook media type "NMS Integration" (monitoring-zabbix/media-types/nms_webhook.js) pointing at
   the NMS API, plus the global macro {$NMS.WEBHOOK.TOKEN}
3. the media on the Admin user and the action "NMS: forward to integration" (problem + recovery)
4. an API token "nms-integration" for the NMS API

Writes NMS_ZABBIX_API_URL, NMS_ZABBIX_API_TOKEN, ZABBIX_API_TOKEN and NMS_ZABBIX_WEBHOOK_TOKEN into
the local .env (git-ignored). Restart the NMS API afterwards. See docs/live-monitoring.md.
"""
import argparse
import os
import re
import secrets
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "NMS ICMP device"
MEDIA = "NMS Integration"
ACTION = "NMS: forward to integration"
TOKEN_NAME = "nms-integration"


class Zabbix:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/") + "/api_jsonrpc.php"
        self.auth: str | None = None

    def call(self, method: str, params) -> object:
        headers = {"Content-Type": "application/json-rpc"}
        if self.auth:
            headers["Authorization"] = f"Bearer {self.auth}"
        r = httpx.post(self.url, json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                       headers=headers, timeout=30)
        data = r.json()
        if "error" in data:
            raise SystemExit(f"{method} failed: {data['error'].get('message')} {data['error'].get('data', '')}")
        return data["result"]


def one(z: Zabbix, method: str, flt: dict, out: str):
    found = z.call(method, {"filter": flt, "output": [out]})
    return found[0][out] if found else None


def ensure_template(z: Zabbix) -> str:
    gid = one(z, "templategroup.get", {"name": ["Templates/NMS"]}, "groupid") or \
        z.call("templategroup.create", {"name": "Templates/NMS"})["groupids"][0]
    tid = one(z, "template.get", {"host": [TEMPLATE]}, "templateid") or \
        z.call("template.create", {"host": TEMPLATE, "groups": [{"groupid": gid}],
                                   "description": "NMS generic reachability: ping, loss, latency."})["templateids"][0]
    items = [("ICMP ping", "icmpping[,3]", 3, ""), ("ICMP loss", "icmppingloss[,10]", 0, "%"),
             ("ICMP response time", "icmppingsec[,10]", 0, "s")]
    have = {i["key_"] for i in z.call("item.get", {"hostids": [tid], "output": ["key_"]})}
    for name, key, vtype, units in items:
        if key not in have:
            z.call("item.create", {"hostid": tid, "name": name, "key_": key, "type": 3, "value_type": vtype,
                                   "units": units, "delay": "30s", "history": "31d", "trends": "365d"})
    t = f"/{TEMPLATE}"
    triggers = [
        # 3 failed pings in a row, OR no ping result for 2 minutes (name stops resolving, check
        # becomes unsupported): both mean the device cannot be reached.
        ("{HOST.HOST} is unreachable", f"max({t}/icmpping[,3],#3)=0 or nodata({t}/icmpping[,3],2m)=1",
         4, "device_unreachable"),
        ("{HOST.HOST} high packet loss", f"min({t}/icmppingloss[,10],5m)>20", 2, "high_packet_loss"),
        ("{HOST.HOST} high latency", f"avg({t}/icmppingsec[,10],5m)>0.2", 2, "high_latency"),
    ]
    have = {x["description"]: x["triggerid"]
            for x in z.call("trigger.get", {"hostids": [tid], "output": ["description", "triggerid"]})}
    for desc, expr, prio, tag in triggers:
        body = {"expression": expr, "priority": prio, "tags": [{"tag": "nms_event_type", "value": tag}]}
        if desc in have:
            z.call("trigger.update", {"triggerid": have[desc], **body})  # keep re-runs in step with this file
        else:
            z.call("trigger.create", {"description": desc, "manual_close": 0, **body})
    return tid


def ensure_webhook(z: Zabbix, nms_url: str, uid: str, webhook_token: str) -> str:
    script = (ROOT / "monitoring-zabbix" / "media-types" / "nms_webhook.js").read_text(encoding="utf-8")
    params = [{"name": "url", "value": nms_url.rstrip("/") + "/integrations/zabbix/events"},
              {"name": "token", "value": "{$NMS.WEBHOOK.TOKEN}"},
              {"name": "eventid", "value": "{EVENT.ID}"}, {"name": "host", "value": "{HOST.HOST}"},
              {"name": "nms_event_type", "value": "{EVENT.TAGS.nms_event_type}"},
              {"name": "severity", "value": "{EVENT.NSEVERITY}"}, {"name": "value", "value": "{EVENT.VALUE}"},
              {"name": "event_date", "value": "{EVENT.DATE}"}, {"name": "event_time", "value": "{EVENT.TIME}"}]
    templates = [{"eventsource": 0, "recovery": r, "subject": "{EVENT.NAME}", "message": "{EVENT.NAME}"} for r in (0, 1)]
    body = {"name": MEDIA, "type": 4, "script": script, "parameters": params, "message_templates": templates,
            "timeout": "10s", "status": 0}
    mid = one(z, "mediatype.get", {"name": [MEDIA]}, "mediatypeid")
    if mid:
        z.call("mediatype.update", {"mediatypeid": mid, **body})
    else:
        mid = z.call("mediatype.create", body)["mediatypeids"][0]

    macro = z.call("usermacro.get", {"globalmacro": True, "filter": {"macro": "{$NMS.WEBHOOK.TOKEN}"},
                                     "output": ["globalmacroid"]})
    if macro:
        z.call("usermacro.updateglobal", {"globalmacroid": macro[0]["globalmacroid"], "value": webhook_token, "type": 1})
    else:
        z.call("usermacro.createglobal", {"macro": "{$NMS.WEBHOOK.TOKEN}", "value": webhook_token, "type": 1})

    z.call("user.update", {"userid": uid, "medias": [{"mediatypeid": mid, "sendto": "nms", "active": 0,
                                                       "severity": 63, "period": "1-7,00:00-24:00"}]})
    op = {"operationtype": 0, "opmessage": {"default_msg": 1, "mediatypeid": mid}, "opmessage_usr": [{"userid": uid}]}
    action = {"name": ACTION, "eventsource": 0, "status": 0, "esc_period": "1h",
              "filter": {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "nms_event_type"}]},
              "operations": [op], "recovery_operations": [op]}
    aid = one(z, "action.get", {"name": [ACTION]}, "actionid")
    if aid:
        action.pop("eventsource")
        z.call("action.update", {"actionid": aid, **action})
    else:
        z.call("action.create", action)
    return mid


def token_works(url: str, token: str | None) -> bool:
    if not token or token == "change_me":
        return False
    try:
        r = httpx.post(url, json={"jsonrpc": "2.0", "method": "host.get", "params": {"limit": 1, "output": ["hostid"]},
                                  "id": 1},
                       headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json-rpc"}, timeout=10)
        return "result" in r.json()
    except (httpx.HTTPError, ValueError):
        return False


def new_api_token(z: Zabbix, uid: str) -> str:
    old = z.call("token.get", {"filter": {"name": TOKEN_NAME, "userid": uid}, "output": ["tokenid"]})
    if old:
        z.call("token.delete", [t["tokenid"] for t in old])  # values cannot be read back; issue a fresh one
    tid = z.call("token.create", {"name": TOKEN_NAME, "userid": uid,
                                  "description": "Used by the NMS integration API"})["tokenids"][0]
    return z.call("token.generate", [tid])[0]["token"]


def write_env(values: dict[str, str]) -> None:
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    for k, v in values.items():
        line = f"{k}={v}"
        text = re.sub(rf"^{k}=.*$", line, text, flags=re.M) if re.search(rf"^{k}=", text, flags=re.M) \
            else text.rstrip("\n") + f"\n{line}\n"
    env.write_text(text, encoding="utf-8")


def read_env(key: str) -> str | None:
    env = ROOT / ".env"
    if not env.exists():
        return None
    m = re.search(rf"^{key}=(.*)$", env.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1).strip() if m else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8080", help="Zabbix web address as seen from this machine")
    ap.add_argument("--user", default="Admin")
    ap.add_argument("--password", default=os.environ.get("ZABBIX_ADMIN_PASSWORD", "zabbix"))
    ap.add_argument("--nms-url", default="http://host.docker.internal:8000",
                    help="NMS API address as seen from the Zabbix server container")
    ap.add_argument("--no-env", action="store_true", help="print values instead of writing .env")
    a = ap.parse_args()

    z = Zabbix(a.url)
    z.auth = z.call("user.login", {"username": a.user, "password": a.password})
    uid = one(z, "user.get", {"username": [a.user]}, "userid")

    webhook_token = read_env("NMS_ZABBIX_WEBHOOK_TOKEN")
    if not webhook_token or webhook_token == "change_me":
        webhook_token = secrets.token_urlsafe(24)
    ensure_template(z)
    ensure_webhook(z, a.nms_url, uid, webhook_token)
    current = read_env("NMS_ZABBIX_API_TOKEN")
    token = current if token_works(z.url, current) else new_api_token(z, uid)  # keep a working token
    z.call("user.logout", [])

    values = {"NMS_ZABBIX_API_URL": a.url.rstrip("/") + "/api_jsonrpc.php", "NMS_ZABBIX_API_TOKEN": token,
              "ZABBIX_API_TOKEN": token, "NMS_ZABBIX_WEBHOOK_TOKEN": webhook_token}
    if a.no_env:
        for k in values:
            print(f"{k}=<{len(values[k])} characters>" if "TOKEN" in k else f"{k}={values[k]}")
        print("Values not written (--no-env). Re-run without it to store them in .env.")
    else:
        write_env(values)
        print("Zabbix is set up: template, webhook, action and API token. Values written to .env.")
    print("Restart the NMS API so it loads them. If you changed the Admin password, use --password.")


if __name__ == "__main__":
    sys.exit(main())
