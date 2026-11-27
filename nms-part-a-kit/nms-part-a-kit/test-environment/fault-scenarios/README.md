# Fault scenarios (live)

Repeatable ways to cause a real fault on purpose and check that the NMS reacts. Each parameter is only reported as working after its fault has been caused and the alert both appeared and cleared. Use only devices you are authorized to touch.

| # | Fault | How | Expected NMS reaction |
|---|---|---|---|
| 1 | Test service breaks | `curl -X POST http://127.0.0.1:9100/fault/break` | Zabbix problem `service_down` within about 1 minute; event reaches the API; policy decides |
| 2 | Test service restart does not help | `curl -X POST http://127.0.0.1:9100/fault/stuck`, then break it | Restart runs, health stays bad, incident `escalated` and a ticket after `NMS_VERIFY_TIMEOUT_SECONDS` |
| 3 | Recovery | `curl -X POST http://127.0.0.1:9100/fault/clear` | Zabbix recovery; incident `resolved` |
| 4 | Camera or switch off | unplug the device or its cable | `device_unreachable` after 3 missed pings; one problem, not three |
| 5 | Camera back | plug it back in | Zabbix recovery |

Rows 4 and 5 need real authorized hardware and an address you put in `monitoring-zabbix/inventory.json`.
