# Intelligent Generic Network Management System

Complete FYP project documentation, transcribed for GitHub from the Word specification.

Original file: [source/Intelligent_Generic_NMS_Complete_FYP_Project_Documentation.docx](source/Intelligent_Generic_NMS_Complete_FYP_Project_Documentation.docx)

Product concept, architecture, CCTV V1, intelligence, self-healing, implementation, and evaluation.

The working implementation view of this same design is [architecture.md](architecture.md).

## 1. Executive summary

This FYP proposes an Intelligent Generic Network Management System (NMS) for monitoring, understanding, and responding to failures in network-connected infrastructure. The project does not attempt to rebuild mature monitoring, dashboarding, and ticketing products from scratch. Instead, Zabbix is used as the monitoring foundation, Grafana as the visualization layer, and osTicket for human incident management. A custom integration and intelligence layer is built around them to normalize events, detect anomalies, correlate related failures, rank probable root causes, make policy-aware response decisions, and coordinate controlled self-healing with independent verification.

The first complete implementation is CCTV/IP camera infrastructure. Cameras provide a practical test case for device onboarding, availability and network-health monitoring, dashboards, dependency topology, incident creation, and controlled fault experiments. CCTV is only the first vertical slice. The architecture is deliberately device-generic so later profiles can represent routers, switches, servers, solar equipment, IoT sensors, and other supported devices where suitable interfaces and authorization exist.

## 2. Background and problem

Organizations often operate large numbers of network-connected devices. A single infrastructure fault can generate many downstream alerts. For example, if a switch connecting several cameras fails, a basic monitoring setup may report the switch and every dependent camera as separate failures. An operator then has to determine which alerts are symptoms, identify the likely root cause, create or update an incident, decide what action is safe, and confirm whether the system recovered.

The project addresses this operational gap between raw monitoring and resolution. The aim is to create a closed operational loop from detection to diagnosis, decision, response, and verification.

## 3. Proposed solution

The proposed system combines five major capabilities:

1. Generic device onboarding through profiles and connectors.
2. Reliable monitoring and event generation using Zabbix.
3. Operational visualization using Grafana.
4. Human incident workflow using osTicket.
5. A custom intelligence and orchestration layer for anomaly detection, correlation, probable RCA, and controlled remediation.

Core lifecycle:

```text
DEVICE
  ↓
DEVICE PROFILE / CONNECTOR
  ↓
ZABBIX
Monitoring → Metrics → Triggers → Events
  ↓
CUSTOM INTEGRATION / INTELLIGENCE
Normalize → Detect Anomaly → Correlate → Rank Probable Root Cause
  ↓
POLICY / DECISION ENGINE
  ├─────────────────┐
  ↓                 ↓
HUMAN PATH        AUTOMATION PATH
osTicket          Approved Playbook
  │                 │
  └────────┬────────┘
           ↓
    ZABBIX VERIFICATION
           ↓
        GRAFANA
Monitoring + Incident + RCA + Remediation State
```

## 4. Product vision

The long-term product is a configurable operations platform. A customer or administrator defines organizations, sites, device types, connectors, metrics, alert rules, dashboards, device capabilities, and automation policies. The same core pipeline then handles supported devices.

```text
Organization → Site → Zone / Building / Plant → Device Group → Device
```

## 5. Objectives

- Design a device-independent NMS architecture.
- Monitor real or simulated authorized devices using standard connectors.
- Normalize monitoring events into a common internal model.
- Build reusable operational dashboards.
- Automatically generate meaningful human incidents.
- Detect abnormal behavior in telemetry.
- Correlate related events using timing and topology.
- Rank probable root causes.
- Support policy-controlled safe remediation.
- Verify remediation independently through monitoring.
- Evaluate whether the intelligent pipeline improves over conventional threshold and event handling.
- Demonstrate extensibility beyond the first CCTV use case.

## 6. Scope

| In scope | Not automatically in scope |
|---|---|
| Device health and network telemetry | CCTV video analytics or facial/object recognition |
| Profiles and connectors for supported devices | Universal support for every vendor or device |
| CCTV as the first vertical slice | Production control of all GIKI cameras |
| Anomaly, correlation, and RCA research | Claiming all failures can be diagnosed perfectly |
| Approved low-risk remediation | Unrestricted AI-generated device commands |
| Human escalation through ticketing | Autonomous control of safety-critical equipment |
| Experimental fault scenarios | Predictive maintenance without suitable historical data |

## 7. Users and roles

