# Product and Website Plan: Intelligent Generic NMS

Status: planning document. Nothing here is built yet unless marked **done**.
Cameras are the first device type. The product must work for any customer and any device type through configuration, not code changes.

---

## 1. What the product is

A company signs up, adds its sites, attaches any number of devices (cameras, switches, NVRs, UPS, routers, servers, sensors) and gets, from one website:

- live monitoring and uptime
- grouped incidents with a probable root cause
- tickets for humans
- controlled self-healing (only approved actions, always verified)
- analytics and monthly reports

The customer never installs or sees Zabbix, Grafana or osTicket. They are engines behind our portal.

---

## 2. Where everything is hosted

### 2.1 Deployment picture

```
CUSTOMER SITE                                   OUR CLOUD (one VM at first)
┌──────────────────────────────┐               ┌──────────────────────────────────────────┐
│ Cameras, switches, UPS, NVR  │               │ Caddy / Nginx (HTTPS, domain, routing)   │
│            │ LAN             │               │  ├─ app.<domain>  → Web frontend          │
│ Collector box                │  outbound     │  ├─ api.<domain>  → NMS API (FastAPI)     │
│  - Zabbix proxy              │ ─ TLS/VPN ──► │  ├─ dash.<domain> → Grafana (embedded)    │
│  - local buffer if offline   │               │  └─ osTicket (internal, behind API)       │
│  - remediation agent         │ ◄─ approved   │ Zabbix server + Zabbix web                │
│    (restart, PoE port cycle) │   actions     │ PostgreSQL (NMS DB, Zabbix DB)            │
└──────────────────────────────┘               │ MariaDB (osTicket)                        │
                                               │ Redis + worker (sweeps, reports, alerts)  │
                                               │ Backups → object storage                  │
                                               └──────────────────────────────────────────┘
```

### 2.2 Hosting stages

| Stage | Where | Size | Cost (approx.) | Use |
|---|---|---|---|---|
| FYP demo | Laptop, Docker Desktop | 16 GB RAM | free | Viva, demo data **(done)** |
| Pilot | One cloud VM (Hetzner / DigitalOcean / AWS Lightsail / local data centre) | 4 vCPU, 8 GB RAM, 160 GB SSD | USD 15–40 / month | 1–3 customers, up to ~1,000 devices |
| Startup | 2–3 VMs or managed Kubernetes, managed Postgres | grows with devices | USD 100+ / month | Many customers |
| On-premise option | Customer's own server (bank, government, Safe City type) | same Docker stack | licence + yearly support | Data must stay inside |

### 2.3 Everything needed

| Item | Why | Notes |
|---|---|---|
| Domain name | `app.`, `api.`, `dash.` subdomains | .pk or .com registrar |
| TLS certificates | HTTPS everywhere | Let's Encrypt, automatic via Caddy |
| Cloud VM | Runs the Docker stack | Ubuntu LTS + Docker Compose |
| Collector hardware | One per customer site | Raspberry Pi 5 / mini PC, or VM image on their server |
| Email (SMTP) | Alerts, invites, reports | transactional email service |
| SMS / WhatsApp gateway | Alerts to phones | local SMS provider or WhatsApp Business API |
| Object storage | Backups, report PDFs | daily DB backups, 30-day retention |
| External uptime check | Know when our own cloud is down | |
| Secrets management | Tokens, passwords | `.env` on server, never in git |
| Git + CI | Tests before deploy | GitHub, `dev` → `main` after approval |

---

## 3. Users and roles

| Role | Who | Permissions |
|---|---|---|
| Super Admin | Us (platform owner) | All companies, device profiles, playbooks, plans, billing |
| Company Admin | Customer IT head | Sites, devices, users, policies, approve fixes |
| Operator | Customer NOC staff | Dashboards, incidents, tickets, approve/reject fixes |
| Viewer | Management | Dashboards and reports only |

Every record carries `organization_id`; a user only sees their own organization, and can be limited to certain sites.

---

## 4. Data model

