# Part A: Step-by-step guide (from zero)

You do not need to know Zabbix, Docker or Python well. Follow the steps in order. Each step says **what you are doing, why, the exact thing to type, and how to know it worked**. If something fails, go to the table in step 16.

How to read the boxes:

* `Terminal 1/2/3` means separate terminal windows that stay open. Keep them open.
* Commands are written for **Windows PowerShell**, with the Linux/macOS difference shown only where it differs.
* "Repository root" means the folder that contains `README.md`, `docker/`, `integration-api/`.

---

## Step 0. Understand what you are building (5 minutes)

```
camera / switch / test service ──► Zabbix (watches them) ──► webhook ──► Integration API (decides)
                                                                              │
                              Zabbix confirms it is fixed ◄── runs approved fix ◄┘   or → ticket for a human
```

Your job (Part A) is everything on the left and the "decide and fix" loop. You are **not** building dashboards (Saadia) or osTicket (Part B). Read `docs/part-a/PRD.md` once (10 minutes) so the words match.

Three words you will see:

| Word | Meaning |
|---|---|
| **Profile** | A file in `device-profiles/` describing a kind of device (what it measures, what problems exist, what fixes are allowed). |
| **Template** | The Zabbix side of a profile: `monitoring-zabbix/templates/<profile>.json`. |
| **Policy** | Per device: `monitor_only`, `recommend`, `require_approval` or `auto_remediate`. Decides whether a fix may run. |

---

## Step 1. Install the tools

| Tool | Why | Check it worked |
|---|---|---|
| **Python 3.11 or newer** (python.org; tick "Add to PATH") | Runs the API, the script, the tests | `python --version` |
| **Git** | Share code with the team | `git --version` |
| **Docker Desktop** | Runs Zabbix | `docker --version` and `docker compose version` |
| **Cursor** (or another AI editor) | Writes and fixes code for you | opens |

**Docker needs hardware virtualization.** Your team notes say the first dev machine had none. If Docker Desktop says "virtualization is disabled": restart, enter BIOS/UEFI (usually F2, Del or F10), enable *Intel VT-x / AMD-V (SVM)*, and in Windows enable "Virtual Machine Platform" and "WSL2" (`wsl --install` in an Administrator PowerShell, then restart). If this machine cannot do it, use another machine for Docker or a Linux VM. **Nothing in Part A can be demonstrated without Zabbix running.**

---

## Step 2. Get the code

**Option A (simplest): work from this zip.**

1. Unzip `nms-part-a-kit.zip`. You get a folder `nms-part-a-kit/`. This is your repository root.
2. Open that folder in Cursor (File → Open Folder).

**Option B: work inside the team repository (needed to hand your work in).**

```powershell
git clone --branch dev https://github.com/Saadia-Asghar/Mysterious.fy.git nms-fyp
cd nms-fyp
git checkout -b feature/part-a-zabbix
```

Then copy the files below from the kit into the clone, keeping the same folders, and open the clone in Cursor. **Do not copy** `README.md`, `docs/README.md`, `visualization-grafana/`, `test-environment/fault-scenarios/README.md` and `scripts/`: the team repository has its own, fuller versions.

New files to copy:
`monitoring-zabbix/provision.py`, `monitoring-zabbix/templates/` (3 files), `monitoring-zabbix/inventory.example.json`, `monitoring-zabbix/inventory.camera.example.json`, `tests/test_zabbix_provision.py`, `tests/test_automation.py`, `docs/part-a/` (3 files), `.cursor/rules/nms-part-a.mdc`.

Changed files to copy over the team's (compare first with `git diff` if a teammate also edited them):
`integration-api/app/main.py`, `schemas.py`, `settings.py`, `zabbix_api.py`, `integration-api/requirements.txt`, `integration-api/README.md`, `monitoring-zabbix/README.md`, `monitoring-zabbix/media-types/nms_webhook.js`, `docker/docker-compose.yml`, `docker/README.md`, `remediation-playbooks/README.md`, `test-environment/simulators/test_service.py`, `tests/test_compose.py`, `.env.example`, `.gitignore`, `pytest.ini`.

