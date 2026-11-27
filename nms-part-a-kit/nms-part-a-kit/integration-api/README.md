# Integration API

Local Python service for the generic NMS integration layer. It loads device profiles, stores devices, and accepts telemetry and events whose names are declared on the device's profile.

This service does not monitor a network by itself. Zabbix monitors and sends events here; this service correlates them, applies policy, runs approved playbooks and asks Zabbix whether the problem is gone.

## Run locally

From the repository root, after `python3 -m venv .venv` and `pip install -r integration-api/requirements.txt`:

```bash
.venv/bin/uvicorn app.main:app --app-dir integration-api --env-file .env --host 0.0.0.0 --port 8000
```

`--env-file .env` loads your settings. `--host 0.0.0.0` lets Zabbix, which runs in Docker, reach the API; set `NMS_ZABBIX_WEBHOOK_TOKEN` in `.env` when you do this. On a machine with no Docker, `--host 127.0.0.1` is enough.

Open http://127.0.0.1:8000 for the local registration page, or http://127.0.0.1:8000/docs for the API.

The SQLite file defaults to `data/nms.sqlite` and is not committed. Profiles are read from `device-profiles/`.

## Automation cycle (Part A)

One cycle does three things in order: sync events into incidents (and tickets), request the first playbook the top-ranked cause's profile allows (the device's automation policy then decides whether it runs, waits for approval or is only recorded), and ask Zabbix whether each action fixed the problem.

* `POST /automation/run` runs one cycle now and returns what it did.
* Set `NMS_AUTOMATION_INTERVAL_SECONDS` (for example `30`) and the service runs a cycle by itself at that interval. `0`, the default, switches this off.
* An incident is handled automatically once. After its first execution it is only moved by approval, verification or a human.

## Tests


```bash
.venv/bin/python -m pytest
```
