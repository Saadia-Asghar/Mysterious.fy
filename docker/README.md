# Docker

M1 core services: Zabbix (server, web, PostgreSQL), Grafana with the Zabbix plugin, osTicket (MariaDB), and the separate NMS PostgreSQL database.

## Prerequisites
Docker Desktop (Windows needs WSL2) or Docker Engine with Compose v2.

## Start
```bash
cp .env.example .env        # then replace every change_me
docker compose -f docker/docker-compose.yml --env-file .env up -d
docker compose -f docker/docker-compose.yml ps
```

| Service | URL | First login |
|---|---|---|
| Zabbix | http://localhost:8080 | Zabbix default `Admin` / `zabbix`, change it immediately |
| Grafana | http://localhost:3000 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |
| osTicket | http://localhost:8081 | `OSTICKET_ADMIN_EMAIL` / `OSTICKET_ADMIN_PASSWORD` |
| NMS DB | localhost:5433 | `NMS_DB_USER` / `NMS_DB_PASSWORD` |

After first Zabbix login create an API token (Users → API tokens), put it in `.env` as `ZABBIX_API_TOKEN`, then `docker compose ... up -d grafana`.

## Stop
```bash
docker compose -f docker/docker-compose.yml down        # keep data
docker compose -f docker/docker-compose.yml down -v     # delete data
```

## M1 acceptance (manual until verified)
1. All containers `running`/`healthy` in `ps`.
2. Zabbix UI loads and shows the server as running.
3. Grafana loads; the Zabbix data source "Save & test" succeeds.
4. osTicket staff panel loads.
5. `pg_isready` succeeds against nms-db.

Status: written, **not yet run** (no Docker on the first dev machine).