In the team repository the tests for Grafana and evaluation also exist; they must still pass.

---

## Step 3. Python environment and the first test run

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r integration-api/requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Linux/macOS: `source .venv/bin/activate` instead of the Activate line.

If PowerShell refuses to run the Activate script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again.

**Expected:** `139 passed` (the team repository shows more, because of Grafana and evaluation tests). If the numbers differ slightly, any `failed` is the problem, not the count. **Why this matters:** it proves the code you were handed works on your machine before you touch anything.

Every later command assumes the `(.venv)` prefix is showing in your terminal. If you open a new terminal, activate again.

---

## Step 4. Create your `.env` (settings and passwords)

```powershell
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Open `.env` and replace **every** `change_me` with your own passwords (anything, but not `change_me`). Leave `NMS_ZABBIX_API_TOKEN` and `ZABBIX_API_TOKEN` as `change_me` for now: you get that token in step 6.

Also set one extra value now, because the API will be reachable from Docker:

```
NMS_ZABBIX_WEBHOOK_TOKEN=pick-a-long-random-word-here
```

`.env` is in `.gitignore`. **Never commit it.**

---

## Step 5. Start Zabbix

**Terminal 1** (repository root). Start only what Part A needs:

```powershell
docker compose -f docker/docker-compose.yml --env-file .env up -d zabbix-db zabbix-server zabbix-web
docker compose -f docker/docker-compose.yml ps
```

The first time, Docker downloads images (a few minutes). Wait until all three show `running` (the database `healthy`).

Open http://localhost:8080. Log in with **Admin / zabbix**. **Change the password now:** top-left user icon → User settings → Change password.

**Expected:** the Zabbix dashboard. Check **Reports → System information**: "Zabbix server is running: Yes".

If the web page shows a database error, wait one more minute and refresh: the server is still preparing the database. See step 16 if it stays broken.

---

## Step 6. Create the Zabbix API token

The scripts talk to Zabbix through its API and need a key.

1. In Zabbix: **Users → API tokens → Create API token**.
2. Name `nms`, user `Admin`, no expiry (or a far date). Click **Add**.
3. **Copy the token now** (it is shown once).
4. Paste it into `.env` as **both** `NMS_ZABBIX_API_TOKEN=` and `ZABBIX_API_TOKEN=`.

---

## Step 7. Start the Integration API

**Terminal 2:**

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir integration-api --env-file .env --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is needed so Zabbix (in Docker) can reach it. Windows may ask to allow Python through the firewall: allow it on **private** networks only.

**Expected:** `Uvicorn running on http://0.0.0.0:8000`. Open http://127.0.0.1:8000/docs: a page listing the API. Open http://127.0.0.1:8000/health: `{"status":"ok"...}`.

Leave it running. (Close with Ctrl+C when you are finished for the day.)

---

## Step 8. Run `setup` (create templates, webhook and action in Zabbix)

**Terminal 3** (repository root, venv active):

```powershell
python monitoring-zabbix/provision.py setup
```

**Expected output** (order may vary):

```
template NMS_ip_camera_basic: created
  item icmpping: created
  ...
  trigger device_unreachable: created
...
media type NMS Integration: created
user Admin: media NMS Integration added
action 'NMS: send events to the integration API': created
```

**Check in the Zabbix web page** (this is your first real proof):

| Where | You should see |
|---|---|
| Data collection → Templates, search `NMS` | three templates |
| Open `NMS_ip_camera_basic` → Items | `ICMP ping`, `ICMP response time`, `ICMP loss` |
| …→ Triggers | three triggers with tag `nms_event_type` |
| Alerts → Media types | `NMS Integration`, type Webhook |
| Users → Users → Admin → Media | `NMS Integration` |
| Alerts → Actions → Trigger actions | `NMS: send events to the integration API` |