| Role | Main responsibilities |
|---|---|
| Platform admin | Organizations, sites, profiles, integrations, users, and policies |
| Customer / site admin | Devices and operational configuration for an assigned scope |
| Engineer | Telemetry, incidents, RCA, and remediation history |
| Viewer / management | Read-only health and operational summaries |
| Research / FYP team | Controlled experiments, algorithm evaluation, and system maintenance |

## 8. Complete architecture

```text
SUPPORTED DEVICES
CCTV | Switch | Router | Server | Solar | IoT | Other Supported Asset
                              │
                              ▼
                  DEVICE PROFILE / CONNECTOR
             ICMP | SNMP | Agent | MQTT | REST | Adapter
                              │
                              ▼
                           ZABBIX
           Items | Metrics | Triggers | Events | Problems
                              │
                              ▼
                     INTEGRATION SERVICE
          Normalize | Enrich | Map IDs | Store Context
                              │
                              ▼
                     INTELLIGENCE LAYER
        Anomaly Detection | Correlation | Probable RCA
                              │
                              ▼
                     DECISION / POLICY
              Monitor / Recommend / Approval / Auto
                         ┌────┴────┐
                         ▼         ▼
                     osTicket   Playbook
                         │         │
                         └────┬────┘
                              ▼
                      HEALTH VERIFICATION
                           Zabbix
                              │
                              ▼
                           GRAFANA
             Operational and Management Dashboards
```

## 9. Generic device model

Every monitored asset has a stable device identity and references a reusable profile. Device-specific behavior belongs in profiles, connectors, and adapters.

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

## 10. Device profiles and connectors

A profile describes how a class of device is monitored and represented.

```text
PROFILE
├── device_type
├── supported connector(s)
├── metric definitions
├── trigger / alert rules
├── dashboard template
├── capabilities
└── allowed automation / playbooks
```

| Connector | Typical use |
|---|---|
| ICMP | Reachability, latency, and packet loss |
| SNMP | Network and device telemetry where supported |
| Agent | Local server or host telemetry |
| MQTT | IoT and telemetry messaging |
| REST / API | Vendor or application integrations |
| Custom adapter | Translation for a supported proprietary interface |

## 11. Zabbix monitoring layer

Zabbix is the monitoring foundation. It knows whether a configured host is reachable, collects metrics, evaluates trigger conditions, and creates events and problems. The team does not claim Zabbix monitoring as original research. Its purpose is to provide reliable telemetry and events to the custom layers.

- Hosts represent monitored devices and services.
- Templates make monitoring reusable.
- Items represent collected values.
- Triggers define problem conditions.
- Events and problems represent detected states.
- Actions and integration mechanisms can forward relevant events.
- After remediation, Zabbix provides independent health verification.

## 12. Grafana visualization layer

Grafana is the primary user-facing visualization layer and Saadia's main implementation responsibility. It combines monitoring and operational information into reusable dashboards. Grafana does not calculate the anomaly model or RCA. It displays results produced by the relevant data sources and services.

```text
Organization overview
  → Site overview
  → Device-type overview
  → Individual device
  → Incident / RCA / remediation detail
```

Example CCTV panels: current status, availability, latency, packet loss, historical latency and health, current incident, anomaly score, probable root cause and confidence, ticket status, remediation and verification state.

Grafana variables: `$organization`, `$site`, `$zone`, `$device_type`, `$device`.

The goal is one reusable camera dashboard.

## 13. osTicket incident layer

osTicket provides the human workflow for incidents that require investigation, approval, or manual resolution. The custom integration layer determines what meaningful incident information should be sent.

- Incident and device context
- Severity
- Detection time and source
- Probable root cause when available
- Affected devices
- Responsible team
- Status and human workflow
- Escalation when automation is unavailable, disallowed, or unsuccessful

## 14. Custom integration service

A Python/FastAPI service is a suitable implementation for the custom integration layer. It separates the project from direct point-to-point coupling between every external tool.

- Receive or collect monitoring events.
- Normalize external payloads.
- Map device, event, and incident identities.
- Enrich events with topology and device context.
- Invoke intelligence services.
- Coordinate ticket creation.
- Request permitted remediation.
- Store operational mappings and audit information.
- Expose custom results to visualization where needed.

## 15. Common data contracts

Telemetry: `device_id`, `metric_name`, `value`, `unit`, `timestamp`, `source`

Event: `event_id`, `device_id`, `event_type`, `severity`, `started_at`, `source`

