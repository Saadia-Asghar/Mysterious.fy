# Architecture

Working architecture for the Intelligent Generic Network Management System. This follows the FYP specification. It does not replace it. The section-by-section specification is [fyp-specification.md](fyp-specification.md).

## Product

The system monitors supported network-connected devices, explains related failures, chooses a safe response, and checks through monitoring whether the service actually recovered.

Mature products keep their jobs:

- Zabbix collects metrics and raises events
- Grafana shows operational state
- osTicket tracks human incidents

The FYP builds the device-generic path between detection and resolution.

## Problem

One fault often becomes many alerts. A failed switch can appear as a down switch plus a separate failure for every camera behind it. Operators then separate symptoms from cause, open or update an incident, decide what is safe, and confirm recovery. The system closes that loop.

## Why the core stays generic

Every asset has a stable `device_id` and a `profile_id`. Profiles, connectors, adapters, templates, and configuration hold device-specific behavior. The core uses:

```text
Organization → Site → Zone / Building / Plant → Device Group → Device
```

CCTV is the first profile, `ip_camera_basic`. Later profiles (Linux server, router or switch, solar inverter, IoT sensor, and other supported assets) add connectors, metrics, capabilities, and dashboard templates. Correlation, RCA, policy, ticketing, and verification stay in place.

A device is supported when an authorized connector and a profile exist. The design does not claim every vendor.

## Flow

```text
Supported device
  CCTV | switch | router | server | solar | IoT | other supported asset
        ↓
Device profile / connector
  ICMP | SNMP | agent | MQTT | REST | adapter
        ↓
Zabbix
  items | metrics | triggers | events | problems
        ↓
Integration service
  normalize | enrich | map IDs | store context
        ↓
Intelligence layer
  anomaly detection | correlation | probable RCA
        ↓
Policy / decision
  monitor | recommend | approval | auto
        ↙                         ↘
    osTicket                 Approved playbook
        ↘                         ↙
              Health verification
                    Zabbix
                      ↓
                   Grafana
     operational and management dashboards
```

```text
DETECT → NORMALIZE → ANALYZE → CORRELATE → DIAGNOSE
      → DECIDE → ACT / ESCALATE → VERIFY → DISPLAY
```

Section 3 of the specification draws integration and intelligence in one summary box. Section 8 separates them. Implementation keeps them as two stages: integration prepares a normalized event with context; intelligence analyzes it.

## Components

### Zabbix

Monitoring foundation. Hosts represent devices or services. Templates make monitoring reusable. Items are collected values. Triggers define problem conditions. Events and problems are the detected state. Actions can forward relevant events into the integration service. After remediation, Zabbix is the independent health check. Zabbix monitoring is infrastructure, not the research claim.

### Grafana

Primary visualization. Dashboard hierarchy:

```text
Organization overview
  → Site overview
  → Device-type overview
  → Individual device
  → Incident / RCA / remediation detail
```

Variables: `$organization`, `$site`, `$zone`, `$device_type`, `$device`.

One reusable camera dashboard serves every camera. Grafana reads anomaly scores, probable cause, ticket status, and verification state. It does not calculate them.

Camera panels, when that profile is shown: current status, availability, latency, packet loss, history, current incident, anomaly score, probable root cause and confidence, ticket status, remediation and verification state.

### osTicket

Human workflow for investigation, approval, and manual resolution. The integration layer decides the incident content:

- device and incident context
- severity
- detection time and source
- probable root cause when available
- affected devices
- responsible team
- status
- escalation when automation is unavailable, disallowed, or unsuccessful

### Integration service

A Python FastAPI service is the specified implementation. It exists so Zabbix, Grafana, osTicket, and intelligence are not wired point to point.

- receive or collect monitoring events
- normalize external payloads
- map device, event, and incident identities
- enrich events with topology and device context
- invoke intelligence
- coordinate ticket creation
- request a permitted remediation
- store operational mappings and audit information
- expose custom results where visualization needs them

### Custom database

PostgreSQL for NMS records. Zabbix and osTicket keep their own databases. TimescaleDB is an option only if time-series volume later justifies it.

Records include organizations, sites, zones, users, roles, teams, device types, profiles, devices, connectors, capabilities, metric definitions, topology nodes and edges, normalized events, incidents, anomaly results, RCA results, ticket mappings, playbooks, remediation executions, notifications, and audit logs.

The core schema does not grow a separate table per device family unless extension data truly requires it.

### Intelligence

This is a major FYP contribution. It turns measurements and alerts into operational understanding.

**Anomaly detection.** Behavior that differs from an expected pattern. Early camera features may include latency, packet loss, availability pattern, response-time variation, and failure frequency. The first model is interpretable and reproducible. A more complex model waits on data and an evaluation that justifies it.

**Event correlation.** Groups events that belong to one incident, using time, topology, and event or device type.

**Probable RCA.** Ranks likely causes with a score and a method. It does not claim certainty. Controlled experiments inject a known fault so the ranking can be measured.

### Policy

| Policy | Behavior |
|---|---|
| `monitor_only` | Observe and alert |
| `recommend` | Show a recommended action and do not execute it |
| `require_approval` | A person approves before an approved playbook runs |
| `auto_remediate` | Only an approved low-risk playbook may run, then Zabbix verifies |

`ip_camera_basic` defaults to `monitor_only`.

### Controlled self-healing

```text
Problem detected
  → correlation / RCA
  → device capability
  → automation policy
  → approved playbook?
        no → osTicket
        yes → execute the playbook
              → Zabbix verifies
                    recovered → resolve
                    not recovered → osTicket / escalate
```