**If it prints `error: ...`:** this is the most likely place for a surprise, because the script was tested against a *fake* Zabbix. Copy the full error text and the template/object it was creating into Cursor with **prompt P3** from the prompts file. The error names the Zabbix API method and field that Zabbix rejected; the fix is usually one field in `provision.py` or one template JSON. Run `setup` again afterwards: it continues from where it stopped and does not duplicate.

Running `setup` twice is safe.

---

## Step 9. Start the lab test service and onboard it

The test service is a safe, fake "device" that can be broken and restarted on purpose.

**Terminal 4:**

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn test_service:app --app-dir test-environment/simulators --host 0.0.0.0 --port 9100
```

Check http://127.0.0.1:9100/health → `{"healthy":true,"restarts":0}`.

**Terminal 3:** create your inventory from the example and onboard it.

```powershell
copy monitoring-zabbix\inventory.example.json monitoring-zabbix\inventory.json
python monitoring-zabbix/provision.py onboard
```

**Expected:**

```
SVC-001: registered in the integration API
SVC-001: Zabbix host created
```

**Why two addresses:** `management_address` (`http://127.0.0.1:9100`) is how the API reaches the service. `monitoring_address` (`http://host.docker.internal:9100`) is how Zabbix, inside Docker, reaches the same service. Inside Docker, `127.0.0.1` means the container itself.

**Check:**

1. http://127.0.0.1:8000/devices lists `SVC-001`.
2. Zabbix → **Monitoring → Hosts**: `Lab test service` appears (give it about a minute to turn green).
3. Zabbix → **Monitoring → Latest data**, host `Lab test service`: `Health endpoint HTTP status` = **200**.

If the item is *Not supported* (red/grey icon, hover for the reason), see step 16.

---

## Step 10. First real problem: break the service and watch it travel

1. Break it (Terminal 3):

   ```powershell
   curl.exe -X POST http://127.0.0.1:9100/fault/break
   ```
   (Linux/macOS: `curl -X POST ...`)

2. Within about a minute: Zabbix **Monitoring → Problems** shows `Lab test service: health check failing`.
3. Zabbix **Reports → Action log** shows the webhook with status **Sent**. If it shows **Failed**, hover over the error: see step 16.
4. Open http://127.0.0.1:8000/events: an event with `"source": "zabbix"`, `"event_type": "service_down"`, `"device_id": "SVC-001"`.

**Why it matters:** this proves Zabbix → webhook → API works end to end, which is the heart of Part A.

---

## Step 11. Policy demos (the part your supervisor will want to see)

Run one cycle by hand (it can also run on a timer, see 11e):

```powershell
curl.exe -X POST http://127.0.0.1:8000/automation/run
```

The response lists `sync`, `remediations`, `verifications`, `errors`.

### 11a. `require_approval` (the default for the test service)

After the run above, `GET http://127.0.0.1:8000/executions` shows one execution `status: "pending"`, and the incident is `action_pending`. Nothing was restarted. Approve it (use the real `execution_id` from the list):

```powershell
curl.exe -X POST http://127.0.0.1:8000/executions/EXECUTION_ID/approve -H "Content-Type: application/json" -d "{\"approved_by\": \"your-name\"}"
```

(Windows tip: quotes inside `-d` need the backslashes as shown.) Run the cycle again:

```powershell
curl.exe -X POST http://127.0.0.1:8000/automation/run
```

**Expected:** the service restarts (`/health` is healthy again), then Zabbix confirms recovery and the incident becomes `resolved`. Check `GET /incidents`, `GET /verifications` (source `zabbix`).

### 11b. `auto_remediate` (no approval)

Stop and reset: `curl.exe -X POST http://127.0.0.1:9100/fault/clear`. In `monitoring-zabbix/inventory.json` change `"automation_policy"` to `"auto_remediate"` and use a **new** device id (for example `SVC-002`), because an already-registered device is not changed by `onboard`. Run `onboard`, then break it again (`/fault/break`, the simulator is shared, so use one device at a time) and run the cycle after the problem appears. **Expected:** restart runs without waiting, incident goes to `resolved`.

