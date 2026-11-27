# NMS Part A: instructions for GitHub Copilot

This repository is a slice of the team's Intelligent Generic NMS project. You are helping with **Part A: Zabbix monitoring, generic device onboarding, and controlled self-healing**.

Read before changing anything: `docs/part-a/PRD.md`, `docs/part-a/TRD.md`, `docs/part-a/STEP_BY_STEP_GUIDE.md`, `CLAUDE.md`, `docs/data-contracts.md`.

## What the system does

Device -> Zabbix (watches it) -> webhook -> integration API (FastAPI, `integration-api/app/main.py`) -> per-device safety policy -> approved playbook -> Zabbix confirms recovery, or the incident escalates to a ticket for a human.

Key files:
- `monitoring-zabbix/provision.py`: `setup` creates Zabbix templates, webhook media type and action; `onboard` registers devices and creates Zabbix hosts.
- `monitoring-zabbix/templates/<profile_id>.json`: Zabbix items and triggers for one device profile.
- `device-profiles/*.json`: what each device type measures, which problems exist, which playbooks are allowed.
- `remediation-playbooks/*.json`: the approved fixes.
- `integration-api/app/main.py`: API, policy flow, verification, automation cycle (`POST /automation/run`).
- `tests/`: offline tests using a fake Zabbix API.

This folder is a slice of the team repo. Files named in `CLAUDE.md` that are missing here (experiments, evaluation scripts, the Grafana dashboard builder) belong to other people. Do not recreate them.

## Scope

You may change: `monitoring-zabbix/`, the automation code in `integration-api/app/main.py`, `remediation-playbooks/`, `device-profiles/` (only together with a matching template), `test-environment/`, `docker/`, tests, and the Part A docs.

Ask before changing: `integration-api/app/osticket.py`, `intelligence/`, `visualization-grafana/`, names in `docs/data-contracts.md`.

## Hard rules

1. **Generic by construction.** No device-type or device-name logic in Python. A new device type is a profile JSON plus a template JSON.
2. **Safety.** Playbooks are named JSON files. Never accept or execute free-form commands or URLs. The policy engine (`remediation.py`) alone decides whether an action runs. Cameras stay `monitor_only`. Never automate medical or safety-critical control.
3. **Naming.** The Zabbix host name equals the NMS `device_id`. A trigger's `nms_event_type` tag must be one of its profile's `triggers`.
4. **Zabbix 7.0 LTS only** (`docker/docker-compose.yml` pins it). Do not use macros or API fields newer than 7.0. `{EVENT.TIMESTAMP}` is 7.2+ and must not be used. When unsure, check the Zabbix 7.0 manual.
5. **No secrets in git.** Never write passwords, tokens or real IP addresses into tracked files or into chat. `.env` and `monitoring-zabbix/inventory.json` stay git-ignored.
6. **Be honest.** Do not say something works unless it was run. The offline tests use a fake Zabbix; say "not verified on live Zabbix" until a real run confirms it.
7. **No dead code.** No unused imports, variables, functions or files, no commented-out blocks, and no README text describing things that do not exist.
8. **Smallest change.** Fix the cause, not the symptom. Never delete or weaken a test to make it pass. Do not refactor unrelated code.

## Commands

```
python -m venv .venv
.venv\Scripts\Activate.ps1                 # Windows PowerShell (Linux/macOS: source .venv/bin/activate)
pip install -r integration-api/requirements.txt -r requirements-dev.txt
python -m pytest -q                        # expect: 139 passed
ruff check --select F .                    # expect: All checks passed!

python -m uvicorn app.main:app --app-dir integration-api --env-file .env --host 0.0.0.0 --port 8000
python -m uvicorn test_service:app --app-dir test-environment/simulators --host 0.0.0.0 --port 9100
python monitoring-zabbix/provision.py setup
python monitoring-zabbix/provision.py onboard
```

## Before you say "done"

Run `python -m pytest -q` and `ruff check --select F .`, show the output, and confirm both are clean. Every behaviour change needs a test. Keep the README, PRD and TRD in step with the code (file paths, commands, ports, environment variables, test counts).

## Things only the human does

Docker and BIOS virtualization setup; creating the Zabbix API token; filling `.env` and `monitoring-zabbix/inventory.json`; causing real faults (breaking the test service, unplugging devices); `git commit` and `git push`. Do not ask the human to paste secrets into chat.
