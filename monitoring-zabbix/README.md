# Zabbix monitoring

Zabbix owns metrics, triggers, problems and post-remediation health verification. Templates follow device profiles, not individual cameras.

## Conventions the integration layer relies on

| Zabbix | NMS | Rule |
|---|---|---|
| Host name (`{HOST.HOST}`) | `device_id` | Must equal the device registered in the integration API, e.g. `CAM-001` |
| Trigger tag `nms_event_type` | `event_type` | Must be one of the device profile's `triggers` |
| `{EVENT.ID}` | `event_id` = `ZBX-<id>` | Stable; redelivery does not duplicate |
| `{EVENT.NSEVERITY}` 0–5 | `severity` | `not_classified` … `disaster` |

## Sending events to the integration API (M5)

1. Alerts → Media types → Create, type **Webhook**, name `NMS Integration`.
2. Paste [media-types/nms_webhook.js](media-types/nms_webhook.js) as the script and add the parameters listed at the top of that file.
3. Create a user (or use Admin) with this media; send to `NMS Integration`.
4. Alerts → Actions → Trigger actions → Create: condition *Tag name equals `nms_event_type`*, operation and recovery operation *Send message* via `NMS Integration`.
5. Optional: set `NMS_ZABBIX_WEBHOOK_TOKEN` for the API and the global macro `{$NMS.WEBHOOK.TOKEN}` to the same value.

Status: route implemented and unit-tested (`tests/test_zabbix_events.py`). End-to-end from a live Zabbix is not verified yet (needs M1 running).

## Verification after remediation (M12)

The integration API never trusts the playbook result. After an action it asks Zabbix: the host is healthy only when Zabbix has **no open problems** for it.

1. Create an API token (Users → API tokens) and set `NMS_ZABBIX_API_URL` and `NMS_ZABBIX_API_TOKEN`.
2. Call `POST /verification/sweep` every 30 s (cron/scheduler), or `POST /executions/{id}/verify` by hand. A recovery event from the NMS webhook also counts as healthy.
3. Still unhealthy after `NMS_VERIFY_TIMEOUT_SECONDS` (default 300) → incident `escalated` and an osTicket ticket is opened.

### Monitoring the lab test service

Host name `SVC-001`. Add an HTTP agent item on `http://<host>:9100/health` (or a web scenario) and a trigger that fires on a non-200 response, with tag `nms_event_type=service_down`.

Status: implemented and tested with a fake Zabbix API (`tests/test_verification.py`); not yet verified against a live Zabbix.
