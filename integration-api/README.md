# Integration API

Local Python service for the generic NMS integration layer. It loads device profiles, stores devices, and accepts telemetry and events whose names are declared on the device's profile.

Zabbix, Grafana, osTicket, correlation, RCA, and remediation are later milestones. This service does not monitor a network by itself.

## Run locally

From the repository root, after `python3 -m venv .venv` and `pip install -r integration-api/requirements.txt`:

```bash
.venv/bin/uvicorn app.main:app --app-dir integration-api --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for the local registration page, or http://127.0.0.1:8000/docs for the API.

The SQLite file defaults to `data/nms.sqlite` and is not committed. Profiles are read from `device-profiles/`.

## Tests

```bash
.venv/bin/python -m pytest
```
