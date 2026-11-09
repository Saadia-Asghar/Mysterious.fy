"""Build the unified NMS operations dashboard (M13) as Grafana JSON.

    python scripts/build_grafana_dashboard.py

Writes visualization-grafana/dashboards/nms-operations.json, which Grafana loads through
provisioning. Edit this script, not the JSON.

Two data sources, both provisioned in visualization-grafana/provisioning/datasources/:
- `zabbix`  (Zabbix plugin): live device metrics. Device-generic: driven by $group / $host.
- `nms-api` (Infinity plugin): incidents, RCA, tickets, remediation and verification from the
  integration API's flat /grafana/* feeds. Grafana only displays; it computes nothing.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "visualization-grafana" / "dashboards" / "nms-operations.json"
ZBX = {"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix"}
NMS = {"type": "yesoreyeram-infinity-datasource", "uid": "nms-api"}

_next_id = 0


def pid() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def nms_query(path: str, columns: list[tuple[str, str, str]] | None = None) -> dict:
    return {
        "refId": "A",
        "datasource": NMS,
        "type": "json",
        "source": "url",
        "format": "table",
        "url": path,
        "url_options": {"method": "GET", "data": ""},
        "root_selector": "",
        "columns": [{"selector": s, "text": t, "type": ty} for s, t, ty in (columns or [])],
    }


def zbx_query(item_regex: str) -> dict:
    return {
        "refId": "A",
        "datasource": ZBX,
        "queryType": "0",
        "group": {"filter": "$group"},
        "host": {"filter": "$host"},
        "application": {"filter": ""},
        "itemTag": {"filter": ""},
        "item": {"filter": item_regex},
        "functions": [],
        "options": {"showDisabledItems": False},
    }


def row(title: str, y: int) -> dict:
    return {"type": "row", "id": pid(), "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(title: str, field: str, x: int, y: int, color: str, unit: str = "none", desc: str = "") -> dict:
    return {
        "type": "stat", "id": pid(), "title": title, "description": desc,
        "datasource": NMS,
        "gridPos": {"x": x, "y": y, "w": 4, "h": 4},
        "targets": [nms_query("/grafana/summary", [(field, title, "number")])],
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "none", "textMode": "value"},
    }


def table(title: str, path: str, columns, x: int, y: int, w: int, h: int, desc: str, overrides=()) -> dict:
    return {
        "type": "table", "id": pid(), "title": title, "description": desc,
        "datasource": NMS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [nms_query(path, columns)],
        "fieldConfig": {"defaults": {"custom": {"filterable": True}}, "overrides": list(overrides)},
        "options": {"showHeader": True, "cellHeight": "sm"},
    }


def color_by_value(field: str, mapping: dict[str, str]) -> dict:
    return {
        "matcher": {"id": "byName", "options": field},
        "properties": [
            {"id": "custom.cellOptions", "value": {"type": "color-background"}},
            {"id": "mappings", "value": [{"type": "value", "options": {
                k: {"color": c, "index": i} for i, (k, c) in enumerate(mapping.items())}}]},
        ],
    }


def timeseries(title: str, item_regex: str, x: int, y: int, unit: str, desc: str) -> dict:
    return {
        "type": "timeseries", "id": pid(), "title": title, "description": desc,
        "datasource": ZBX,
        "gridPos": {"x": x, "y": y, "w": 8, "h": 8},
        "targets": [zbx_query(item_regex)],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    }


STATUS_COLORS = {"open": "red", "action_pending": "orange", "verifying": "yellow",
                 "resolved": "green", "escalated": "purple"}
EXEC_COLORS = {"pending": "orange", "running": "yellow", "completed": "blue",
               "failed": "red", "rejected_by_policy": "text"}
BOOL_COLORS = {"true": "green", "false": "red"}


def build() -> dict:
    panels = []
    y = 0
    panels.append(row("Operations overview (NMS intelligence)", y)); y += 1
    for i, (title, field, color, unit, desc) in enumerate([
        ("Open incidents", "open", "red", "none", "Correlated incidents not yet acted on"),
        ("Awaiting approval", "action_pending", "orange", "none", "Remediation waiting for a person (require_approval)"),
        ("Verifying", "verifying", "yellow", "none", "Action done; waiting for Zabbix to confirm health"),
        ("Escalated", "escalated", "purple", "none", "Needs humans: action failed, rejected or recovery not verified"),
        ("Resolved", "resolved", "green", "none", "Recovery confirmed by Zabbix"),
        ("Alert reduction", "alert_reduction_percent", "blue", "percent", "1 - incidents / raw events"),
    ]):
        panels.append(stat(title, field, i * 4, y, color, unit, desc))
    y += 4

    panels.append(table(
        "Incidents: correlation, probable root cause, ticket, remediation, verification",
        "/grafana/incidents",
        [("incident_id", "Incident", "string"), ("created_at", "Started", "timestamp"),
         ("severity", "Severity", "string"), ("status", "Status", "string"),
         ("affected_devices", "Affected devices", "string"), ("event_count", "Events", "number"),
         ("top_cause", "Probable cause", "string"), ("top_cause_score", "Cause rank score", "number"),
         ("top_cause_reason", "Why", "string"), ("ticket_id", "osTicket #", "string"),
         ("remediation_status", "Remediation", "string"), ("verified_healthy", "Zabbix healthy", "string")],
        0, y, 24, 9,
        "One row per correlated incident. Rank scores are heuristic ranks (topology_time_v1), not probabilities.",
        [color_by_value("Status", STATUS_COLORS), color_by_value("Remediation", EXEC_COLORS),
         color_by_value("Zabbix healthy", BOOL_COLORS)],
    ))
    y += 9

    panels.append(table(
        "Controlled self-healing and verification",
        "/grafana/executions",
        [("execution_id", "Execution", "string"), ("incident_id", "Incident", "string"),
         ("device_id", "Device", "string"), ("playbook_id", "Playbook", "string"),
         ("policy", "Policy", "string"), ("status", "Action", "string"), ("reason", "Policy decision", "string"),
         ("approved_by", "Approved by", "string"), ("finished_at", "Finished", "timestamp"),
         ("healthy", "Zabbix healthy", "string"), ("last_verification", "Last verification", "string")],
        0, y, 16, 8,
        "An action finishing is not recovery. Only the Zabbix verification column decides health.",
        [color_by_value("Action", EXEC_COLORS), color_by_value("Zabbix healthy", BOOL_COLORS)],
    ))
    panels.append(table(
        "Telemetry anomalies (robust_zscore_v1)",
        "/intelligence/anomalies?only_anomalies=true",
        [("timestamp", "Time", "timestamp"), ("device_id", "Device", "string"),
         ("metric_name", "Metric", "string"), ("value", "Value", "number"),
         ("baseline_median", "Baseline", "number"), ("direction", "Direction", "string"),
         ("anomaly_score", "Score", "number")],
        16, y, 8, 8,
        "Readings with |robust z| >= 3.5 against the previous 30 readings. Score 0.5 = threshold.",
    ))
    y += 8

    panels.append(row("Device health (Zabbix) - pick a group and devices above", y)); y += 1
    panels.append(timeseries("Availability", "/ICMP ping/", 0, y, "none",
                             "1 = reachable, 0 = down (Zabbix ICMP ping)"))
    panels.append(timeseries("Latency", "/ICMP response time/", 8, y, "s",
                             "Round-trip time from Zabbix ICMP checks"))
    panels.append(timeseries("Packet loss", "/ICMP loss/", 16, y, "percent",
                             "ICMP packet loss reported by Zabbix"))

    return {
        "uid": "nms-operations",
        "title": "NMS Operations",
        "description": "Generic intelligent NMS: monitoring, incidents, RCA, tickets, remediation, verification.",
        "tags": ["nms", "fyp"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": [
            {"name": "group", "label": "Device group", "type": "query", "datasource": ZBX,
             "query": {"queryType": "group", "group": "/.*/", "host": "", "application": "", "itemTag": "", "item": ""},
             "refresh": 1, "includeAll": False, "multi": False, "current": {}},
            {"name": "host", "label": "Device", "type": "query", "datasource": ZBX,
             "query": {"queryType": "host", "group": "$group", "host": "/.*/", "application": "", "itemTag": "", "item": ""},
             "refresh": 2, "includeAll": True, "multi": True, "allValue": "/.*/", "current": {}},
        ]},
        "panels": panels,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}")