Incident: `incident_id`, `event_ids`, `affected_devices`, `severity`, `status`, `created_at`

Anomaly: `device_id`, `anomaly_score`, `model_version`, `timestamp`

RCA: `incident_id`, `ranked_causes[{device_id or service_id, score}]`, `method`

Ticket mapping: `incident_id`, `provider`, `external_ticket_id`

Remediation: `execution_id`, `incident_id`, `playbook_id`, `policy`, `status`, `timestamps`

Field-level examples for implementation are in [data-contracts.md](data-contracts.md).

## 16. Generic database / information model

- organizations, sites, zones
- users, roles, teams
- device_types, device_profiles, devices
- device_connectors, device_capabilities
- metric_definitions
- topology_nodes, topology_edges
- normalized_events
- incidents and incident_events
- anomaly_results and rca_results
- ticket_mappings
- playbooks and remediation_executions
- notifications
- audit_logs

A generic schema avoids separate core tables such as `camera_table` and `solar_table` unless domain-specific extension data genuinely requires them.

## 17. Topology and dependency model

Topology represents what depends on what. It is essential for meaningful correlation and RCA.

```text
CORE-SWITCH
├── SWITCH-A
│   ├── CAM-001
│   ├── CAM-002
│   └── CAM-003
└── SWITCH-B
    ├── CAM-004
    └── CAM-005

CAM-001 depends_on SWITCH-A
CAM-002 depends_on SWITCH-A
CAM-003 depends_on SWITCH-A
SWITCH-A depends_on CORE-SWITCH
```

## 18. Intelligence / data science layer

This is a major FYP contribution. Basic monitoring produces raw measurements and alerts. The intelligence layer attempts to convert those signals into higher-level operational understanding.

### 18.1 Anomaly detection

Anomaly detection identifies behavior that differs from an expected pattern. CCTV network-health features may include latency, packet loss, availability patterns, response-time variation, and failure frequency. The first model should be interpretable and reproducible. More complex ML should only be introduced if justified by data and evaluation.

### 18.2 Event correlation

Correlation groups events that likely belong to the same underlying incident. Initial correlation can combine event timing, topology and dependency relationships, and event or device type.

### 18.3 Probable root-cause analysis

RCA ranks likely causes. In controlled experiments, the actual injected fault is known, so the system's ranking can be measured objectively.

## 19. Example: why correlation and RCA matter

```text
10:01:01  SWITCH-A DOWN
10:01:03  CAM-001 DOWN
10:01:04  CAM-002 DOWN
10:01:04  CAM-003 DOWN
```

Basic handling: 4 separate alerts, and possibly several tickets.

Intelligent handling: 1 correlated incident.

Affected: SWITCH-A, CAM-001, CAM-002, CAM-003.

Probable root cause ranking in the specification’s illustration:

| Rank | Cause | Score |
|---|---|---|
| 1 | SWITCH-A | 0.91 |
| 2 | CAM-001 | 0.04 |
| 3 | CAM-002 | 0.03 |
| 4 | CAM-003 | 0.02 |

These scores are the specification’s example. They are not a measured result from this repository.

## 20. Policy / decision engine

The system must not automatically act on every diagnosis. The response depends on device capabilities, risk, and configured policy.

| Policy | Behavior |
|---|---|
| `monitor_only` | Observe and alert only |
| `recommend` | Show a recommended action and do not execute it |
| `require_approval` | Human approval required before an approved playbook |
| `auto_remediate` | Only an approved low-risk playbook may run automatically |

## 21. Controlled self-healing

Self-healing means executing a predefined approved action and then checking whether the monitored system actually recovered. It does not mean allowing an AI model to invent and execute arbitrary commands.

```text
Problem detected
      ↓
Correlation / RCA
      ↓
Check device capability
      ↓
Check automation policy
      ↓
Approved playbook exists?
   ┌──────┴──────┐
   NO            YES
   ↓              ↓
osTicket       Execute action
                  ↓
              Zabbix verifies
               ┌──┴──┐
             Fixed   Not fixed
               ↓       ↓
            Resolve  osTicket / escalate
```

## 22. Verification loop

A remediation command returning success does not prove that the device or service is healthy. The system therefore uses monitoring to verify the real post-action state. This creates the closed loop: Detect → Diagnose → Decide → Act → Verify → Display.

## 23. Security, RBAC, and audit

