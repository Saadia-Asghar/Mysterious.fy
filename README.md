# Intelligent Generic Network Management System

An academic Final Year Project that is also built to run as a product: a multi-company network
management service that watches devices, groups related failures into one incident, names the
probable cause, opens and routes tickets, and confirms recovery through monitoring.

Zabbix monitors, Grafana displays, osTicket handles human escalation. The project's own layer sits
between them: normalized events, anomaly detection, correlation, probable root cause, policy,
controlled remediation, a customer portal and ticketing.

CCTV / IP cameras are the first device type. They are not the product boundary: devices are
described by reusable profiles in `device-profiles/`.

GitHub repository: `Mysterious.fy`.

## How it works

```text
Device → Profile → Zabbix (ping, loss, latency) → webhook → NMS events
→ correlation + probable cause → incident → ticket to the device's team
→ device answers again → Zabbix confirms → incident and ticket resolved
```

Lifecycle: DETECT → NORMALIZE → ANALYZE → CORRELATE → DIAGNOSE → DECIDE → ACT / ESCALATE → VERIFY → DISPLAY.

## What is working

| Area | Status | Details |
|---|---|---|
| Integration API | done | FastAPI + SQLite, devices, events, telemetry, topology |
| Intelligence | done | anomaly (robust z-score), correlation v1/v2, probable root cause |
| Incidents | done | persisted, continued (not duplicated) when alerts arrive seconds apart |
| Remediation | done | policy engine, approved JSON playbooks, Zabbix verification |
| Live monitoring | verified locally with lab devices | [docs/live-monitoring.md](docs/live-monitoring.md) |
| osTicket | verified locally | [docs/osticket-live-verification.md](docs/osticket-live-verification.md) |
| Grafana | done | dashboard `NMS Operations` with analytics |
| Customer portal | done | companies, sites, devices, users, roles at `/app` |
| Ticketing | done | teams, SLA timers, history, reports, CSV export — [docs/ticketing-and-data.md](docs/ticketing-and-data.md) |
| Platform admin | done | company health, suspend, support requests, notices |
| Real hardware | not yet | next step: one real switch and camera |
| Email / SMS alerts | not yet | |

Lab results are SIMULATED and are not evaluation results.

## Run it locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -r integration-api/requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

1. Copy `.env.example` to `.env` and fill in your own values. `.env` stays on your machine.
2. Start Zabbix: `docker compose -f docker/docker-compose.yml --env-file .env up -d zabbix-db zabbix-server zabbix-web`
3. Set Zabbix up for the NMS: `python scripts/zabbix_bootstrap.py` (writes the API token into `.env`).
4. Start the API: `python -m uvicorn app.main:app --app-dir integration-api --host 0.0.0.0 --port 8000`
5. Open http://localhost:8000/app. The first visit creates the staff (super admin) login.

Other services (Grafana, osTicket) are in `docker/docker-compose.yml`; see [docker/README.md](docker/README.md).
Lab devices for testing without hardware: `docker compose -f docker/lab-devices.yml up -d`.

## Secrets

- Never commit `.env`, `data/`, backups, passwords, API keys, tokens or real device addresses.
- Every secret is read from `.env` or the environment; `.env.example` holds only `change_me` placeholders.
- Scripts ask for a password when it is not set; nothing has a built-in default password.
- Tests generate throwaway logins at run time (`tests/_creds.py`), so no password is written in code.
- If a real secret is ever pushed, change it at its source (Zabbix, osTicket, …) first; removing it from Git is not enough.

## Documents

| Document | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Working architecture |
| [docs/product-website-plan.md](docs/product-website-plan.md) | Product, hosting, pages and phases |
| [docs/live-monitoring.md](docs/live-monitoring.md) | Zabbix setup and device-to-ticket flow |
| [docs/ticketing-and-data.md](docs/ticketing-and-data.md) | Tickets, teams, audit trail, backups |
| [docs/osticket-live-verification.md](docs/osticket-live-verification.md) | osTicket live test |
| [docs/data-contracts.md](docs/data-contracts.md) | Shared entities and identifiers |
| [docs/milestones.md](docs/milestones.md) | Build order |
| [docs/fyp-specification.md](docs/fyp-specification.md) | Full FYP specification |
| [CLAUDE.md](CLAUDE.md) | Short context for coding agents |

## Git workflow

```text
main      = stable; merged from dev only after testing and approval
dev       = active development; all work is pushed here
feature/* = branched from dev, merged back only into dev
```
