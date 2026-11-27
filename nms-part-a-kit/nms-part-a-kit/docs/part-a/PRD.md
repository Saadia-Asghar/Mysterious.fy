# Part A: Product Requirements (PRD)

**Project:** Intelligent Generic NMS (FYP). **Owner of this part:** Person 2 or Person 3 (Zakriya / Ali decide who takes Part A and who takes Part B).
**Part A name:** Zabbix + generic monitoring + controlled self-healing.
**Status date of source plans:** camera plan 10 Nov 2026.

## 1. Why this part exists

The NMS is one system for many kinds of devices. Part A is the layer that **watches the devices** (Zabbix), **turns what it sees into events the rest of the system understands**, and **fixes a small set of safe problems by itself, then proves the fix worked**. Without Part A nothing real enters the system: Grafana has no data, osTicket gets no tickets, and the intelligence layer has no events.

## 2. Goal in one sentence

When a monitored device has a problem, Zabbix detects it, the NMS decides what to do under that device's safety policy, an approved action runs only if allowed, Zabbix confirms recovery, and anything that cannot be fixed safely reaches a human as a ticket.

```
Device -> Profile/Connector -> Zabbix -> Events -> Intelligence/Decision -> Grafana + osTicket / Self-healing -> Verify (Zabbix)
          \_______________ Part A ______________/                          \________ Part A ________/
```

## 3. What is in scope (the Part A task list)

Numbers match the team plan ("Part A") so you can tick them off.

| # | Requirement from the plan | Delivered by | Status in this kit |
|---|---|---|---|
| A1 | Zabbix server, frontend and database running | `docker/docker-compose.yml` (already in repo) | Exists. Never run yet: you run it (guide step 5) |
| A2 | Hosts, templates, items, triggers, events, problems, actions | `monitoring-zabbix/provision.py setup`, `templates/*.json` | **Built**, unit-tested, **not yet run on a live Zabbix** |
| A3 | Generic onboarding: organization/site → device profile → connector → metrics → rules | `provision.py onboard`, `inventory*.json`, host groups `NMS/<org>/<site>`, host tags | **Built**, unit-tested |
| A4 | Camera/test device first through ICMP; SNMP, agents, MQTT, REST, custom adapters possible later | ICMP template for cameras and switches, HTTP template for the test service | ICMP and HTTP built. SNMP/MQTT: future profiles (see §7) |
| A5 | Pass monitoring data to Grafana and relevant events to the integration layer | Grafana data source (exists), NMS webhook media type and action created by `setup` | **Built**; live check pending |
| A6 | Define device capabilities and approved actions per device profile | `device-profiles/*.json` (`capabilities`, `allowed_playbooks`, `default_policy`) | Exists |
| A7 | Controlled remediation playbooks | `remediation-playbooks/restart_test_service.json` + `integration-api/app/remediation.py` | Exists |
| A8 | Automation modes: Monitor Only, Recommend, Require Approval, Auto-Remediate | Policy engine (exists) + **automation cycle** (new: requests the playbook by itself) | **Built** |
| A9 | After an approved action, verify recovery again through Zabbix | `integration-api/app/zabbix_api.py`, verification in `main.py`; cycle now runs it automatically | Exists + **automated** |
| A10 | Success → resolved/auto-healed; failure or not permitted → ticket path | Incident states `resolved` / `escalated` + osTicket client | Exists |
| A11 | Action/audit log; no unrestricted commands | `executions` and `verifications` tables, `GET /executions`, `GET /verifications`; playbooks are named files, never free commands | Exists |

## 4. Users and what each gets

| User | Gets from Part A |
|---|---|
| Network/IT team | Real problems with the right device, severity and team, not noise |
| Maintenance team | Tickets only for what automation could not or must not fix |
| Management | Honest numbers: how many incidents auto-healed vs escalated |
| Your supervisor / examiner | A reproducible demo: break a service, watch detect → decide → heal → verify |

## 5. Functional requirements

**FR1 Generic by construction.** No device-type logic in code. A new device type = one profile file + one Zabbix template file (+ playbooks if healing is wanted). A test fails if a profile has no template or a template uses a name its profile does not declare.

**FR2 One naming rule.** Zabbix host name equals NMS `device_id`. `onboard` creates both sides from one inventory entry so they cannot drift.

**FR3 Detection.** Cameras and switches: availability (no reply 3 times in a row), latency, packet loss through ICMP every 60 s. Test service: HTTP health every 30 s. A device that is down raises one problem, not three (trigger dependencies).

**FR4 Events reach the NMS.** Every trigger carrying tag `nms_event_type` is sent on problem **and** on recovery by a webhook, with the host name, event type, severity and value.

**FR5 Safety policy decides.** Each device has a policy: `monitor_only`, `recommend`, `require_approval`, `auto_remediate`. Cameras default to `monitor_only`. Only the policy engine may start an action.

