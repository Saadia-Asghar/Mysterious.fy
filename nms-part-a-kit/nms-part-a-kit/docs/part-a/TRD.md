# Part A: Technical Requirements (TRD)

How Part A is built. Read the PRD first for *what*; this says *how* and *where*.

## 1. Components and who talks to whom

```
 Authorized devices                Docker                                  Your computer (host)
 ──────────────────   ICMP/HTTP   ┌─────────────────────────┐  webhook    ┌─────────────────────────────┐
 camera, switch,   ◄───────────── │ Zabbix server  (10051)  │ ──────────► │ Integration API  (:8000)    │
 test service :9100               │ Zabbix web     (:8080)  │ host.docker │  events → incidents         │
        ▲                         │ Zabbix DB (PostgreSQL)  │  .internal  │  policy → playbook → device │
        │ POST /restart           └────────────▲────────────┘             │  verify ──────────────┐     │
        └────────────────────────────────────────────────────────────────  (reads Zabbix API) ◄────┘     │
                                              │ Zabbix API (JSON-RPC, token)                            │
                                  provision.py (setup / onboard) ─────────────────────────────────────►│ POST /devices
                                                                                                          │ POST /topology/edges
                                                                                                          └─────────────────────────────┘
```

| Component | Where it runs | Port | Started by |
|---|---|---|---|
| Zabbix server / web / DB | Docker | 10051 / 8080 / internal | `docker compose` |
| Integration API (FastAPI) | host | 8000 | `uvicorn` |
| Lab test service (FastAPI) | host | 9100 | `uvicorn` |
| `provision.py` | host, run on demand | none | you |

**Why the API is not in Docker:** the existing design runs it on the host for easy debugging. Docker reaches it through the name `host.docker.internal`, which `docker-compose.yml` maps for the `zabbix-server` service. Hence `--host 0.0.0.0` when starting the API and the test service.

## 2. Data flow, step by step

1. `provision.py onboard` registers `SVC-001` in the API (`POST /devices`) and creates Zabbix host `SVC-001` linked to template `NMS_test_service_basic`. The host macro `{$NMS.BASE_URL}` holds the address **as Zabbix sees it** (`http://host.docker.internal:9100`); the API keeps the address **as the API sees it** (`http://127.0.0.1:9100`). They differ on purpose.
2. Zabbix polls `{$NMS.BASE_URL}{$NMS.HEALTH_PATH}` every 30 s (HTTP agent, headers only, regex extracts the status code).
3. Service breaks → status 503 → trigger `service_down` (tag `nms_event_type=service_down`) → Zabbix problem.
4. Action `NMS: send events to the integration API` matches the tag → media type `NMS Integration` runs `nms_webhook.js` → `POST /integrations/zabbix/events` with `{eventid, host, nms_event_type, severity, value, clock}`.
5. API stores the event as `ZBX-<eventid>` (`value=1` problem; `value=0` recovery, see 8).
6. Automation cycle (timer or `POST /automation/run`):
   1. `sync_incidents`: correlate events using topology and time, rank root causes, store incidents, open tickets above `NMS_TICKET_MIN_SEVERITY`.
   2. For each `open` incident with **no execution yet**: take the top-ranked cause device → its profile → first `allowed_playbooks` entry that exists → `_request_remediation`. The **policy engine** (existing, `remediation.py`) then returns `run`, `pending` or `rejected_by_policy`.
   3. For every execution awaiting verification: ask Zabbix (`problem.get` for the host). No open problem → `resolved`. Still a problem after `NMS_VERIFY_TIMEOUT_SECONDS` → `escalated` + ticket.
7. Playbook `restart_test_service`: `POST <management_address>/restart`. Incident becomes `verifying`, never straight to `resolved`.
8. Zabbix sends a recovery message (`value=0`); the API also treats it as verification that the host is healthy. This is the fastest route to `resolved`.

## 3. File-by-file (what is new, what changed, what is untouched)

### New (Part A)

