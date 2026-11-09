# Data contracts

Shared records between Zabbix, the integration service, intelligence, osTicket, remediation, and Grafana. Field names below are the ones named in specification section 15, plus the device fields in section 9 and the minimum verification record required to finish the trace.

These examples show shape. Addresses are placeholders. Rank scores in the RCA example are the specification’s illustration, not a measured result.

## Trace

```text
device_id → event_id → incident_id → ticket_id or execution_id → verification result
```

Correlation groups `event_ids` on one incident. The specification does not define a separate `correlation_id`.

## Device

```json
{
  "device_id": "CAM-001",
  "name": "FCSE Entrance Camera",
  "device_type": "ip_camera",
  "profile_id": "ip_camera_basic",
  "organization_id": "GIKI",
  "site_id": "FCSE",
  "zone_id": "MAIN_ENTRANCE",
  "management_address": "<authorized-address>",
  "responsible_team": "network_team",
  "automation_policy": "monitor_only",
  "enabled": true
}
```

`GIKI`, `FCSE`, and `MAIN_ENTRANCE` are the specification’s example identifiers. This repository is public. Use them only as examples until the team confirms seed data. Do not replace `<authorized-address>` with a real address in Git.

`automation_policy` is one of `monitor_only`, `recommend`, `require_approval`, `auto_remediate`.

## Profile

A profile is reusable configuration for a device class.

```json
{
  "profile_id": "ip_camera_basic",
  "device_type": "ip_camera",
  "connectors": ["icmp"],
  "optional_connectors": ["snmp", "http"],
  "metrics": [
    {"metric_name": "availability", "unit": "bool"},
    {"metric_name": "latency_ms", "unit": "ms"},
    {"metric_name": "packet_loss_percent", "unit": "percent"}
  ],
  "triggers": ["device_unreachable", "high_latency", "high_packet_loss"],
  "dashboard": "ip_camera_basic",
  "capabilities": ["health_check"],
  "allowed_playbooks": [],
  "default_policy": "monitor_only"
}
```

## Telemetry

`device_id`, `metric_name`, `value`, `unit`, `timestamp`, `source`

```json
{
  "device_id": "CAM-001",
  "metric_name": "latency_ms",
  "value": 42,
  "unit": "ms",
  "timestamp": "2026-11-01T10:01:00+05:00",
  "source": "zabbix"
}
```

## Event

`event_id`, `device_id`, `event_type`, `severity`, `started_at`, `source`

```json
{
  "event_id": "EVT-1001",
  "device_id": "SWITCH-A",
  "event_type": "device_unreachable",
  "severity": "high",
  "started_at": "2026-11-01T10:01:01+05:00",
  "source": "zabbix"
}
```

`event_type` is a string defined by the device profile, not a camera-only enum in the core.

The specification does not name severity levels. Use Zabbix’s names when events come from Zabbix: `not_classified`, `information`, `warning`, `average`, `high`, `disaster`. Record any other scale as a reviewed change before code depends on it.

## Incident

`incident_id`, `event_ids`, `affected_devices`, `severity`, `status`, `created_at`

```json
{
  "incident_id": "INC-501",
  "event_ids": ["EVT-1001", "EVT-1002", "EVT-1003", "EVT-1004"],
  "affected_devices": ["SWITCH-A", "CAM-001", "CAM-002", "CAM-003"],
  "severity": "high",
  "status": "open",
  "created_at": "2026-11-01T10:01:05+05:00"
}
```

Suggested status values, matching the lifecycle, until the team freezes them: `open`, `action_pending`, `verifying`, `resolved`, `escalated`.

## Correlation result

Grouped by the incident. No extra identifier.

```json
{
  "incident_id": "INC-501",
  "event_ids": ["EVT-1001", "EVT-1002", "EVT-1003", "EVT-1004"],
  "method": "time_window_and_topology",
  "reason": "CAM-001, CAM-002, and CAM-003 depend_on SWITCH-A and failed within the same short window"
}
```

## Anomaly result

`device_id`, `anomaly_score`, `model_version`, `timestamp`

