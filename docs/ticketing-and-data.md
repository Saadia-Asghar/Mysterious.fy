# Ticketing, teams, and company data

This covers how a company manages its own repair work in the portal, how every change is
tracked, and how we make sure no company data is lost. Code: `integration-api/app/ticketing.py`,
`integration-api/app/portal.py` (activity log), `scripts/backup_db.py`. Tests: `tests/test_ticketing.py`.

## 1. Who does what

| Role | Created by | Tickets | Teams | Reports and exports | Activity log |
|---|---|---|---|---|---|
| Super admin (NMS staff) | setup | all, any company | all | all, any company | every company |
| Admin (company) | NMS staff | all of the company: create, assign, change | create, set members, archive | yes | own company |
| Operator | NMS staff | all of the company: create, assign, change | read | reports only | no |
| Technician | NMS staff | only tickets assigned to them or to one of their teams: update status, add notes | read | no | no |
| Viewer | NMS staff | read only | read | reports only | no |

Logins are always created by NMS staff (see the platform admin). A company manages its own
teams and its own tickets.

## 2. Teams

A team is a named group of a company's users, for example `cctv-team` or `network`.

- Admins create teams and tick the members.
- Each device has a **Responsible team** field. When the name matches a team (case does not
  matter), tickets for incidents on that device go straight to that team.
- Teams are never deleted. **Archive** hides a team from new assignments; its old tickets keep
  the team name.

## 3. Tickets

### Where tickets come from

1. **Automatically from monitoring.** Every open incident on a company's devices gets exactly
   one ticket (an incident ID can never have two). Title, affected devices, and the probable
   cause come from the correlation and RCA results. Priority follows severity:
   disaster → urgent, high → high, average/warning → normal, others → low.
2. **By hand.** Any admin, operator or technician can open a ticket, optionally linked to a device.

### Life of a ticket

```
new ──assign──► assigned ──► in_progress ──► waiting ──► resolved ──► closed
 ▲                                                         │
 └──────────────────────── reopen ◄─────────────────────────┘
```

- Assigning a team or person to a `new` ticket moves it to `assigned`.
- Reopening clears the resolved time; the SLA clock keeps counting from the original start.
- For a ticket opened by monitoring: when Zabbix-based verification marks the incident
  **resolved**, the ticket is resolved by "NMS monitoring" with the reason
  "monitoring confirmed recovery". A person can mark the ticket resolved earlier, but the
  page warns that the incident itself stays open until monitoring sees the device healthy.
  A human click never closes an incident. This keeps the project rule that a reported fix
  is not proof of recovery.

### SLA timers

| Priority | Respond within | Fix within |
|---|---|---|
| Urgent | 15 minutes | 4 hours |
| High | 1 hour | 8 hours |
| Normal | 4 hours | 24 hours |
| Low | 8 hours | 72 hours |

- The clock starts when the incident started (monitoring tickets) or when the ticket was opened.
- **Response** = the first assignment, status change or note by anyone.
- **Overdue** = response or fix deadline passed while the ticket is still open.
- Changing priority recalculates both deadlines from the original start.

## 4. Tracking: who did what, when

Two records, both **append-only**. The database itself refuses any `UPDATE` or `DELETE`
on them (SQLite triggers), so not even a bug or a staff member can rewrite history.

| Record | Holds | Seen by |
|---|---|---|
| Ticket history (`ticket_events`) | every status, priority, team and assignee change (from → to), every note, monitoring's resolution | everyone who can see the ticket |
| Activity log (`audit_log`) | sites, devices (with a field-by-field diff), users, password resets, teams, tickets, data exports, company creation/suspension | company admins (own company) and NMS staff (all companies) |

Actions done by the system (monitoring, sync) are recorded as "NMS system" or "NMS monitoring".

## 5. No company data is lost

| Protection | How |
|---|---|
| Tickets are never deleted | database trigger blocks `DELETE` on `tickets`; close them instead |
| History cannot be changed | triggers block `UPDATE`/`DELETE` on `ticket_events` and `audit_log` |
| People are never deleted | removing a user only disables sign-in; their name stays on all past records |
| Teams are never deleted | archive only |
| Companies are never deleted | suspend only; all data stays |
| Sites with devices cannot be deleted | the API refuses until the devices are moved |
| Backups | `scripts/backup_db.py`: consistent online copy, integrity-checked, keeps newest N |
| Safe restore | restore first saves the current database as `<db>.before-restore-<time>` |

### Backups (do this on every real installation)

```powershell
python scripts/backup_db.py                                  # data/nms.sqlite -> backups/
python scripts/backup_db.py --db data/nms.sqlite --keep 30
python scripts/backup_db.py --restore backups/nms-20261126T020000Z.sqlite --db data/nms.sqlite
```

- Schedule it daily (Windows Task Scheduler or cron), for example at 02:00.
- Copy `backups/` to another machine or cloud storage. A backup on the same disk does not
  survive a disk failure.
- Test a restore once a month on a spare copy.
- `backups/` and `data/` are git-ignored. Never commit customer data.

## 6. The company benefits from its own data

**Reports & data** page (`GET /portal/reports/tickets?days=7|30|90|365`):

- tickets opened, resolved, open now, overdue now
- average hours to fix and % fixed within SLA
- how many tickets monitoring opened automatically
- the same numbers by team, by person and by priority (who is overloaded, who is fast)
- devices with the most tickets (what to replace first)

**Download your data (CSV)** (`GET /portal/export/{kind}.csv`, company admins):
`tickets`, `ticket_history`, `incidents`, `devices`, `sites`, `teams`, `audit`.
The company can open these in Excel, use them in its own reports, or take them if it leaves.
Every export is itself recorded in the activity log.

NMS staff see the same reports for any company (company selector) plus **All activity**
across all companies, which shows who is active, what changed, and where support is needed.

## 7. API summary

| Method and path | Purpose |
|---|---|
| `GET/POST /portal/teams` | list / create teams |
| `PUT /portal/teams/{id}/members` | set members |
| `POST /portal/teams/{id}/archive` | archive (never delete) |
| `GET /portal/tickets?view=open,mine,my_teams,unassigned,overdue,all` | ticket lists |
| `POST /portal/tickets` | open a ticket by hand |
| `GET /portal/tickets/{id}` | ticket with full history |
| `PATCH /portal/tickets/{id}` | status, priority, team, assignee, `unassign` |
| `POST /portal/tickets/{id}/comments` | add a note |
| `GET /portal/reports/tickets?days=N` | company report |
| `GET /portal/export/{kind}.csv` | data export |
| `GET /portal/audit` | company activity log |
| `GET /portal/admin/audit?organization_id=` | all activity (staff) |

All are scoped to the caller's company; NMS staff add `?organization_id=` to act on one company.

## 8. Relation to osTicket

osTicket stays an optional extra for customers who already use it: the M6 integration still
opens an osTicket ticket per incident when configured, and its number shows in the incidents
export (`external_ticket`). The portal tickets are the main place where a company's team works,
so ticketing works even when osTicket is not installed.

## 9. Known limits

- Times are shown in UTC.
- SLA hours are 24/7, not business hours.
- No email or SMS alert to the assignee yet (planned with notifications, phase 6).
- SQLite is fine for a pilot. Move to PostgreSQL before many companies use one server.