- Least-privilege credentials and service accounts.
- Secrets outside source control.
- Role-based access to administration and remediation.
- Audit logs for policy decisions and remediation executions.
- Separate test and production configuration.
- No destructive experiments on unauthorized infrastructure.
- Safety-critical equipment can remain monitor and escalate only.
- Sensitive network information should not be exposed in public FYP material.

## 24. Alerting and notifications

Notification channels can later include email, SMS, or messaging integrations, but alerting should follow incident severity and ownership. Notification configuration is an operational feature, not the primary research contribution.

## 25. Multi-tenant / multi-organization direction

The generic hierarchy allows multiple organizations or customers to be represented with separated sites, users, devices, and permissions. Full production-grade multi-tenancy may be beyond the first FYP implementation, but the data model should avoid assumptions that only one organization can exist.

## 26. CCTV V1 — detailed implementation

### 26.1 Initial camera profile

```text
profile_id: ip_camera_basic
connector: ICMP
optional: SNMP / HTTP
metrics:
  - availability
  - latency_ms
  - packet_loss_percent
triggers:
  - device_unreachable
  - high_latency
  - high_packet_loss
dashboard: ip_camera_basic
capabilities:
  - health_check
default_policy: monitor_only
```

### 26.2 First working path

```text
Authorized camera / test endpoint → ICMP → Zabbix
  → availability / latency / packet loss → Grafana CCTV dashboard
```

### 26.3 First failure path

```text
CAM-001 becomes unreachable
  → Zabbix trigger / problem
  → Integration normalizes event
  → Incident decision
  → osTicket if human action is required
  → Grafana displays active state
```

### 26.4 Topology scenario

Introduce a switch or simulated dependency so several cameras share an upstream parent. Inject a known upstream fault and collect the resulting event sequence. The correlation and RCA layer should group related events and rank the upstream device as a likely cause.

### 26.5 Safe remediation demonstration

Use a controllable test service or device. An approved playbook may restart the test service. Zabbix must then verify whether health returned. If not, the incident is escalated.

## 27. CCTV dashboards

| Dashboard | Example content |
|---|---|
| Organization overview | Total cameras and devices, healthy, problems, critical incidents, auto-healed count, MTTR |
| Site overview | Health by building or zone, active incidents, device table |
| Device detail | Status, availability, latency, packet loss, history, incident |
| Intelligence / RCA | Correlated incident, affected devices, anomaly score, ranked probable cause |
| Remediation | Policy, action, execution state, verification result, history |

## 28. Generalization beyond CCTV

| Profile | Connector examples | Metric examples |
|---|---|---|
| ip_camera_basic | ICMP, SNMP | availability, latency, packet loss |
| linux_server_basic | Agent, SNMP | CPU, RAM, disk, network |
| solar_inverter_basic | MQTT, REST/API | power, voltage, current, temperature |
| router_switch_basic | SNMP, ICMP | reachability, interface status, errors, utilization |
| iot_sensor_basic | MQTT, API | sensor-specific telemetry, availability |

The core incident, correlation, RCA, policy, ticket, and verification architecture should remain unchanged. New device types primarily add profiles, connectors, metrics, capabilities, and dashboard templates.

## 29. Technology stack

| Layer | Suggested technology |
|---|---|
| Monitoring | Zabbix |
| Visualization | Grafana |
| Ticketing | osTicket |
| Integration / API | Python + FastAPI |
| Custom data | PostgreSQL; TimescaleDB extension if justified |
| Data science | Python, pandas, scikit-learn |
| Topology analysis | NetworkX or equivalent |
| Deployment | Docker / Docker Compose |
| Version control | Git / GitHub |

## 30. Development deployment

```text
Development VM / host
├── Zabbix Server
├── Zabbix Database
├── Zabbix Web
├── Grafana
├── osTicket
├── osTicket Database
├── NMS Integration API
├── Intelligence Service
└── Custom NMS Database
```

Connected to authorized or simulated test devices. The architecture is logical. Development does not require one physical server per component.

## 31. Repository structure

```text
nms-fyp/
├── README.md
├── docs/
├── docker/
├── monitoring-zabbix/
├── visualization-grafana/
├── ticketing-osticket/
├── integration-api/
├── intelligence/
│   ├── anomaly/
│   ├── correlation/
│   └── rca/
├── device-profiles/
├── remediation-playbooks/
├── test-environment/
└── scripts/
```

That tree is the specification’s target. This documentation commit creates `docs/` and the root README. The implementation directories are added with the milestone that fills them.

## 32. Team division

