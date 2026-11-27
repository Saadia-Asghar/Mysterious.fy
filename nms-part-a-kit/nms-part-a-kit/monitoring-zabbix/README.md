# Zabbix monitoring (Part A)

Zabbix owns metrics, triggers, problems and the post-remediation health check. Everything here is driven by **device profiles**, never by a single camera: a new device type needs a new profile and a new template file, not new code.

## What is in this folder

| Path | What it is |
|---|---|
| `provision.py` | The one script you run. `setup` creates templates, the webhook media type and the action in Zabbix. `onboard` registers devices and creates their Zabbix hosts. |
| `templates/<profile_id>.json` | The Zabbix side of one device profile: items (what is measured) and triggers (when it is a problem). One file per profile in `device-profiles/`. |
| `media-types/nms_webhook.js` | The script Zabbix runs to send an event to the integration API. `setup` uploads it. |
| `inventory.example.json` | Onboarding input that works as-is: the lab test service. |
| `inventory.camera.example.json` | Onboarding input for a switch and a camera. Addresses are placeholders you must replace. |
| `inventory.json` | **Your** inventory (copy of an example). Ignored by git because it holds real addresses. |

## How the pieces connect

```
device-profiles/ip_camera_basic.json  ──same profile_id──►  templates/ip_camera_basic.json
        (what the NMS knows:                                   (what Zabbix measures:
         metrics, trigger names,                                items, trigger expressions,
         allowed playbooks)                                     tag nms_event_type)
                                   inventory.json
                                   (which real devices exist) ──► provision.py onboard
                                                                     ├─► integration API  POST /devices
                                                                     └─► Zabbix host (name = device_id)
```

## Conventions the integration layer relies on

| Zabbix | NMS | Rule |
|---|---|---|
| Host name (`{HOST.HOST}`) | `device_id` | Always equal. `onboard` guarantees it. |
| Trigger tag `nms_event_type` | `event_type` | Must be one of the profile's `triggers`. A test enforces it. |
| `{EVENT.ID}` | `event_id` = `ZBX-<id>` | Stable; redelivery does not duplicate. |
| `{EVENT.NSEVERITY}` 0 to 5 | `severity` | `not_classified` … `disaster`. |
| Host group `NMS/<organization>/<site>` and tags `nms_organization`, `nms_site`, `nms_zone`, `nms_profile` | Grafana variables | Lets dashboards select Organization, Site, Device. |

## What `setup` creates (so you can find it in the Zabbix UI)

| Where in Zabbix | Name |
|---|---|
| Data collection → Templates | `NMS_ip_camera_basic`, `NMS_network_switch_basic`, `NMS_test_service_basic` (template group `NMS Templates`) |
| Alerts → Media types | `NMS Integration` (webhook) |
| Users → Users → Admin → Media | one `NMS Integration` entry, send to `nms` |
| Alerts → Actions → Trigger actions | `NMS: send events to the integration API`, condition *Tag name equals `nms_event_type`*, send on problem and on recovery |

Existing objects are left alone, so you can run `setup` again safely. The one exception is the media type: its script and parameters are refreshed each time, so a new webhook URL or token takes effect. To change a template, delete it in the Zabbix UI and run `setup` again.

## Checks per profile

| Profile | Item | Trigger (`nms_event_type`) | Fires when |
|---|---|---|---|
| ip_camera_basic, network_switch_basic | `icmpping` | `device_unreachable` (high) | no reply 3 checks in a row |
| | `icmppingsec` | `high_latency` (warning) | 5 minute average above `{$NMS.LATENCY.MAX_MS}` |
| | `icmppingloss` | `high_packet_loss` (average) | 5 minute average above `{$NMS.PACKET_LOSS.MAX_PERCENT}` |
| test_service_basic | `nms.health.status` (HTTP) | `service_down` (high) | status is not 200, or no answer for 3 minutes |

`high_latency` and `high_packet_loss` depend on `device_unreachable`, so a dead device raises one problem, not three.

**Thresholds are provisional** (100 ms and 5 %). The camera plan says they must still be agreed with the supervisor. Change the two macro values in `templates/ip_camera_basic.json` and `network_switch_basic.json` once agreed, or override them per host in Zabbix.

Item names `ICMP ping`, `ICMP response time` and `ICMP loss` are exactly what the Grafana dashboard queries. Do not rename them without telling the Grafana owner. Latency is stored in seconds (Zabbix convention); the NMS metric `latency_ms` is that value times 1000.

## Known limits

* The test service template does not collect response time, so the profile's `high_latency` is not raised for it.
* Event time sent to the NMS is the time the alert is sent, not the exact Zabbix event time, because the `{EVENT.TIMESTAMP}` macro does not exist in Zabbix 7.0 LTS. The difference is seconds.
* Written and unit-tested against a fake Zabbix API. Not yet run against a live Zabbix. The step-by-step guide says what to check.

## Verification after remediation

The integration API never trusts a playbook's own success message. After an action it asks Zabbix: the host is healthy only when Zabbix has **no open problems** for it. The automation cycle does this automatically (see `integration-api/README.md`); a Zabbix recovery message also counts. If the host is still unhealthy after `NMS_VERIFY_TIMEOUT_SECONDS` (default 300) the incident becomes `escalated` and an osTicket ticket is opened.
