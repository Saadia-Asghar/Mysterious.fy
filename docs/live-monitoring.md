# Live monitoring: from a real device to a ticket and back

This connects the portal to a running Zabbix so the NMS monitors devices without demo data.
Verified locally on 2026-11-26 with lab devices (see section 5).

```
Portal: add device ──► Zabbix host created (template "NMS ICMP device")
Zabbix pings every 30 s ──► trigger fires ──► webhook ──► NMS event
NMS timer (every N s) ──► correlate + RCA ──► incident ──► ticket to the device's team
Device answers again ──► Zabbix problem clears ──► recovery check ──► incident resolved ──► ticket resolved
```

## 1. Start Zabbix (once)

```powershell
docker compose -f docker/docker-compose.yml --env-file .env up -d zabbix-db zabbix-server zabbix-web
```

Zabbix web: http://localhost:8080. A fresh install uses Zabbix's documented default login; change the
Admin password in Zabbix right away. Put it in your local `.env` as `ZABBIX_ADMIN_PASSWORD` (never in
Git); if it is not set, the bootstrap asks for it.

## 2. Set Zabbix up for the NMS (once, safe to repeat)

```powershell
python scripts/zabbix_bootstrap.py
```

It creates, or updates if they exist:

| Object | Purpose |
|---|---|
| Template **NMS ICMP device** (group Templates/NMS) | ping, packet loss and response time every 30 s |
| Trigger "is unreachable" (high) | 3 failed pings in a row, or no ping result for 2 minutes (e.g. the name stops resolving) → `nms_event_type=device_unreachable` |
| Trigger "high packet loss" (warning) | > 20 % for 5 minutes → `high_packet_loss` |
| Trigger "high latency" (warning) | > 200 ms average for 5 minutes → `high_latency` |
| Media type **NMS Integration** | webhook to `http://host.docker.internal:8000/integrations/zabbix/events` |
| Global macro `{$NMS.WEBHOOK.TOKEN}` | shared secret checked by the API |
| Action **NMS: forward to integration** | sends every problem and recovery tagged `nms_event_type` |
| API token **nms-integration** | used by the API to create hosts and check problems |

It writes `NMS_ZABBIX_API_URL`, `NMS_ZABBIX_API_TOKEN`, `ZABBIX_API_TOKEN` and
`NMS_ZABBIX_WEBHOOK_TOKEN` into `.env` (git-ignored). A token that still works is kept, so
re-running does not break a running API.

## 3. Run the API with live sync

The API reads `.env` itself. Set in `.env`:

```
NMS_AUTO_SYNC_SECONDS=30      # background: correlate new events, verify fixes, close recovered incidents
NMS_PORTAL_SECRET=<long random value>   # so logins survive restarts
```

```powershell
python -m uvicorn app.main:app --app-dir integration-api --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is needed so the Zabbix container can reach the webhook.

## 4. Add devices

In the portal (http://localhost:8000/app) add each device with its **real IP address** (or DNS
name) as the management address. The device list shows a **Monitoring** column:

| Status | Meaning |
|---|---|
| monitored | Zabbix host exists and is being checked |
| paused | device disabled in the portal; host disabled in Zabbix |
| skipped | placeholder address (`<...>`), nothing to monitor |
| error | Zabbix call failed (hover for the reason); fix it and press **Sync to Zabbix** |
| off | this server has no Zabbix configured |

Zabbix hosts are named by device ID and grouped `NMS/<company>` and `NMS/<company>/<site>`,
with tags `nms_company`, `nms_site`, `nms_device_type`. A Zabbix error never blocks saving a device.

Set each device's **Responsible team** to a team name so its tickets are routed automatically.

## 5. Lab test without hardware

`docker/lab-devices.yml` starts three tiny containers on the Zabbix network:

```powershell
docker compose -f docker/lab-devices.yml up -d
```

Add them in the portal with addresses `lab-sw-1`, `lab-cam-1` (parent the switch), `lab-cam-2`
(parent the switch). Then:

```powershell
docker stop lab-sw-1 lab-cam-1 lab-cam-2   # switch outage
docker start lab-sw-1 lab-cam-1 lab-cam-2  # recovery
docker stop lab-cam-1                      # single camera failure
docker start lab-cam-1
```

Observed on 2026-11-26 (SIMULATED lab devices, timer 20 s, one run each; not a measured result):

| Scenario | What happened |
|---|---|
| Switch outage | 3 Zabbix problems → 1 incident with 3 devices, probable cause the switch → 1 ticket to the team; about 2–3 minutes from stop to ticket |
| Recovery | incident resolved by monitoring and ticket resolved "monitoring confirmed recovery" about 35 s after the devices answered again |
| Single camera | 1 incident, probable cause that camera, ticket to the team; closed about 20 s after it came back |

Detection takes about 2 minutes by design (3 pings or 2 minutes without data), so a single
lost ping does not wake anyone. Lower the trigger thresholds in the template if a site needs
faster alerts.

## 6. What happens to incidents

- Alerts arrive seconds apart. If the first sync sees only one camera and the next sees the
  switch too, the incident is **continued** (same ID, same ticket), not duplicated. The ticket
  title is updated and the change is recorded in its history.
- An incident closes on its own only when Zabbix reports **no open problem for every affected
  device**. Devices that Zabbix does not monitor (for example old demo data) are never assumed
  healthy, so their incidents stay open.
- Remediation still works as before: after an approved action the incident waits in
  `verifying` until Zabbix confirms recovery.

## 7. Known limits

- Natural recoveries are counted in MTTR (`/grafana/analytics/recovery`, column
  `recovered_by` = `itself` or `remediation`).
- Checks are ICMP only. Camera-specific checks (RTSP/ONVIF stream, recording status) need the
  camera and NVR models and Sir Khurram's approval.
- The webhook converts `{EVENT.DATE} {EVENT.TIME}` assuming the Zabbix server runs in UTC
  (true for the official image).
- Email alerts work when SMTP is set (see docs/ticketing-and-data.md section 6); no SMS yet.
