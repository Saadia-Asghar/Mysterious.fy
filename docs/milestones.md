# Milestones

Build in this order. Finish and review one milestone before starting the next. `dev` is the integration branch. `main` changes only when a completed milestone is explicitly approved for merge.

## Status

| Item | State |
|---|---|
| M0 foundation | Complete on `dev`, awaiting review. Checks: `tests/test_foundation.py` |
| Local integration service | Devices, telemetry, events. M5 Zabbix webhook route `/integrations/zabbix/events` unit-tested; live Zabbix not yet connected. |
| M1 core services | Compose written and statically tested. Not yet run (no Docker on first dev machine). |
| M7–M9 topology, correlation, RCA | Implemented in `intelligence/`, exposed at `/topology/edges` and `/intelligence/incidents`. Unit- and API-tested on synthetic scenarios. Accuracy not yet measured (M14). |
| M6 osTicket | Incidents persisted; one ticket per eligible incident; mapping stored. Tested with a fake osTicket server, not yet live. |
| M10 anomaly detection | `robust_zscore_v1` implemented, exposed at `/intelligence/anomalies`, logic-tested on synthetic seeded series. Not yet evaluated on real runs (M14). |
| M11 controlled self-healing | Policy engine, approval flow and `restart_test_service` playbook on a lab simulator. Tested via mock transport; not yet live. |
| Known-good implementation tag | None |
| `main` | Unchanged until an approved merge |

## Sequence

| ID | Milestone | Done when |
|---|---|---|
| M0 | Project foundation | Repository layout, agent context, contracts, and docs match the specification. Checks pass. Services are not required. |
| M1 | Core services | Zabbix, Grafana, osTicket, and the custom database start from documented configuration. |
| M2 | First endpoint to Zabbix | An authorized or simulated endpoint produces availability, latency, and packet loss. |
| M3 | Zabbix to Grafana | Grafana shows those live series. |
| M4 | Reusable CCTV dashboard | One dashboard, driven by variables, for many devices and sites. |
| M5 | Event to integration API | A Zabbix problem becomes a normalized event with stable IDs. |
| M6 | Integration to osTicket | One meaningful ticket is mapped back to `incident_id`. |
| M7 | Topology | `depends_on` edges represent the switch and camera example. |
| M8 | Event correlation | An upstream fault becomes one incident. Two unrelated cameras stay apart. |
| M9 | Probable RCA | A known injected cause is ranked, and the rank is recorded from the run. |
| M10 | Anomaly detection | An interpretable model emits scores. Evaluation uses real runs. |
| M11 | Controlled self-healing | One approved playbook runs on a test service. |
| M12 | Zabbix verification | Recovery and failed recovery both follow monitoring. Failed recovery escalates. |
| M13 | Unified visualization | Grafana shows incident, RCA, ticket, remediation, and verification. |
| M14 | Experimental evaluation | Baseline versus the intelligent pipeline, from experiment logs only. |
| M15 | Second device profile | A non-CCTV profile uses the same pipeline. |

The specification’s fifteen phases match this list. Phase 1 in the specification (“run core services”) is M1 here. M0 is the foundation that makes that work reviewable.

## Fault scenarios used by later milestones

| Scenario | Expected behavior |
|---|---|
| One camera unreachable | One relevant device incident |
| High latency or loss | The defined degraded or anomaly behavior |
| One switch causes three cameras to go down | Correlation groups the events; RCA favors the switch |
| Two unrelated cameras fail | The incidents stay separate |
| Approved test service fails | The playbook runs and monitoring verifies |
| The action finishes but health stays bad | Verification fails and the incident escalates |

## Tags

A tag such as `m0-foundation-good` is created only after that milestone’s checks have passed. Documentation publication alone does not create a tag.