```
Organization (company)
 ├─ Users (role, allowed sites)
 ├─ Collectors (one per site, key, last_seen)
 └─ Sites
     └─ Zones
         └─ Devices
              ├─ device_type + Profile (metrics, thresholds, Zabbix template, allowed playbooks)
              ├─ Parent device (topology edge)
              ├─ Automation policy (monitor_only / recommend / require_approval / auto_remediate)
              └─ Telemetry, Events → Incidents → Tickets / Executions → Verifications
```

Already in the API **(done)**: devices with organization/site/zone/profile/policy, topology edges, events, incidents, tickets, executions, verifications, analytics feeds.
To add: organizations, users and roles, sites table, collectors, notification rules, PostgreSQL.

---

## 5. All pages

### 5.1 Public website

| Page | Content |
|---|---|
| Home | What it does, supported device types, screenshots, call to action |
| Features | Monitoring, RCA, self-healing, analytics, tickets |
| How it works | Collector → cloud → dashboard diagram |
| Pricing | Plans (section 8) |
| Use cases | CCTV, campus networks, retail chains, factories |
| Contact / Request demo | Form |
| Login, Sign up, Forgot password | Auth |

### 5.2 Customer app

| # | Page | What it shows / does |
|---|---|---|
| 1 | Overview | Devices up/down, open incidents, uptime %, MTTR, site map, latest incidents |
| 2 | Sites | List, add/edit site (name, address, map pin, contact) |
| 3 | Site detail | Devices at the site, collector status, site uptime |
| 4 | Devices | Table filtered by site, type, status; search; bulk actions |
| 5 | Add device wizard | Type → address and credentials → site/zone → parent device → policy → test connection → save |
| 6 | Bulk import | CSV/Excel upload with validation preview; IP-range auto-discovery |
| 7 | Device detail | Live graphs (ping, latency, loss, plus type-specific e.g. temperature, voltage, recording status), events, incidents, fixes, verifications |
| 8 | Topology | Tree/graph core → switches → devices, coloured by status, drag to set parent |
| 9 | Incidents | Grouped incidents, status, probable cause, affected count, age |
| 10 | Incident detail | Alert timeline, RCA ranking, ticket link, suggested playbook, Approve/Reject, verification result |
| 11 | Approvals queue | All fixes waiting for a human |
| 12 | Tickets | osTicket tickets, status, assignee, notes |
| 13 | Analytics | Alerts vs incidents per day, MTTR trend, top problem devices, causes by device type, per-site table, uptime |
| 14 | Reports | Monthly SLA/uptime PDF, scheduled email |
| 15 | Policies | Per device type or device: automatic vs approval |
| 16 | Notifications | Email/SMS/WhatsApp, who gets which severity, quiet hours, escalation |
| 17 | Collectors | Status per site, download installer, copy registration key |
| 18 | Users & roles | Invite, role, site access, disable |
| 19 | Audit log | Who approved what, which action ran, result |
| 20 | Billing | Plan, device count, invoices |
| 21 | Settings | Company name, logo (white label), time zone, API keys |
| 22 | My profile | Name, password, 2FA |

### 5.3 Super Admin panel

| Page | Purpose |
|---|---|
| Companies | All tenants, device counts, plan, status |
| Device profile builder | New device type: metrics, thresholds, Zabbix template, allowed playbooks. Available to every customer, no code change |
| Playbook library | Approved action types only; reviewed before release |
| Collectors (global) | Health of every collector |
| Plans & billing | Prices, invoices |
| System health | Zabbix, Grafana, osTicket, DB, queue status |

---

## 6. Workflows

### 6.1 New customer onboarding
1. Demo → organization created.
2. Site survey: devices, IPs, models, network layout.
3. Company Admin adds sites.
4. Collector installed at each site, registered with its key, shows **online**.
5. Devices added (wizard or CSV), each with profile, parent device and policy.
6. System creates Zabbix hosts through the proxy automatically.
7. Data appears on dashboards within minutes.
8. Users and notification rules set. Go live.