| File | Purpose | Key points |
|---|---|---|
| `monitoring-zabbix/provision.py` | CLI: `setup` and `onboard` | Reuses `app.zabbix_api.ZabbixApiClient` (one JSON-RPC client in the project). Only creates what is missing. Errors become one readable line (`error: ...`), exit code 1. |
| `monitoring-zabbix/templates/ip_camera_basic.json` | ICMP items + 3 triggers | Item names equal Zabbix's own (`ICMP ping`, `ICMP response time`, `ICMP loss`) because the Grafana dashboard queries those names. |
| `monitoring-zabbix/templates/network_switch_basic.json` | Same for switches | Same checks; separate file so the two can diverge when SNMP is added. |
| `monitoring-zabbix/templates/test_service_basic.json` | HTTP health item + trigger | Uses the host macro `{$NMS.BASE_URL}` set by `onboard` (`address_macro`). |
| `monitoring-zabbix/inventory.example.json`, `inventory.camera.example.json` | Onboarding inputs | Copy to `inventory.json` (git-ignored). |
| `tests/test_zabbix_provision.py` | 27 tests | Fake Zabbix API; real integration API for onboarding; checks templates against profiles. |
| `tests/test_automation.py` | 9 tests | All four policies, stuck service, Zabbix outage, no Zabbix, background loop. |
| `docs/part-a/*` , `README.md`, `.cursor/rules/nms-part-a.mdc` | Documentation and agent rules | |

### Changed

| File | Change | Why |
|---|---|---|
| `integration-api/app/main.py` | Extracted `_request_remediation` (endpoint behaviour unchanged); added `_playbook_for`, `_automation_cycle`, `_automation_loop`, `POST /automation/run`, loop start/stop in lifespan | Without a caller, "auto-remediate" never started by itself |
| `integration-api/app/schemas.py` | `AutomationResult` | Response of the cycle |
| `integration-api/app/settings.py` | `automation_interval_seconds` ← `NMS_AUTOMATION_INTERVAL_SECONDS` (default 0 = off) | Opt-in timer |
| `integration-api/app/zabbix_api.py` | `_call` renamed `call` (public) | Provisioning reuses the client |
| `integration-api/requirements.txt` | `python-dotenv` | `uvicorn --env-file` and `provision.py` read `.env` |
| `monitoring-zabbix/media-types/nms_webhook.js` | **Bug fix.** Removed `{EVENT.TIMESTAMP}` and the token-macro guard; clock = time of sending | `{EVENT.TIMESTAMP}` does not exist in Zabbix 7.0 LTS (added in 7.2). Left as it was, every event would have been rejected (HTTP 422). |
| `docker/docker-compose.yml` | `extra_hosts: host.docker.internal:host-gateway` on `zabbix-server` | The webhook runs in that container and must reach the host |
| `.env.example`, `.gitignore`, `pytest.ini` | new variables, ignore `inventory.json`, add `monitoring-zabbix` to the test path | |
| READMEs | monitoring-zabbix, integration-api, remediation-playbooks, docker, docs index, test-environment/simulators docstring | Reflect the above |

### Existing and relied on, unchanged

`integration-api/app/remediation.py` (policy engine, playbook loader), `app/store.py` (SQLite: devices, events, incidents, executions, verifications), `app/zabbix.py` (webhook → event mapping), `app/analysis.py` + `intelligence/` (correlation, RCA), `app/osticket.py` (tickets), `device-profiles/*.json`, `remediation-playbooks/restart_test_service.json`, `test-environment/simulators/test_service.py`, `docker/docker-compose.yml` (everything else).

## 4. Zabbix object model created by `setup`

| Object | API method | Notes |
|---|---|---|
| Template group `NMS Templates` | `templategroup.create` | Zabbix 7.0 keeps template groups separate from host groups |
| Template `NMS_<profile_id>` | `template.create` | Technical name has no spaces so expressions need no quoting. Visible name `NMS <profile_id>`. Macros carry thresholds. |
| Items | `item.create` | `simple_check` (ICMP) type 3, `http_agent` type 19. Tag `nms_metric` links an item to the profile metric it measures. |
| Triggers | `trigger.create` | Tag `nms_event_type`. `depends_on` becomes a Zabbix dependency. Expression `{TEMPLATE}` is replaced by the template name. |
| Media type `NMS Integration` | `mediatype.create/update` | Type 4 (webhook). Script from `nms_webhook.js`. Parameters: `url, token, eventid, host, nms_event_type, severity, value`. |
| User media | `user.update` | Zabbix runs a media type only for a user who has it. Admin gets one entry (send to `nms`). |
| Action | `action.create` | Condition type 25 (event tag name) equals `nms_event_type`. Operation and recovery operation: send message. |
| Hosts (onboard) | `host.create` | Name = `device_id`; group `NMS/<org>/<site>`; tags `nms_organization`, `nms_site`, `nms_zone`, `nms_profile`; agent-type interface holding the address (ICMP and HTTP need only the address). |

## 5. Interfaces