### 11c. Failed recovery → ticket

```powershell
curl.exe -X POST http://127.0.0.1:9100/fault/stuck
curl.exe -X POST http://127.0.0.1:9100/fault/break
```

Run the cycle once the problem appears: restart runs, health stays bad, incident `verifying`. Wait `NMS_VERIFY_TIMEOUT_SECONDS` (default 300 s; set a smaller number such as 60 in `.env` and restart the API for demos) and run the cycle again: incident `escalated`. A ticket is opened if osTicket is configured (Part B); otherwise the response says so.

### 11d. `monitor_only` and `recommend`

Onboard a device with these policies: the cycle records an execution with `rejected_by_policy` and runs nothing. That record is your evidence that the safety policy works.

### 11e. Run automatically

Put `NMS_AUTOMATION_INTERVAL_SECONDS=30` in `.env`, restart the API (Terminal 2: Ctrl+C, then the same command). The cycle now runs every 30 s with no manual calls.

---

## Step 12. Onboard a real or simulated camera and switch (ICMP)

You need an **authorized** IP address for a camera or switch. If you have none yet, use the address of any device you own (a phone on your Wi-Fi, a router) as a stand-in and say so in your report.

1. `copy monitoring-zabbix\inventory.camera.example.json monitoring-zabbix\inventory.json`
2. Replace both `<authorized-address>` values with real addresses (an IP like `192.168.1.20` or a host name). Do not commit this file.
3. `python monitoring-zabbix/provision.py onboard`
4. Zabbix **Latest data** for `Lab camera 1`: `ICMP ping` = 1, `ICMP response time` small, `ICMP loss` = 0.
5. Fault test: unplug/power off the device. After 3 missed pings (about 3 minutes) one problem `Lab camera 1 is unreachable` appears; the event arrives at `GET /events`. Plug it back: Zabbix recovers.

Because the camera is `monitor_only`, the cycle takes **no action** on it: the event waits for a human ticket. That is correct and is what the plan says.

**If Zabbix cannot ping from Docker** (`ICMP ping` stays 0 though the device answers from your PC): Docker Desktop may block ICMP to your LAN. Test with `docker exec -it $(docker compose -f docker/docker-compose.yml ps -q zabbix-server) fping 192.168.1.20`. If that fails, run Docker on a Linux machine, or use prompt P7.

---

## Step 13. Latency and packet-loss checks

1. On a Linux test host or router: add delay or loss to the monitored device's link (for example `tc qdisc add dev eth0 root netem delay 200ms`), or use a real bad cable.
2. Expect `high_latency` after the 5-minute average passes `{$NMS.LATENCY.MAX_MS}`; `high_packet_loss` likewise.
3. Remove the fault: both clear.

Record for each parameter: fault, time it was caused, time the alert appeared, time it cleared. **Thresholds are provisional**: ask your supervisor for the agreed values, then edit the two macro values in `templates/ip_camera_basic.json` and `templates/network_switch_basic.json`, delete the templates in Zabbix (Data collection → Templates), and run `setup` again.

---

## Step 14. Show it in Grafana (with Saadia)

1. Make sure `ZABBIX_API_TOKEN` in `.env` is the token from step 6.
2. `docker compose -f docker/docker-compose.yml --env-file .env up -d grafana`
3. http://localhost:3000 (admin / your `GRAFANA_ADMIN_PASSWORD`) → Dashboards → NMS operations. Your hosts are in host group `NMS/LAB/LAB-SITE`.

Tell Saadia the facts she needs: item names `ICMP ping`, `ICMP response time` (seconds) and `ICMP loss`; host groups `NMS/<organization>/<site>`; host tags `nms_organization`, `nms_site`, `nms_zone`, `nms_profile`.

---

## Step 15. Adding a new device type later (shows it is generic)