### 6.2 Add a device
Type → address and credentials → site/zone → parent → policy → **Test** (collector ping / SNMP / ONVIF) → save → Zabbix host created → first data shown.

### 6.3 Fault to resolution (core flow, already built in the API)
```
Device fails
→ Collector / Zabbix detects (ping, SNMP, trigger)
→ Event sent to NMS API, normalized
→ Anomaly check, correlation (upstream_anchor_quorum_v2), RCA (topology_time_v1)
→ One incident with a probable cause (not 20 separate alerts)
→ Policy decides:
     monitor_only     → shown only
     recommend        → shown with suggested fix
     require_approval → Approvals queue, operator approves
     auto_remediate   → approved playbook runs
   not fixable        → osTicket ticket to a human
→ Action runs through the collector agent
→ Zabbix re-checks health (verification)
     healthy                  → resolved, MTTR recorded
     unhealthy after timeout  → escalated + ticket note
→ Dashboards, analytics, reports update; notification sent
```

### 6.4 Human ticket flow
Ticket opened → technician notified → site visit / fix → monitoring confirms recovery → ticket closed with verification attached.

### 6.5 Monthly reporting
Scheduler builds uptime, incidents, MTTR and top problem devices per site → PDF → emailed to Company Admin and Viewers.

### 6.6 Adding a new device type (customization)
Super Admin defines a profile (e.g. UPS: battery %, input voltage, load, temperature; thresholds; template; allowed actions) → available to all customers → generic dashboards work through group/host variables.

---

## 7. Technology stack

| Layer | Choice | Status |
|---|---|---|
| Frontend | React / Next.js + Tailwind | to build |
| Backend | FastAPI integration API | **done** (core); add auth and tenants |
| Auth | JWT with roles; later SSO (Keycloak) shared with Grafana | to build |
| NMS database | SQLite now → PostgreSQL | to migrate |
| Intelligence | Anomaly, correlation v1/v2, RCA | **done** |
| Monitoring | Zabbix 7.0 server + proxy per site | compose written; proxy to add |
| Charts | Grafana 11.2 embedded, one org per company | **done** (dashboard + analytics) |
| Tickets | osTicket behind the API | integration **done** |
| Jobs | Worker for verification sweeps, reports, notifications | to build |
| Reverse proxy | Caddy or Nginx, HTTPS | to add |
| Deployment | Docker Compose on one VM | compose exists |

---

## 8. Pricing model (draft)

| Plan | Includes | Charge |
|---|---|---|
| Basic | Monitoring, dashboards, alerts | per device per month |
| Managed | Basic + tickets, reports, our NOC watching | higher per device |
| Self-healing | Managed + RCA, approved automatic fixes | premium |
| On-premise | Whole stack on customer server | licence + yearly support |
| Collector box | Configured hardware | one-time |

---

## 9. Security

- HTTPS only; collectors connect outbound only (no open ports at the customer)
- Passwords hashed; 2FA for admins
- Tenant isolation by `organization_id` on every query
- Device credentials encrypted at rest
- Only built-in, approved playbook actions; no free-form commands
- Full audit log of approvals and actions
- Daily backups with tested restore

---

## 10. Build plan

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Intelligence, API, Grafana dashboards, analytics, demo data | **done** |
| 1 | Login, roles, organizations, sites, device list/add/edit | next |
| 2 | Add device wizard, CSV import, topology page | |
| 3 | Incidents, incident detail, approvals queue (API exists) | |
| 4 | Analytics page (Grafana embedded), reports PDF | |
| 5 | Zabbix + proxy live, collector registration, real devices end to end | needs Zabbix running |
| 6 | Notifications (email/SMS/WhatsApp), audit log | |
| 7 | Cloud deploy: VM, domain, HTTPS, backups | pilot |
| 8 | Billing, white label, Super Admin profile builder | startup |

FYP demo target: phases 1–5 on one laptop or one VM, with one company, several sites and mixed device types.
