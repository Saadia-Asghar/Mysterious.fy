"""Keep Zabbix in step with the portal: every portal device becomes a Zabbix host.

Host name = NMS device_id (the convention the webhook and verification rely on).
Groups: "NMS/<company>" and "NMS/<company>/<site>", so Zabbix and Grafana can filter per customer.
Template: "NMS ICMP device" (created by scripts/zabbix_bootstrap.py): ping, loss and latency
items with triggers tagged nms_event_type = device_unreachable / high_packet_loss / high_latency.
Interface: IP when management_address is an IP, otherwise DNS name.

A Zabbix failure never blocks saving the device: the link is stored as "error" with the
message and can be retried from the portal.
"""
import ipaddress
from datetime import datetime, timezone

from app.zabbix_api import ZabbixApiClient, ZabbixApiError

TEMPLATE = "NMS ICMP device"


def _is_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False


class ZabbixProvisioner:
    def __init__(self, client: ZabbixApiClient, store) -> None:
        self.client = client
        self.store = store
        self._template_id: str | None = None

    def init(self) -> None:
        with self.store._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS zabbix_links (
                       device_id TEXT PRIMARY KEY,
                       hostid TEXT,
                       status TEXT NOT NULL,
                       error TEXT,
                       synced_at TEXT NOT NULL
                   )""")

    # ---- link bookkeeping ----
    def _save(self, device_id: str, hostid: str | None, status: str, error: str | None = None) -> None:
        with self.store._connect() as conn:
            conn.execute("INSERT INTO zabbix_links VALUES (?, ?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET"
                         " hostid=excluded.hostid, status=excluded.status, error=excluded.error,"
                         " synced_at=excluded.synced_at",
                         (device_id, hostid, status, error,
                          datetime.now(timezone.utc).replace(microsecond=0).isoformat()))

    def links(self) -> dict[str, dict]:
        with self.store._connect() as conn:
            return {r["device_id"]: dict(r) for r in conn.execute("SELECT * FROM zabbix_links")}

    # ---- Zabbix objects ----
    def _group(self, name: str) -> str:
        found = self.client.call("hostgroup.get", {"filter": {"name": [name]}, "output": ["groupid"]})
        if found:
            return found[0]["groupid"]
        return self.client.call("hostgroup.create", {"name": name})["groupids"][0]

    def _template(self) -> str:
        if self._template_id is None:
            found = self.client.call("template.get", {"filter": {"host": [TEMPLATE]}, "output": ["templateid"]})
            if not found:
                raise ZabbixApiError(f'Template "{TEMPLATE}" missing; run scripts/zabbix_bootstrap.py')
            self._template_id = found[0]["templateid"]
        return self._template_id

    def sync(self, device, company: str, site: str) -> str:
        """Create or update the Zabbix host for this device. Returns the link status."""
        try:
            addr = device.management_address.strip()
            if not addr or addr.startswith("<"):
                self._save(device.device_id, None, "skipped", "placeholder address; nothing to monitor")
                return "skipped"
            groups = [{"groupid": self._group(f"NMS/{company}")}, {"groupid": self._group(f"NMS/{company}/{site}")}]
            ip = _is_ip(addr)
            iface = {"type": 1, "main": 1, "useip": 1 if ip else 0, "ip": addr if ip else "",
                     "dns": "" if ip else addr, "port": "10050"}
            tags = [{"tag": "nms_company", "value": company}, {"tag": "nms_site", "value": site},
                    {"tag": "nms_device_type", "value": device.device_type}]
            fields = {"name": f"{device.device_id} {device.name}"[:128], "groups": groups,
                      "templates": [{"templateid": self._template()}], "tags": tags,
                      "status": 0 if device.enabled else 1}
            found = self.client.call("host.get", {"filter": {"host": [device.device_id]}, "output": ["hostid"],
                                                  "selectInterfaces": ["interfaceid", "type", "main"]})
            if found:
                hostid = found[0]["hostid"]
                self.client.call("host.update", {"hostid": hostid, **fields})
                main = next((i for i in found[0]["interfaces"] if i["type"] == "1" and i["main"] == "1"), None)
                if main:
                    self.client.call("hostinterface.update", {"interfaceid": main["interfaceid"], **iface})
                else:
                    self.client.call("hostinterface.create", {"hostid": hostid, **iface})
            else:
                hostid = self.client.call("host.create", {"host": device.device_id, "interfaces": [iface],
                                                          **fields})["hostids"][0]
            status = "monitored" if device.enabled else "paused"
            self._save(device.device_id, hostid, status)
            return status
        except ZabbixApiError as exc:
            self._save(device.device_id, None, "error", str(exc)[:500])
            return "error"