An AI model does not invent commands. Actions are named playbooks. The safe demonstration uses a controllable test service, such as a restart of that test service, rather than an unsafe action on a real camera.

### Verification

The playbook process exiting successfully is an execution fact. Zabbix then checks the monitored health. That check closes the loop: detect, diagnose, decide, act, verify, display.

## Topology

Topology is what depends on what. Correlation and RCA need it.

```text
CORE-SWITCH
├── SWITCH-A
│   ├── CAM-001
│   ├── CAM-002
│   └── CAM-003
└── SWITCH-B
    ├── CAM-004
    └── CAM-005
```

`CAM-001 depends_on SWITCH-A`, and `SWITCH-A depends_on CORE-SWITCH`.

## Worked failure

Illustration from the specification, not an experimental measurement.

```text
10:01:01  SWITCH-A down
10:01:03  CAM-001 down
10:01:04  CAM-002 down
10:01:04  CAM-003 down
```

Conventional handling can produce four alerts and several tickets.

Intelligent handling produces one incident for SWITCH-A, CAM-001, CAM-002, and CAM-003. The specification’s example ranking is SWITCH-A 0.91, then the cameras at 0.04, 0.03, and 0.02. Those numbers are the document’s example shape. They are not a result from this repository.

On the default camera policy the human path opens one osTicket incident. Grafana shows the grouped incident, the ranked cause, the ticket, and later the verification state.

Two unrelated camera failures must stay separate. If an approved test action runs and health stays bad, verification fails and the incident escalates.

## CCTV version 1

Profile `ip_camera_basic`:

| Field | Value |
|---|---|
| Connector | ICMP |
| Optional connectors | SNMP, HTTP |
| Metrics | availability, latency_ms, packet_loss_percent |
| Triggers | device_unreachable, high_latency, high_packet_loss |
| Dashboard | ip_camera_basic |
| Capabilities | health_check |
| Default policy | monitor_only |

First working path: authorized camera or test endpoint → ICMP → Zabbix → availability, latency, packet loss → Grafana CCTV dashboard.

First failure path: camera unreachable → Zabbix problem → integration normalizes the event → incident decision → osTicket when a human is required → Grafana shows the active state.

Topology scenario: several cameras share an upstream parent. An injected upstream fault is grouped, and RCA ranks that parent above the cameras.

Dashboards to plan:

| Dashboard | Content |
|---|---|
| Organization overview | Device counts, healthy, problems, critical incidents, auto-healed count, MTTR |
| Site overview | Health by zone, active incidents, device table |
| Device detail | Status, availability, latency, packet loss, history, incident |
| Intelligence / RCA | Correlated incident, affected devices, anomaly score, ranked cause |
| Remediation | Policy, action, execution state, verification result, history |

## Later profiles

| Profile | Connector examples | Metric examples |
|---|---|---|
| ip_camera_basic | ICMP, SNMP | availability, latency, packet loss |
| linux_server_basic | Agent, SNMP | CPU, RAM, disk, network |
| solar_inverter_basic | MQTT, REST/API | power, voltage, current, temperature |
| router_switch_basic | SNMP, ICMP | reachability, interface status, errors, utilization |
| iot_sensor_basic | MQTT, API | sensor telemetry, availability |

## Logical deployment

One development host may run:

- Zabbix server, Zabbix database, Zabbix web
- Grafana
- osTicket and osTicket database
- NMS integration API
- intelligence service
- custom NMS database

These are logical components. They do not require one physical machine each. They connect only to authorized or simulated test devices.

Suggested stack from the specification: Zabbix, Grafana, osTicket, Python and FastAPI, PostgreSQL, pandas and scikit-learn, NetworkX or an equivalent, Docker Compose, Git.

Versions are not pinned in the specification. Pin them when service installation is approved. Do not invent credentials or device addresses.

## Security

- least-privilege service accounts
- secrets outside source control
- role-based access for administration and remediation
- audit logs for policy decisions and remediation executions
- separate test and production configuration
- no destructive experiments on unauthorized infrastructure
- safety-critical equipment can remain monitor and escalate only
- this repository is public; keep real network details out of it

Roles: platform admin; customer or site admin; engineer; viewer or management; research team.

Notifications (email, SMS, messaging) follow incident severity and ownership. They are an operational feature, not the research contribution.

The data model allows more than one organization. Full production multi-tenancy can remain beyond the FYP.

## Evaluation

Compare the intelligent pipeline with conventional threshold handling. Metrics, to be computed from real experiments only:

| Metric | Purpose |
|---|---|
| Precision, recall, F1 | Anomaly or event classification where applicable |
| RCA top-1 and top-k | Whether the injected cause is ranked correctly |
| Alert reduction | Raw alerts versus correlated incidents |
| MTTD | Detection speed |
| MTTR | Resolution or recovery time |
| Remediation success rate | Automatic recovery that monitoring confirmed |
| Failed or blocked action rate | Failures and safety-policy behavior |

Fault scenarios and expected behavior are listed in [milestones.md](milestones.md) and in specification section 34. No experimental numbers are stored in this repository yet.

## Research claim

The claim is the device-generic architecture and the custom layer: normalization, topology and timing, anomaly and RCA methods, policy, verified remediation, and a measured comparison with a conventional baseline. The final report should describe the team’s design and measured results. It should not claim that every existing monitoring product lacks these features, or that every failure can be diagnosed.

## What implementation must not change silently

- Zabbix, Grafana, and osTicket roles
- the separate integration and intelligence stages
- profile-based device behavior
- approved playbooks only
- Zabbix verification after automation
- the shared identifiers in [data-contracts.md](data-contracts.md)