1. Add `device-profiles/<new_profile>.json` (copy a similar one).
2. Add `monitoring-zabbix/templates/<new_profile>.json` (copy a similar one). Use only metric names and trigger names the profile declares.
3. `python -m pytest`: the contract tests tell you if you missed something.
4. `python monitoring-zabbix/provision.py setup`, add the device to `inventory.json`, `onboard`.
No Python code changes. That is the proof for "generic NMS".

---

## Step 16. When something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `error: Set NMS_ZABBIX_API_TOKEN in .env` | Token missing or still `change_me` | Step 6 |
| `error: ... Connection refused` for Zabbix | Zabbix not up, or wrong URL | `docker compose ... ps`; `NMS_ZABBIX_API_URL=http://localhost:8080/api_jsonrpc.php` |
| `error: Zabbix API error ... Invalid parameter ...` | Real Zabbix rejected a call | Prompt P3 with the full message |
| `error: ... not a usable address` | Placeholder still in inventory | Put a real IP/host name |
| `error: ... integration API returned 422` on onboard | A field is wrong in the inventory (for example an unknown `automation_policy`) | Read the message; valid policies are the four above |
| `error: ...Connection refused` on onboard to the API | API not running (step 7) or `--nms-url` wrong | Start it |
| Item `Health endpoint HTTP status` not supported | Zabbix cannot reach `host.docker.internal:9100` | Test service must run with `--host 0.0.0.0`; check firewall; `docker exec <zabbix-server> wget -S -O- http://host.docker.internal:9100/health` |
| Problem appears, no event at `GET /events` | Webhook failed or no media on Admin | Zabbix Reports → Action log: read the error. 401 = token mismatch (`NMS_ZABBIX_WEBHOOK_TOKEN` in `.env` and re-run `setup`); 422 = see the error text, use prompt P4; "connection refused" = API started without `--host 0.0.0.0` |
| Action log shows no entry at all | Action disabled or condition not met | Alerts → Actions: enabled? Trigger has tag `nms_event_type`? |
| Event arrives with HTTP 422 `not declared on profile` | Trigger tag value is not in the profile's `triggers` | Make template and profile match (a test normally prevents this) |
| After restart, incident stays `verifying` | Zabbix still shows a problem (item interval 30 s) | Wait one or two polls and run the cycle again |
| Cycle `errors` contains an incident id | Zabbix API unreachable during verification | Check token and URL; the incident stays `verifying` |
| `docker compose` cannot find `.env` values | Command run outside the repository root | `cd` to the root |
| Windows firewall popup ignored → Zabbix cannot reach the API | Blocked inbound | Allow Python on private networks |

---

## Step 17. Commit and hand in

```powershell
python -m pytest
ruff check --select F .
git status
git add -A
git commit -m "Part A: Zabbix provisioning, onboarding, automation cycle"
git push -u origin feature/part-a-zabbix
```

Open a pull request into `dev` and tell the team. **Before you commit check that `git status` does not list `.env`, `monitoring-zabbix/inventory.json`, or `data/`.** If it does, stop and ask.

(`ruff` is a checker for unused code: `pip install ruff` once. It must print `All checks passed!`.)

---

## Step 18. Final checklist (maps to PRD §8)

Tick each one and keep a screenshot or copied output as evidence for your report.

- [ ] 1. `pytest` all green
- [ ] 2. `setup` ran; objects visible in Zabbix
- [ ] 3. Test service host shows status 200 in Latest data
- [ ] 4. Break → problem in Zabbix → event in `/events`
- [ ] 5. `require_approval`: pending → approved → restarted → `resolved`
- [ ] 6. `auto_remediate`: resolved without approval
- [ ] 7. `stuck`: escalated after timeout (ticket if Part B is ready)
- [ ] 8. `monitor_only` / `recommend`: blocked record, nothing run
- [ ] 9. Camera or switch offline → one `device_unreachable`; recovery
- [ ] 10. Grafana shows your hosts
- [ ] 11. Each ICMP parameter: fault, alert, clear recorded
- [ ] 12. Open questions sent to supervisor: camera model, switch model, NVR, thresholds

When all are ticked, Part A is complete.