**FR6 Automation cycle.** One cycle syncs events into incidents, requests the first playbook the top-ranked cause's profile allows (once per incident), and verifies finished actions with Zabbix. It can be started by hand (`POST /automation/run`) or on a timer (`NMS_AUTOMATION_INTERVAL_SECONDS`).

**FR7 Verification from Zabbix only.** A playbook saying "done" is never proof. Healthy means Zabbix has no open problem for the host. Still unhealthy after the timeout (default 300 s) → `escalated` + ticket.

**FR8 Audit.** Every decision, run, approval, rejection and verification is stored with time and who approved.

**FR9 Repeatable.** `setup` and `onboard` can be run again without creating duplicates.

## 6. Non-functional requirements and safety boundaries

* **No unrestricted commands.** Playbooks are JSON files with a fixed action type; the target is the registered device address plus a fixed path. The API accepts a `playbook_id`, never a command or URL.
* **Never touch medical or safety-critical control.** Such equipment is monitor-and-escalate only. Cameras are `monitor_only`.
* **No secrets in git.** `.env` and `monitoring-zabbix/inventory.json` are ignored. The webhook token lives in `.env`.
* **Only authorized devices.** Use your own lab devices or ones you have written permission to monitor.
* **Honest claims.** A parameter or result is claimed only after its fault was caused on purpose and the alert appeared and cleared. Thresholds are provisional until agreed.
* **Small and clear code.** No dead code, no unused files, every file has a reason (see TRD §9).

## 7. Out of scope (and why)

| Item | Why |
|---|---|
| Dashboards | Person 1 (Grafana) |
| osTicket setup, ticket fields, closing tickets on recovery | Person 3 / Part B |
| Anomaly detection, correlation, root-cause ranking internals | Shared intelligence layer (already in repo) |
| Exporting Zabbix history to the NMS as telemetry (feeds anomaly detection) | Stretch task, prompt P11 in the prompts file |
| SNMP: PoE power, port errors, uptime; RTSP stream check; MQTT | Listed "to add" or "if supported" in the camera plan; need real hardware details first. Each is one new template file + profile entry |
| Camera reboot or configuration changes | Camera policy is `monitor_only` by design |
| Storing passwords or video | Security and privacy |
| Voltage read from the camera, image analysis | Not network management |

## 8. Success criteria (acceptance)

Part A is **done** when all of these are demonstrated and written down with screenshots:

1. `pytest` passes (139 tests in this kit).
2. `provision.py setup` runs on a live Zabbix 7.0 without errors, and the template, media type, user media and action are visible in the Zabbix UI.
3. `provision.py onboard` creates the test service as a Zabbix host; **Latest data** shows `Health endpoint HTTP status = 200`.
4. Break the test service: a Zabbix problem appears within ~1 minute and the event is visible at `GET /events` with `source: zabbix`.
5. Policy `require_approval`: an execution waits as `pending`; after approval the service restarts, Zabbix recovers, the incident becomes `resolved`.
6. Policy `auto_remediate`: the same without approval.
7. `fault/stuck`: restart runs, health stays bad, after the timeout the incident is `escalated` and a ticket exists.
8. Policy `monitor_only` or `recommend`: nothing is executed, a blocked decision is recorded.
9. A camera or switch (real or simulated address) raises `device_unreachable` when taken offline, and recovers when brought back; one problem, not three.
10. Grafana (Person 1) shows your hosts in the Organization → Site → Device selection.
11. For each ICMP parameter you report in your thesis: fault caused on purpose, alert seen, alert cleared.

## 9. Metrics to report (from the plan)

Remediation success rate (resolved by automation ÷ automated attempts), time from fault to Zabbix problem (MTTD), time from fault to resolved (MTTR), number of blocked actions, number of escalations. The data is in the `events`, `executions`, `verifications` tables; `GET /grafana/summary` aggregates it.

## 10. Risks and open questions

| Risk or question | Effect | What to do |
|---|---|---|
| Docker needs hardware virtualization; the first dev machine had none | Cannot run Zabbix | Enable virtualization (BIOS) and WSL2, or use another machine or a Linux VM |
| ICMP from a container to LAN devices can be blocked by Docker Desktop networking | Camera pings fail | Test with `docker exec`; fall back to a Linux host or `network_mode: host` |
| Camera make/model, switch model, NVR access unknown | Cannot add SNMP/RTSP items | Ask supervisor/GIKI IT; add a profile and template per answer |
| Latency/loss thresholds not agreed | Provisional 100 ms / 5 % | Agree, then edit two macro values |
| Templates and API calls written without a live Zabbix | A call may be rejected by real Zabbix 7.0 | Guide step 8 shows the error format and the fix path; prompt P3 asks Cursor to fix it |
| Ticket for an incident is opened at sync even when automation then heals it | Open ticket after auto-heal | Part B closes tickets on `resolved` (agree this with Part B) |