| Area | Ownership |
|---|---|
| Grafana and generic visualization | Saadia |
| Zabbix, device monitoring, and controlled self-healing | Zakarya or Ali |
| osTicket and incident integration | The other of Zakarya or Ali |
| Intelligence, integration decisions, and evaluation | Shared team contribution |
| Architecture, documentation, and testing | Shared responsibility |

## 33. Implementation roadmap

| Phase | Target | Result |
|---|---|---|
| 1 | Environment and repository | Run core services and document setup |
| 2 | First CCTV endpoint | Zabbix collects availability, latency, and loss |
| 3 | Grafana | Visualize real monitoring data |
| 4 | Reusable dashboard | Use variables for multiple devices and sites |
| 5 | Integration service | Normalize monitoring events |
| 6 | osTicket | Create a meaningful human incident |
| 7 | Topology | Represent dependencies |
| 8 | Correlation | Group related events |
| 9 | RCA | Rank probable causes |
| 10 | Anomaly detection | Generate and evaluate anomaly outputs |
| 11 | Self-healing | Run one approved safe test action |
| 12 | Verification | Confirm recovery through monitoring |
| 13 | Unified visualization | Show the full lifecycle |
| 14 | Evaluation | Compare the intelligent pipeline with the baseline |
| 15 | Second device profile | Demonstrate generalization |

The team’s working checklist, including a foundation step before services are installed, is [milestones.md](milestones.md).

## 34. Testing strategy

- Unit tests for normalization, algorithms, and policy logic.
- Integration tests across service boundaries.
- Controlled fault injection with known ground truth.
- Regression tests for bugs found during development.
- End-to-end scenario tests.
- Configuration and reproducibility tests from a clean environment.

| Fault scenario | Expected behavior |
|---|---|
| One camera unreachable | Single relevant device incident |
| High latency or loss | Defined degraded or anomaly behavior |
| One switch causes three cameras down | Correlation groups events; RCA favors the switch |
| Two unrelated cameras fail | Do not incorrectly merge them |
| Approved test service fails | Playbook executes and monitoring verifies |
| Action executes but health remains bad | Verification fails and the incident escalates |

## 35. Evaluation

| Metric | Purpose |
|---|---|
| Precision / recall / F1 | Evaluate anomaly or event classification where applicable |
| RCA top-1 / top-k accuracy | Measure whether the known injected cause is ranked correctly |
| Alert reduction | Compare raw alerts with meaningful correlated incidents |
| MTTD | Measure detection speed |
| MTTR | Measure resolution or recovery time |
| Remediation success rate | Measure successful verified automatic recovery |
| Failed / blocked action rate | Measure failures and safety-policy behavior |

Results must come from actual experiments. This repository does not yet contain experimental numbers.

## 36. Research contribution and novelty

The defensible contribution is the specific device-generic architecture and custom layer that normalizes telemetry and events, uses topology and timing for correlation, applies anomaly and RCA methods, makes policy-aware response decisions, coordinates controlled remediation with independent verification, and quantitatively evaluates the result against a conventional monitoring baseline.

Existing monitoring and automation systems already contain related features, so the final report should avoid universal novelty claims. The contribution should be framed around the team's design, algorithms, integration choices, implementation, and measured results.

## 37. Baseline versus proposed intelligent NMS

| Conventional baseline | Proposed FYP |
|---|---|
| Threshold trigger fires | Threshold or event is still detected by monitoring |
| Each alert may be handled independently | Related events can be correlated |
| Operator manually investigates cause | Probable root cause is ranked |
| Manual ticket creation and triage | Incident can be enriched and created automatically |
| Manual recovery | Approved low-risk remediation may run |
| Operator checks whether it is fixed | Monitoring verifies recovery |
| Separate views | Grafana provides a unified operational view |

## 38. Limitations and risks

- Device support depends on available protocols, APIs, and authorization.
- Ground-truth fault scenarios must be designed carefully.
- Limited historical data may constrain ML methods.
- RCA produces probable causes, not guaranteed truth.
- Real network access may be restricted.
- Self-healing must remain conservative for safety.
- Open-source component APIs and version behavior can change.
- Full enterprise multi-tenancy and security hardening may exceed FYP scope.

## 39. Commercialization / productization direction

A commercial version could package device profiles, customer and site onboarding, RBAC, managed connectors, dashboards, incident workflows, policy packs, and supported remediation playbooks. Production use would require stronger security, deployment automation, vendor testing, observability, backup and high availability, support processes, license review, and formal safety boundaries.

## 40. FYP deliverables

