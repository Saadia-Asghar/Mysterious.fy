# NMS Part A Kit: Zabbix, generic monitoring and controlled self-healing

Starter kit for **Person 2, Part A** of the Intelligent Generic NMS final-year project. It contains the parts of the team repository (`dev` branch) that Part A uses or touches, plus the new Part A work, so you can run it and build on it.

**Start here:** [docs/part-a/STEP_BY_STEP_GUIDE.md](docs/part-a/STEP_BY_STEP_GUIDE.md). It assumes nothing and walks you from installing tools to a demonstrated self-healing loop.

| Read | When |
|---|---|
| [docs/part-a/PRD.md](docs/part-a/PRD.md) | What Part A must deliver, scope, acceptance criteria |
| [docs/part-a/TRD.md](docs/part-a/TRD.md) | How it works and which file does what |
| [docs/part-a/STEP_BY_STEP_GUIDE.md](docs/part-a/STEP_BY_STEP_GUIDE.md) | Doing it, with exact commands and a troubleshooting table |
| [monitoring-zabbix/README.md](monitoring-zabbix/README.md) | The Zabbix folder in detail |
| [CLAUDE.md](CLAUDE.md), [docs/](docs/) | The team's shared context and full specification |

## What Part A is

```
Device -> Profile/Connector -> Zabbix -> Monitoring & Events -> Decision -> Self-healing -> Verify (Zabbix)
```

Zabbix watches devices. When a problem occurs it sends an event to the integration API. A per-device safety policy decides whether an approved fix may run. After a fix, **Zabbix**, not the fix, says whether the problem is gone. Anything that cannot be fixed safely goes to a human as a ticket.

## What was added to the team code

* `monitoring-zabbix/provision.py` with `setup` (templates, webhook, action) and `onboard` (register devices + create Zabbix hosts + topology), driven by profile-matched files in `monitoring-zabbix/templates/`.
* An **automation cycle** in the integration API (`POST /automation/run`, optional timer): sync events, request the approved playbook, verify with Zabbix.
* A **bug fix** in the Zabbix webhook script: it used `{EVENT.TIMESTAMP}`, which does not exist in the pinned Zabbix 7.0 LTS and would have made every event fail.
* `extra_hosts` on the Zabbix container so the webhook can reach the API on your computer.
* 37 new tests (139 in total).

## Quick start (details in the guide)

```powershell
python -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r integration-api/requirements.txt -r requirements-dev.txt
python -m pytest -q                       # offline, no Docker
copy .env.example .env                    # then replace every change_me
docker compose -f docker/docker-compose.yml --env-file .env up -d zabbix-db zabbix-server zabbix-web
# Zabbix UI http://localhost:8080 -> create an API token -> put it in .env
python -m uvicorn app.main:app --app-dir integration-api --env-file .env --host 0.0.0.0 --port 8000
python monitoring-zabbix/provision.py setup
python -m uvicorn test_service:app --app-dir test-environment/simulators --host 0.0.0.0 --port 9100
copy monitoring-zabbix\inventory.example.json monitoring-zabbix\inventory.json
python monitoring-zabbix/provision.py onboard
```

## Layout

```
.cursor/rules/nms-part-a.mdc      Rules for Cursor / AI agents
.env.example                      All settings (copy to .env, never commit .env)
docker/                           Zabbix, Grafana, osTicket, databases (Docker Compose)
monitoring-zabbix/                PART A: provisioning script, Zabbix templates, webhook script, inventories
device-profiles/                  What each device type measures, may do, and is allowed to run
remediation-playbooks/            The approved fixes (named files, never free commands)
integration-api/                  FastAPI service: events, incidents, policy, remediation, verification, automation
intelligence/                     Correlation and root-cause code the API imports (shared layer)
test-environment/                 Lab test service and the live fault-scenario list
visualization-grafana/            Data sources and dashboard only so the Docker stack starts (Person 1)
ticketing-osticket/               Placeholder for Person 3 / Part B
tests/                            139 tests, offline
docs/                             Team specification + docs/part-a/ (PRD, TRD, guide)
```

## What is not here, on purpose

Evaluation experiments and result files, the Grafana dashboard generator, the original Word specification, the fault-scenario generator. They are not needed for Part A; they come in the separate `nms-extras-not-needed.zip` and in the team repository.

## Status, honestly

Everything is written and passes offline tests against a **fake** Zabbix API. It has **not** been run against a live Zabbix 7.0 yet: that is guide steps 5 to 12, and the first thing you do. Latency and packet-loss thresholds are provisional until agreed with your supervisor.