```json
{
  "device_id": "CAM-001",
  "anomaly_score": 0.0,
  "model_version": "unimplemented",
  "timestamp": "2026-11-01T10:01:04+05:00"
}
```

`anomaly_score` in stored experiments must come from a real model run. The zero above marks an unimplemented model, not a measured score.

## RCA result

`incident_id`, `ranked_causes[{device_id or service_id, score}]`, `method`

```json
{
  "incident_id": "INC-501",
  "ranked_causes": [
    {"device_id": "SWITCH-A", "score": 0.91},
    {"device_id": "CAM-001", "score": 0.04},
    {"device_id": "CAM-002", "score": 0.03},
    {"device_id": "CAM-003", "score": 0.02}
  ],
  "method": "specification_illustration"
}
```

The scores are copied from specification section 19 so the team can see the record shape. They are not an evaluation result. A real RCA result uses the method name of the implementation that produced it.

## Ticket mapping

`incident_id`, `provider`, `external_ticket_id`

```json
{
  "incident_id": "INC-501",
  "provider": "osticket",
  "external_ticket_id": "<ticket-id>"
}
```

## Remediation execution

`execution_id`, `incident_id`, `playbook_id`, `policy`, `status`, `timestamps`

```json
{
  "execution_id": "EXE-900",
  "incident_id": "INC-501",
  "playbook_id": "restart_test_service",
  "policy": "require_approval",
  "status": "pending",
  "timestamps": {
    "started_at": null,
    "finished_at": null
  }
}
```

Execution status describes the playbook run: `pending`, `rejected_by_policy`, `running`, `completed`, `failed`. Health is the verification record, not this status.

`restart_test_service` is the specification’s safe-demo idea. It is not an approved playbook in this repository, and no command is stored here.

## Verification result

The specification requires a monitoring check after every automated action and a trace from `execution_id` to that result. Section 15 does not list field names. The minimum record is:

```json
{
  "execution_id": "EXE-900",
  "incident_id": "INC-501",
  "source": "zabbix",
  "healthy": false,
  "observed_at": "2026-11-01T10:06:00+05:00",
  "summary": "Monitored health did not recover"
}
```

`source` stays `zabbix`. `healthy: false` escalates. `healthy: true` can resolve the incident. Several observations over time can be stored; `observed_at` orders them.

## Topology edge

```json
{
  "from_device_id": "CAM-001",
  "to_device_id": "SWITCH-A",
  "relationship": "depends_on"
}
```

## Implementation notes (dev)

- Zabbix events get `event_id` = `ZBX-<zabbix eventid>`.
- `GET /intelligence/incidents` returns Incident fields plus nested `correlation {method, reason}` and `rca {method, ranked_causes[{device_id, score, reason}]}`. Methods: correlation `upstream_anchor_quorum_v2` (default) or `time_window_and_topology_v1` via `?method=` (also on `POST /incidents/sync`; unknown values return 422), RCA `topology_time_v1`. The stored `correlation.method` records which one produced the incident. RCA scores are normalized heuristic ranks, not probabilities.
- Until incidents are persisted, `incident_id` is `INC-<first event_id>` (deterministic, recomputed on each call).

- Persisted incidents (`GET /incidents`) add `updated_at`, `ticket` (Ticket mapping + `created_at`) and `ticket_error`. Re-analysis refreshes events, devices and RCA but never changes `status`.

- `GET /intelligence/anomalies` returns the Anomaly result fields (`device_id`, `anomaly_score`, `model_version`=`robust_zscore_v1`, `timestamp`) plus `metric_name`, `value`, `baseline_median`, `robust_z`, `is_anomaly`, `direction`.

- Remediation execution adds `device_id`, `reason` (policy decision), `detail` (action result), `approved_by`, and `timestamps.requested_at`. Status values unchanged; a human rejection is recorded as `rejected_by_policy` with the approver in `reason`.

- Verification results (`GET /verifications`) add `device_id` to the minimum record. `source` is always `zabbix`.

## Rules

- Producers and consumers use these names.
- Device-specific trigger names live on the profile.
- Do not add camera-only fields to the core incident, correlation, or RCA records.
- Do not change a field after another workstream depends on it without a reviewed note in this file.