**Provision CLI**

```
python monitoring-zabbix/provision.py setup
python monitoring-zabbix/provision.py onboard [--inventory PATH] [--nms-url URL]
```
Environment (from `.env`): `NMS_ZABBIX_API_URL`, `NMS_ZABBIX_API_TOKEN` (required), `NMS_ZABBIX_WEBHOOK_URL`, `NMS_ZABBIX_WEBHOOK_TOKEN` (optional but recommended).

**Template file schema** (`monitoring-zabbix/templates/<profile_id>.json`)

| Key | Meaning |
|---|---|
| `profile_id` | Must equal a file in `device-profiles/` (tested) |
| `description`, `macros[]` | Template description and default macro values |
| `address_macro` (optional) | Host macro that receives the monitoring address (HTTP profiles) |
| `items[]` | `name, key, type (simple_check|http_agent), value_type (float|unsigned), delay`, optional `units, description, nms_metric`, and any raw Zabbix item field (`url, retrieve_mode, preprocessing, ...`) |
| `triggers[]` | `nms_event_type` (must be in the profile's `triggers`), `name`, `expression` (with `{TEMPLATE}`), `severity`, optional `depends_on` (an earlier `nms_event_type`) |

**Inventory file**: `devices[]` with `device_id, name, profile_id, organization_id, site_id, zone_id, management_address, responsible_team`, optional `monitoring_address` (address Zabbix uses if different) and `automation_policy`; `topology[]` of `{from, to}` meaning *from depends on to* (camera depends on switch).

**API added:** `POST /automation/run` → `{sync, remediations[], verifications[], errors{}}`.

## 6. Design decisions

| Decision | Reason |
|---|---|
| Provision through the Zabbix API, not by importing exported YAML | One readable source (JSON next to the profiles), testable offline, no dependence on a Zabbix-version-specific export format |
| Create-if-missing, not update | Fewer ways to fail against a live system. To change a template: delete it in the UI, run `setup` again |
| `high_latency` / `high_packet_loss` depend on `device_unreachable` | Zabbix then raises one problem for a dead device. Also stops the correlation layer seeing three events for one cause |
| Automation requests a playbook **once** per incident | A failing action must not be retried in a loop on a real device |
| Automation never overrides policy | `_request_remediation` is the same code path as the manual endpoint |
| Latency kept in seconds in Zabbix | Matches Zabbix defaults and the existing Grafana dashboard. `latency_ms` = value × 1000 when exported |
| Event time = time the alert is sent | `{EVENT.TIMESTAMP}` is not in Zabbix 7.0 LTS. Moving to 7.2+ would allow the exact time |
| Admin user holds the media | Simplest for a lab. A production setup would use a dedicated least-privilege user |

## 7. Testing

| Layer | How | Where |
|---|---|---|
| Unit and component | `python -m pytest` (139 tests, ~5 s, no Docker) | `tests/` |
| Contract between profile and template | Tests fail when a profile has no template, a trigger name is not in the profile, an expression uses an item the template lacks | `tests/test_zabbix_provision.py` |
| Zabbix 7.0 compatibility guard | Test fails if `{EVENT.TIMESTAMP}` returns | same |
| Live | Guide steps 8 to 13; fault table in `test-environment/fault-scenarios/README.md` | manual |

**What the offline tests cannot prove:** that a real Zabbix 7.0 accepts every call and that the HTTP item regex and trigger expressions behave. Treat guide step 8 as the first real test; fix with prompt P3 if Zabbix rejects something.

## 8. Known gaps and handoffs

1. Live Zabbix run: not done in this kit.
2. Ticket is opened at sync even if automation then heals the incident. Part B should update or close it when the incident becomes `resolved`.
3. An incident that recovers on its own with no automation (for example, a camera plugged back in) stays `open`. Closing it on a recovery event is Part B work; agree with them.
4. Telemetry export (Zabbix history → `POST /telemetry`) is not built; anomaly detection needs it (prompt P11).
5. SNMP, RTSP, PoE, MQTT checks need hardware answers first (PRD §7).
6. Thresholds are provisional.

## 9. Rules for keeping the code clean

* Every file has one job and is referenced by a README or a test. Delete what nothing uses.
* No commented-out code. No unused imports or variables: `ruff check --select F .` must print "All checks passed".
* Names in profiles, templates, triggers and events are the shared vocabulary; change them in all places or none (tests catch drift).
* Add behaviour together with a test. Run `python -m pytest` before every commit.
