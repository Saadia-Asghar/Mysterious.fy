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

The local integration service is `integration-api/`. Profiles are `device-profiles/`. Tests are `tests/`. Expected later layout:

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

M0 foundation complete. M1 core services: `docker/docker-compose.yml` written and statically tested (`tests/test_compose.py`) but NOT yet run, because the first dev machine has no Docker. M5 integration side done ahead of M1–M4: `POST /integrations/zabbix/events` normalizes Zabbix problems to `ZBX-<eventid>` events (`integration-api/app/zabbix.py`, `tests/test_zabbix_events.py`, media type in `monitoring-zabbix/media-types/`). M7–M9 done ahead too: `intelligence/topology.py` (depends_on edges, cycle check), `intelligence/correlation` (`time_window_and_topology_v1`: same time window AND directly related, i.e. upstream or same parent), `intelligence/rca` (`topology_time_v1`: coverage 0.7 / alerting 0.2 / earliest 0.1, normalized ranks, not probabilities; considers a silent shared upstream). API: `POST/GET /topology/edges`, `GET /intelligence/incidents` (stateless; `incident_id` = `INC-<first event_id>` until incidents are persisted with M6). Second profile `network_switch_basic` added. M6 done in code: `POST /incidents/sync` persists incidents (status never overwritten by re-analysis) and opens one osTicket ticket per eligible incident via `app/osticket.py`; failures are stored as `ticket_error` and retried; tested with a fake osTicket. `GET /incidents[/{id}]` shows ticket mapping. M10 done in code: `intelligence/anomaly` model `robust_zscore_v1` (median/MAD over previous 30 readings, |z|>=3.5, score |z|/(|z|+3.5), no look-ahead) at `GET /intelligence/anomalies`; `intelligence/anomaly/evaluate.py` gives precision/recall/F1 for M14. Synthetic test data is not an evaluation result. Blocked: Docker cannot run on the dev PC until hardware virtualization is enabled. Next once Docker runs: verify M1, then M2–M4, then wire Zabbix to M5 end to end. The user merges `dev` into `main` themselves once the application works; agents never merge or tag. `main` is still the initial commit.

## Data contracts

Stable entities: Device, Telemetry, Event, Incident, Anomaly Result, Correlation Result, RCA Result, Ticket Mapping, Remediation Execution, Verification Result.

Trace: `device_id` → `event_id` → `incident_id` → `ticket_id` / `execution_id` → verification result.

Details and examples: [docs/data-contracts.md](docs/data-contracts.md). Do not change a shared schema after another component depends on it unless the change is reviewed and recorded.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -r integration-api/requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --app-dir integration-api --host 127.0.0.1 --port 8000
docker compose -f docker/docker-compose.yml --env-file .env up -d   # M1 services (see docker/README.md)
```

Run pytest before pushing to `dev`. Do not commit `.venv/` or `data/`.

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
