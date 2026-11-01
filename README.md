# Intelligent Generic Network Management System

An academic Final Year Project for monitoring, understanding, and responding to failures in network-connected infrastructure.

Zabbix is the monitoring foundation, Grafana is the visualization layer, and osTicket is the human incident workflow. The project contribution is the device-generic layer around them: normalized events, anomaly detection, event correlation, probable root-cause analysis, policy-aware decisions, and controlled self-healing with independent monitoring verification.

CCTV / IP cameras are the first vertical slice used to build and demonstrate that architecture. They are not the product boundary.

The GitHub repository name is `Mysterious.fy`. The product name is the Intelligent Generic Network Management System.

## Read this first

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Working architecture for implementation |
| [docs/fyp-specification.md](docs/fyp-specification.md) | Full FYP specification, readable on GitHub |
| [docs/source/Intelligent_Generic_NMS_Complete_FYP_Project_Documentation.docx](docs/source/Intelligent_Generic_NMS_Complete_FYP_Project_Documentation.docx) | Original specification document |
| [docs/data-contracts.md](docs/data-contracts.md) | Shared entities and identifiers |
| [docs/team-start.md](docs/team-start.md) | Who owns what, and what can start now |
| [docs/milestones.md](docs/milestones.md) | Build order and current status |
| [CLAUDE.md](CLAUDE.md) | Short context for coding agents |

The Word document is the detailed FYP specification. The Markdown architecture and contracts are the working copy for the team. If they disagree, stop and resolve the disagreement before changing the design.

## Architecture

```text
Supported device
        ↓
Device profile / connector
        ↓
Zabbix
        ↓
Monitoring metrics / events
        ↓
Custom integration layer
        ↓
Normalized events + context
        ↓
Intelligence layer
        ↓
Anomaly detection + event correlation + probable root cause
        ↓
Policy / decision engine
       ↙                    ↘
Human incident            Approved controlled
via osTicket              self-healing
       ↘                    ↙
        Verification through Zabbix
              ↓
           Grafana
```

Operational lifecycle:

```text
DETECT → NORMALIZE → ANALYZE → CORRELATE → DIAGNOSE
      → DECIDE → ACT / ESCALATE → VERIFY → DISPLAY
```

Conceptual inventory:

```text
Organization → Site → Zone / Building / Plant → Device Group → Device
```

A device references a reusable profile. Device-specific behavior stays in profiles, connectors, adapters, templates, and configuration.

## First profile

`ip_camera_basic`

- Connectors: ICMP, with optional SNMP or HTTP where the device supports them
- Metrics: availability, latency, packet loss
- Triggers: unreachable, high latency, high packet loss
- Dashboard: one reusable IP camera dashboard
- Default automation: monitor only

## Git workflow

```text
main  = latest known stable version
dev   = active development and integration
feature/* = isolated work, branched from dev and merged back only to dev
```

This documentation is published on `dev`. Do not merge `dev` into `main` until a milestone is complete, its checks pass, and that merge is explicitly approved.

Do not commit passwords, API keys, tokens, or real device addresses. Use placeholders and environment variables.

## Run the integration service locally

This is the first runnable piece. It stores devices, telemetry, and events on this machine. Zabbix, Grafana, and osTicket are not started.

```bash
python3 -m venv .venv
.venv/bin/pip install -r integration-api/requirements.txt
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --app-dir integration-api --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 to register a device. API details are at http://127.0.0.1:8000/docs. The database file `data/nms.sqlite` stays local.

See [integration-api/README.md](integration-api/README.md).

## Current status

Architecture documentation and the local integration service are on `dev`. Tests cover profile loading, device registration, telemetry, and events. Docker, Zabbix, Grafana, osTicket, correlation, RCA, and self-healing are not implemented yet. See [docs/milestones.md](docs/milestones.md).

Work is tested locally, then pushed to `dev`. `main` changes only after an approved merge.