- System architecture and design documentation
- Generic device and profile model
- Working CCTV vertical slice
- Zabbix monitoring configuration and templates
- Reusable Grafana dashboards
- osTicket incident integration
- Custom integration API
- Topology representation
- Anomaly, correlation, and RCA implementation
- Controlled remediation and verification workflow
- Test environment and fault scenarios
- Evaluation scripts and results
- Repository and reproducibility documentation
- Final report, presentation, and demonstration

## 41. Demo flow

1. Show organization and site CCTV health.
2. Open an individual camera or device dashboard.
3. Inject an authorized controlled failure.
4. Show Zabbix detecting it.
5. Show the normalized incident and event.
6. Run a topology failure scenario.
7. Show the correlated incident and probable RCA.
8. Show osTicket or the approved remediation path.
9. Show Zabbix verification.
10. Show the final state in Grafana.
11. Show a second device profile, or an architecture explanation, so CCTV is visibly the first slice.

## 42. Defense explanation

The FYP is a generic intelligent Network Management System. Zabbix is the monitoring foundation, Grafana provides reusable visualization, and osTicket provides the human incident workflow. The main contribution is the layer between detection and resolution. It normalizes events, uses telemetry, event timing, and topology for anomaly detection, correlation, and probable root-cause analysis, then applies policy to decide whether an incident should go to a human or an approved low-risk remediation playbook. After any automated action, Zabbix independently verifies whether the system recovered. CCTV is the first end-to-end implementation. Device profiles and connectors keep the architecture extensible to other supported infrastructure.

## 43. Important defense questions

**Why use Zabbix?** It is a mature monitoring foundation, so the FYP can focus on intelligence and orchestration.

**Why Grafana if Zabbix has dashboards?** Grafana provides flexible reusable operational views and can combine multiple relevant data sources. Dashboarding itself is not claimed as novelty.

**Where is the data science?** Anomaly detection, correlation and RCA ranking, and quantitative evaluation.

**Is this just connecting tools?** The tools provide infrastructure. The custom layer normalizes and contextualizes events, performs intelligence, applies policy, coordinates verified remediation, and is experimentally evaluated.

**Can it support every device?** The architecture is device-independent. A device still needs an authorized supported connector, API, or protocol, and a profile.

**Will it reboot hospital or industrial devices automatically?** Safety-critical systems can be monitor and escalate only. Automatic actions require an explicit safe capability and policy.

**How will RCA be proved?** Controlled fault scenarios with known ground truth, measuring whether the injected cause is ranked correctly.

**What is new?** The team’s specific generic architecture, intelligence and RCA method, policy-controlled verified remediation, and measured improvement over the baseline.

## 44. Developer context

This section is secondary to the project specification above. It exists to prevent implementation drift.

Source of truth: this is a generic intelligent NMS. CCTV is V1 only.

Preserve:

```text
Device → Profile / Connector → Zabbix → Metrics / Events
→ Integration / Intelligence → Anomaly + Correlation + RCA
→ Policy → osTicket OR approved self-healing
→ Zabbix verification → Grafana
```

When stuck:

1. Identify the current implementation milestone.
2. Find the last known-good state.
3. Classify the failing component.
4. Reproduce the smallest failure.
5. Check producer, then interface or schema, then consumer.
6. Trace `device_id`, `event_id`, `incident_id`, and `execution_id`.
7. Inspect logs before changing another component.
8. Make the smallest compatible fix.
9. Add a regression test.
10. Re-run the milestone acceptance test.
11. Never silently change architecture or shared schemas.
12. Keep device-specific behavior in profiles, adapters, and templates.

The short agent copy of this section is [../CLAUDE.md](../CLAUDE.md).

## 45. Glossary

| Term | Meaning |
|---|---|
| NMS | Network Management System |
| Telemetry | Time-based operational measurements |
| RCA | Root Cause Analysis |
| Correlation | Grouping related events |
| Playbook | Approved action sequence |
| RBAC | Role-Based Access Control |
| MTTD | Mean Time To Detect |
| MTTR | Mean Time To Resolve or Repair |
| Connector | Mechanism used to communicate with a device or system |
| Profile | Reusable configuration describing a device class |
| Verification | Independent check that an action actually restored health |

## 46. Final project statement

The project should always be described as an Intelligent Generic Network Management System with CCTV as the first implementation. The final system is defined by the complete closed loop from generic device monitoring to normalized intelligence, probable diagnosis, policy-aware response, verified remediation or human escalation, and operational visualization.
