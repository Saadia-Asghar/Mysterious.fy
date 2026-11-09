"""Zabbix API client used for post-remediation verification (M12).

Verification asks Zabbix, not the device or the playbook: a device is healthy when Zabbix
reports no open (unresolved) problems for its host. Host name == NMS device_id.
Zabbix 6.4+/7.0: authenticate with an API token as `Authorization: Bearer <token>`.
"""
from dataclasses import dataclass

import httpx


class ZabbixApiError(RuntimeError):
    pass


@dataclass
class ZabbixApiClient:
    url: str  # e.g. http://localhost:8080/api_jsonrpc.php
    token: str
    transport: httpx.BaseTransport | None = None
    timeout: float = 10.0

    def _call(self, method: str, params: dict) -> object:
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                r = client.post(
                    self.url,
                    json=body,
                    headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json-rpc"},
                )
        except httpx.HTTPError as exc:
            raise ZabbixApiError(f"Zabbix API unreachable: {exc}") from exc
        if r.status_code != 200:
            raise ZabbixApiError(f"Zabbix API returned HTTP {r.status_code}")
        data = r.json()
        if "error" in data:
            err = data["error"]
            raise ZabbixApiError(f"Zabbix API error: {err.get('message')} {err.get('data', '')}".strip())
        return data["result"]

    def open_problems(self, host: str) -> list[dict]:
        hosts = self._call("host.get", {"filter": {"host": [host]}, "output": ["hostid"]})
        if not hosts:
            raise ZabbixApiError(f"Host {host} is not monitored by Zabbix")
        return self._call(
            "problem.get",
            {"hostids": [hosts[0]["hostid"]], "output": ["eventid", "name", "severity"], "recent": False},
        )
