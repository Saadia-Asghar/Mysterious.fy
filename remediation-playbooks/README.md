# Remediation playbooks

Explicit, approved actions only. Each playbook is a JSON file here; the API refers to it by `playbook_id` and never accepts a command.

```json
{
  "playbook_id": "restart_test_service",
  "description": "...",
  "applies_to_device_types": ["test_service"],
  "required_capability": "restart",
  "action": {"type": "http_post", "path": "/restart"},
  "timeout_seconds": 10
}
```

## Rules enforced in `integration-api/app/remediation.py`

- Action types are a fixed list implemented in code (currently only `http_post`). Anything else fails to load.
- The target URL is the registered device's `management_address` + the playbook `path`. Requests cannot supply a URL.
- The playbook must be in the device profile's `allowed_playbooks`, match its device type, and the profile must have the required capability.
- Policy (device `automation_policy`, defaulting to the profile's `default_policy`):

| Policy | Result |
|---|---|
| `monitor_only` | `rejected_by_policy`; humans handle it (osTicket) |
| `recommend` | `rejected_by_policy` with the suggested playbook named |
| `require_approval` | `pending` until `POST /executions/{id}/approve` (or `/reject`, which escalates) |
| `auto_remediate` | runs immediately |

- One pending or running action per incident.
- Outcomes: action accepted → execution `completed`, incident `verifying` (Zabbix verification decides health, M12). Action failed or rejected → incident `escalated`.

## API

`GET /playbooks` · `POST /incidents/{incident_id}/remediation` `{playbook_id, device_id?}` (defaults to the top RCA cause) · `POST /executions/{id}/approve|reject` `{approved_by}` · `GET /executions[?incident_id=]` · `GET /executions/{id}`

## Safe demo target

`test-environment/simulators/test_service.py` with profile `test_service_basic` (default policy `require_approval`). It can be made "stuck" so a restart succeeds but health stays bad, which is the failed-recovery scenario for M12.

Status: implemented and tested (`tests/test_remediation.py`) against the simulator via a mock transport. Not yet run against a live process monitored by Zabbix.
