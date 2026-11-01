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

## Current status

Architecture documentation is on `dev`. Application code, Docker services, Zabbix, Grafana, osTicket, the integration API, models, and self-healing are not implemented yet. The next implementation step is Milestone 0 / Milestone 1 only after the team agrees to start it. See [docs/milestones.md](docs/milestones.md).
