# CLAUDE.md

Concise context for coding agents. The detailed specification is [docs/fyp-specification.md](docs/fyp-specification.md) and the original Word file in [docs/source/](docs/source/). The working design is [docs/architecture.md](docs/architecture.md).

## Project

Intelligent Generic Network Management System. CCTV is version-1 only.

Zabbix monitors. Grafana displays. osTicket handles human incidents. A custom integration and intelligence layer normalizes events, detects anomalies, correlates failures, ranks probable causes, applies policy, and coordinates controlled remediation. Zabbix verifies recovery. A command reporting success does not prove recovery.

## Preserve this flow

```text
Device → Profile / Connector → Zabbix → Metrics / Events
→ Integration → Normalized events + context
→ Intelligence → Anomaly + Correlation + RCA
→ Policy → osTicket OR approved playbook
→ Zabbix verification → Grafana
```

Lifecycle: DETECT, NORMALIZE, ANALYZE, CORRELATE, DIAGNOSE, DECIDE, ACT / ESCALATE, VERIFY, DISPLAY.

## Component ownership

| Component | Responsibility |
|---|---|
| Zabbix | Hosts, items, triggers, events, problems, post-action health |
| Grafana | Reusable dashboards. Display only |
| osTicket | Human ticket workflow and escalation |
| Integration API | Normalize, enrich, map IDs, orchestrate, audit |
| Custom database | NMS records. Separate from Zabbix and osTicket databases |
| Intelligence | Anomaly, correlation, probable RCA |
| Policy | monitor_only, recommend, require_approval, auto_remediate |
| Playbooks | Explicit approved actions only |
| Verification | Independent Zabbix health check |

## Directory map

Documentation currently lives at the repository root and under `docs/`. Implementation directories are created when the milestone that fills them is approved. Expected later layout:

```text
docker/  monitoring-zabbix/  visualization-grafana/  ticketing-osticket/
integration-api/  intelligence/{anomaly,correlation,rca}/
device-profiles/  remediation-playbooks/
test-environment/{simulators,fault-scenarios}/  tests/  scripts/
```

## Git

- `main`: stable. Do not commit unfinished work here.
- `dev`: integration branch. Normal work happens here.
- `feature/*`: branch from `dev`, merge back only to `dev`.
- Never merge a feature branch directly into `main`.
- Merge `dev` into `main` only after acceptance tests pass and a person explicitly approves.
- Tag `mN-...-good` only after that milestone has actually been tested.

## Current milestone

Documentation publication on `dev`. No implementation milestone is in progress. No `*-good` tag exists. Last shared commit before this documentation was `71e3809` on `main`.

## Data contracts

Stable entities: Device, Telemetry, Event, Incident, Anomaly Result, Correlation Result, RCA Result, Ticket Mapping, Remediation Execution, Verification Result.

Trace: `device_id` → `event_id` → `incident_id` → `ticket_id` / `execution_id` → verification result.

Details and examples: [docs/data-contracts.md](docs/data-contracts.md). Do not change a shared schema after another component depends on it unless the change is reviewed and recorded.

## Commands

No runtime is installed for this documentation commit. Do not add development commands here until a milestone introduces them.

## Constraints an agent must not silently change

- The generic pipeline and the CCTV-as-V1 boundary
- Which product owns monitoring, visualization, and ticketing
- Policy-controlled remediation and the ban on invented commands
- Monitoring-based verification after every automated action
- Shared identifiers and schemas
- Secrets: never commit credentials, tokens, or real management addresses
- Research integrity: never fabricate accuracy, MTTR, anomaly, RCA, or remediation results
- Do not start the next milestone without explicit approval

## When stuck

1. Name the current milestone and the last known-good commit.
2. Reproduce the smallest failure.
3. Check producer, then contract, then consumer.
4. Trace `device_id`, `event_id`, `incident_id`, and `execution_id`.
5. Read logs before editing another component.
6. Apply the smallest compatible fix and add a regression test.
7. Re-run the milestone acceptance check.
