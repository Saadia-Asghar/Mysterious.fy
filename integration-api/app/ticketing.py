"""Company ticketing: teams, tickets, assignment, SLA timers, full history, reports and exports.

Rules (see docs/ticketing-and-data.md):
- Tickets and their history are never deleted. Every change is an append-only ticket event.
- An open incident on a company's devices automatically gets one ticket, routed to the team
  whose name matches the device's responsible_team (otherwise left unassigned).
- When monitoring (Zabbix-based verification) marks the incident resolved, its ticket is
  resolved by "NMS monitoring". People can mark a ticket resolved too, but the incident
  itself stays open until monitoring confirms recovery.
- Technicians see only tickets assigned to them or to their teams.
"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

Priority = Literal["low", "normal", "high", "urgent"]
Status = Literal["new", "assigned", "in_progress", "waiting", "resolved", "closed"]
OPEN_TICKET = ("new", "assigned", "in_progress", "waiting")
OPEN_INCIDENT = {"open", "action_pending", "verifying", "escalated"}
# (respond within, resolve within) per priority
SLA = {"urgent": (timedelta(minutes=15), timedelta(hours=4)),
       "high": (timedelta(hours=1), timedelta(hours=8)),
       "normal": (timedelta(hours=4), timedelta(hours=24)),
       "low": (timedelta(hours=8), timedelta(hours=72))}
SEVERITY_PRIORITY = {"disaster": "urgent", "high": "high", "average": "normal", "warning": "normal"}
MANAGERS = {"super_admin", "admin", "operator"}  # may assign and edit any ticket of the company
TEAM_ADMINS = {"super_admin", "admin"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""


class Team(TeamIn):
    team_id: int
    active: bool
    members: list[dict] = []


class MembersIn(BaseModel):
    user_ids: list[int]


class TicketIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    priority: Priority = "normal"
    device_id: str | None = None
    team_id: int | None = None
    assignee_id: int | None = None


class TicketUpdate(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    team_id: int | None = None
    assignee_id: int | None = None
    unassign: bool = False


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class TicketEvent(BaseModel):
    event_id: int
    actor_name: str
    kind: str
    detail: dict
    created_at: str


class Ticket(BaseModel):
    ticket_id: int
    organization_id: str
    title: str
    description: str
    priority: Priority
    status: Status
    source: Literal["manual", "incident"]
    team_id: int | None
    team_name: str | None
    assignee_id: int | None
    assignee_name: str | None
    device_id: str | None
    incident_id: str | None
    incident_status: str | None
    created_by: str
    created_at: str
    updated_at: str
    first_response_at: str | None
    resolved_at: str | None
    response_due: str
    resolve_due: str
    response_breached: bool
    resolve_breached: bool
    history: list[TicketEvent] = []


def register(router: APIRouter, store, portal, current_user, org_scope, org_devices, notifier=None):
    """Add the ticketing routes. Returns sync_all(), which opens/resolves incident tickets for
    every active company, so the background loop can run it without anyone opening the portal."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    with store._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE (organization_id, name)
            );
            CREATE TABLE IF NOT EXISTS team_members (
                team_id INTEGER NOT NULL REFERENCES teams(team_id),
                user_id INTEGER NOT NULL,
                PRIMARY KEY (team_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                team_id INTEGER,
                assignee_id INTEGER,
                device_id TEXT,
                incident_id TEXT UNIQUE,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                first_response_at TEXT,
                resolved_at TEXT,
                response_due TEXT NOT NULL,
                resolve_due TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tickets_org ON tickets(organization_id, status);
            CREATE TABLE IF NOT EXISTS ticket_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(ticket_id),
                organization_id TEXT NOT NULL,
                actor_id INTEGER,
                actor_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS ticket_events_no_update BEFORE UPDATE ON ticket_events
                BEGIN SELECT RAISE(ABORT, 'ticket history is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS ticket_events_no_delete BEFORE DELETE ON ticket_events
                BEGIN SELECT RAISE(ABORT, 'ticket history is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS tickets_no_delete BEFORE DELETE ON tickets
                BEGIN SELECT RAISE(ABORT, 'tickets are never deleted; close them instead'); END;
            """
        )

    # ---------- helpers ----------
    def q(sql, params=()):
        return portal._all(sql, params)

    def user_names(org_id: str) -> dict[int, str]:
        return {r["user_id"]: r["full_name"]
                for r in q("SELECT user_id, full_name FROM users WHERE organization_id=?", (org_id,))}

    def team_of(org_id: str, team_id: int | None):
        if team_id is None:
            return None
        rows = q("SELECT * FROM teams WHERE team_id=? AND organization_id=? AND active=1", (team_id, org_id))
        if not rows:
            raise HTTPException(status_code=422, detail="Unknown team")
        return rows[0]

    def check_assignee(org_id: str, user_id: int | None) -> None:
        if user_id is None:
            return
        u = portal.get_user(user_id)
        if u is None or u.organization_id != org_id or u.role == "viewer":
            raise HTTPException(status_code=422, detail="Assignee must be an active, non-viewer user of this company")

    def my_team_ids(user) -> set[int]:
        return {r["team_id"] for r in q("SELECT team_id FROM team_members WHERE user_id=?", (user.user_id,))}

    def log(ticket_id: int, org_id: str, actor, kind: str, detail: dict) -> None:
        portal._exec("INSERT INTO ticket_events (ticket_id, organization_id, actor_id, actor_name, kind, detail, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (ticket_id, org_id, getattr(actor, "user_id", None), getattr(actor, "full_name", "NMS monitoring"),
                      kind, json.dumps(detail), iso(utcnow())))
        alert(ticket_id, org_id, actor, kind, detail)

    def recipients(row, actor) -> list[str]:
        """The assignee if there is one, otherwise every active member of the ticket's team.
        The person who made the change is not emailed about it."""
        if row["assignee_id"]:
            ids = [row["assignee_id"]]
        elif row["team_id"]:
            ids = [r["user_id"] for r in q("SELECT user_id FROM team_members WHERE team_id=?", (row["team_id"],))]
        else:
            return []
        me = getattr(actor, "user_id", None)
        marks = ",".join("?" * len(ids))
        return [r["email"] for r in q(f"SELECT user_id, email FROM users WHERE active=1 AND user_id IN ({marks})", tuple(ids))
                if r["user_id"] != me]

    def alert(ticket_id: int, org_id: str, actor, kind: str, detail: dict) -> None:
        if notifier is None:
            return
        if kind == "status" and detail.get("to") not in ("resolved", "closed"):
            return
        if kind not in ("created", "assignee", "team", "status"):
            return
        row = q("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,))[0]
        what = {"created": "New ticket", "assignee": "Ticket assigned to you", "team": "Ticket assigned to your team",
                "status": f"Ticket {detail.get('to')}"}[kind]
        lines = [f"{what}: T-{ticket_id} {row['title']}",
                 f"Priority: {row['priority']}    Status: {row['status']}",
                 f"Device: {row['device_id'] or '-'}    Incident: {row['incident_id'] or '-'}",
                 f"Respond by: {row['response_due']}    Resolve by: {row['resolve_due']}"]
        if detail.get("reason"):
            lines.append(f"Reason: {detail['reason']}")
        lines.append(f"By: {getattr(actor, 'full_name', 'NMS monitoring')}")
        notifier.queue(org_id, ticket_id, recipients(row, actor),
                       f"[NMS {row['priority'].upper()}] {what}: T-{ticket_id} {row['title']}"[:200], "\n".join(lines))

    def to_ticket(r, names, teams, incidents, with_history=False) -> Ticket:
        now = utcnow()
        end = datetime.fromisoformat(r["resolved_at"]) if r["resolved_at"] else now
        first = datetime.fromisoformat(r["first_response_at"]) if r["first_response_at"] else now
        hist = []
        if with_history:
            hist = [TicketEvent(event_id=e["event_id"], actor_name=e["actor_name"], kind=e["kind"],
                                detail=json.loads(e["detail"]), created_at=e["created_at"])
                    for e in q("SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY event_id", (r["ticket_id"],))]
        return Ticket(
            ticket_id=r["ticket_id"], organization_id=r["organization_id"], title=r["title"], description=r["description"],
            priority=r["priority"], status=r["status"], source=r["source"], team_id=r["team_id"],
            team_name=teams.get(r["team_id"]), assignee_id=r["assignee_id"], assignee_name=names.get(r["assignee_id"]),
            device_id=r["device_id"], incident_id=r["incident_id"], incident_status=incidents.get(r["incident_id"]),
            created_by=r["created_by"], created_at=r["created_at"], updated_at=r["updated_at"],
            first_response_at=r["first_response_at"], resolved_at=r["resolved_at"],
            response_due=r["response_due"], resolve_due=r["resolve_due"],
            response_breached=first > datetime.fromisoformat(r["response_due"]),
            resolve_breached=end > datetime.fromisoformat(r["resolve_due"]),
            history=hist)

    def context(org_id: str):
        teams = {r["team_id"]: r["name"] for r in q("SELECT team_id, name FROM teams WHERE organization_id=?", (org_id,))}
        incidents = {i.incident_id: i.status for i in store.list_incidents()}
        return user_names(org_id), teams, incidents

    def insert_ticket(org_id: str, actor, title: str, description: str, priority: str, source: str,
                      device_id=None, incident_id=None, team_id=None, assignee_id=None, created_at=None) -> int:
        start = created_at or utcnow()
        respond, resolve = SLA[priority]
        status = "assigned" if (team_id or assignee_id) else "new"
        tid = portal._exec(
            "INSERT INTO tickets (organization_id, title, description, priority, status, source, team_id, assignee_id,"
            " device_id, incident_id, created_by, created_at, updated_at, response_due, resolve_due)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, title, description, priority, status, source, team_id, assignee_id, device_id, incident_id,
             getattr(actor, "full_name", "NMS monitoring"), iso(start), iso(utcnow()),
             iso(start + respond), iso(start + resolve)))
        log(tid, org_id, actor, "created", {"priority": priority, "source": source, "team_id": team_id,
                                            "assignee_id": assignee_id, "device_id": device_id, "incident_id": incident_id})
        return tid

    def sync_incidents(org_id: str) -> None:
        """One ticket per open incident on this company's devices; resolve a ticket once monitoring
        has confirmed its incident resolved. Idempotent: safe to run on every read."""
        devices = {d.device_id: d for d in org_devices(org_id)}
        if not devices:
            return
        teams_by_name = {r["name"].lower(): r["team_id"]
                         for r in q("SELECT team_id, name FROM teams WHERE organization_id=? AND active=1", (org_id,))}
        existing = {r["incident_id"]: r for r in q(
            "SELECT ticket_id, incident_id, status, title FROM tickets WHERE organization_id=? AND incident_id IS NOT NULL",
            (org_id,))}
        for inc in store.list_incidents():
            mine = [d for d in inc.affected_devices if d in devices]
            if not mine:
                continue
            causes = [c.device_id for c in inc.rca.ranked_causes if c.device_id in devices]
            cause = causes[0] if causes else mine[0]
            title = f"{inc.incident_id}: {len(inc.affected_devices)} device(s) affected, probable cause {cause}"
            description = (f"Opened automatically from monitoring. Affected: {', '.join(inc.affected_devices)}. "
                           f"Correlation: {inc.correlation.reason}")
            t = existing.get(inc.incident_id)
            if t is None and inc.status in OPEN_INCIDENT:
                dev = devices[cause]
                created = inc.created_at if inc.created_at.tzinfo else inc.created_at.replace(tzinfo=timezone.utc)
                tid = insert_ticket(
                    org_id, None, title, description, SEVERITY_PRIORITY.get(inc.severity, "low"), "incident",
                    device_id=dev.device_id, incident_id=inc.incident_id,
                    team_id=teams_by_name.get(dev.responsible_team.lower()), created_at=created)
                portal.audit(org_id, None, "ticket.opened_from_incident", f"T-{tid}", inc.incident_id)
            elif t is not None and t["status"] in OPEN_TICKET and t["title"] != title:
                # Later alerts widened the incident (e.g. the switch behind the camera): keep the
                # ticket in step and say so in its history.
                portal._exec("UPDATE tickets SET title=?, description=?, device_id=?, updated_at=? WHERE ticket_id=?",
                             (title, description, cause, iso(utcnow()), t["ticket_id"]))
                log(t["ticket_id"], org_id, None, "details",
                    {"from": t["title"], "to": title, "reason": "monitoring added related alerts"})
            if t is not None and inc.status == "resolved" and t["status"] in OPEN_TICKET:
                ts = iso(utcnow())
                portal._exec("UPDATE tickets SET status='resolved', resolved_at=?, updated_at=?,"
                             " first_response_at=COALESCE(first_response_at, ?) WHERE ticket_id=?",
                             (ts, ts, ts, t["ticket_id"]))
                log(t["ticket_id"], org_id, None, "status", {"from": t["status"], "to": "resolved",
                                                             "reason": "monitoring confirmed recovery"})

    def visible(row, user) -> bool:
        if user.role != "technician":
            return True
        return row["assignee_id"] == user.user_id or row["team_id"] in my_team_ids(user)

    def load(org_id: str, ticket_id: int, user) -> Ticket:
        rows = q("SELECT * FROM tickets WHERE ticket_id=? AND organization_id=?", (ticket_id, org_id))
        if not rows or not visible(rows[0], user):
            raise HTTPException(status_code=404, detail="Unknown ticket")
        return to_ticket(rows[0], *context(org_id), with_history=True)

    def can_work(user) -> None:
        if user.role == "viewer":
            raise HTTPException(status_code=403, detail="Viewers cannot change tickets")

    def need_team_admin(user) -> None:
        if user.role not in TEAM_ADMINS:
            raise HTTPException(status_code=403, detail="Admin role required")

    # ---------- teams ----------
    @router.get("/teams", response_model=list[Team])
    def list_teams(scope=Depends(org_scope)) -> list[Team]:
        org_id = scope[1]
        names = user_names(org_id)
        out = []
        for r in q("SELECT * FROM teams WHERE organization_id=? ORDER BY active DESC, name", (org_id,)):
            members = [{"user_id": m["user_id"], "full_name": names.get(m["user_id"], "?")}
                       for m in q("SELECT user_id FROM team_members WHERE team_id=?", (r["team_id"],))]
            out.append(Team(team_id=r["team_id"], name=r["name"], description=r["description"],
                            active=bool(r["active"]), members=members))
        return out

    @router.post("/teams", response_model=Team, status_code=201)
    def add_team(body: TeamIn, scope=Depends(org_scope)) -> Team:
        user, org_id = scope
        need_team_admin(user)
        if q("SELECT 1 FROM teams WHERE organization_id=? AND lower(name)=lower(?)", (org_id, body.name)):
            raise HTTPException(status_code=409, detail="A team with this name exists")
        tid = portal._exec("INSERT INTO teams (organization_id, name, description) VALUES (?, ?, ?)",
                           (org_id, body.name, body.description))
        portal.audit(org_id, user, "team.created", body.name)
        return Team(team_id=tid, active=True, **body.model_dump())

    @router.put("/teams/{team_id}/members", response_model=Team)
    def set_members(team_id: int, body: MembersIn, scope=Depends(org_scope)) -> Team:
        user, org_id = scope
        need_team_admin(user)
        team = team_of(org_id, team_id)
        for uid in body.user_ids:
            check_assignee(org_id, uid)
        with store._connect() as conn:
            conn.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))
            conn.executemany("INSERT INTO team_members VALUES (?, ?)", [(team_id, u) for u in set(body.user_ids)])
        names = user_names(org_id)
        portal.audit(org_id, user, "team.members_set", team["name"],
                     ", ".join(names.get(u, str(u)) for u in body.user_ids) or "(none)")
        return next(t for t in list_teams(scope) if t.team_id == team_id)

    @router.post("/teams/{team_id}/archive", response_model=Team)
    def archive_team(team_id: int, scope=Depends(org_scope)) -> Team:
        user, org_id = scope
        need_team_admin(user)
        team = team_of(org_id, team_id)
        portal._exec("UPDATE teams SET active=0 WHERE team_id=?", (team_id,))
        portal.audit(org_id, user, "team.archived", team["name"], "kept on record with its tickets")
        return next(t for t in list_teams(scope) if t.team_id == team_id)

    # ---------- tickets ----------
    @router.get("/tickets", response_model=list[Ticket])
    def list_tickets(scope=Depends(org_scope),
                     view: Literal["all", "open", "mine", "my_teams", "unassigned", "overdue"] = "open",
                     status: Status | None = None, team_id: int | None = None) -> list[Ticket]:
        user, org_id = scope
        sync_incidents(org_id)
        ctx = context(org_id)
        out = [to_ticket(r, *ctx) for r in q("SELECT * FROM tickets WHERE organization_id=? ORDER BY ticket_id DESC",
                                              (org_id,)) if visible(r, user)]
        teams = my_team_ids(user)
        is_open = lambda t: t.status in OPEN_TICKET  # noqa: E731
        filters = {
            "all": lambda t: True,
            "open": is_open,
            "mine": lambda t: is_open(t) and t.assignee_id == user.user_id,
            "my_teams": lambda t: is_open(t) and t.team_id in teams,
            "unassigned": lambda t: is_open(t) and t.team_id is None and t.assignee_id is None,
            "overdue": lambda t: is_open(t) and (t.response_breached or t.resolve_breached),
        }
        out = [t for t in out if filters[view](t)]
        if status:
            out = [t for t in out if t.status == status]
        if team_id is not None:
            out = [t for t in out if t.team_id == team_id]
        return out

    @router.post("/tickets", response_model=Ticket, status_code=201)
    def create_ticket(body: TicketIn, scope=Depends(org_scope)) -> Ticket:
        user, org_id = scope
        can_work(user)
        if body.device_id and body.device_id not in {d.device_id for d in org_devices(org_id)}:
            raise HTTPException(status_code=422, detail="Unknown device")
        team_of(org_id, body.team_id)
        check_assignee(org_id, body.assignee_id)
        tid = insert_ticket(org_id, user, body.title, body.description, body.priority, "manual",
                            device_id=body.device_id, team_id=body.team_id, assignee_id=body.assignee_id)
        portal.audit(org_id, user, "ticket.created", f"T-{tid}", body.title)
        return load(org_id, tid, user)

    @router.get("/tickets/{ticket_id}", response_model=Ticket)
    def get_ticket(ticket_id: int, scope=Depends(org_scope)) -> Ticket:
        sync_incidents(scope[1])  # pick up a recovery that monitoring confirmed since the last read
        return load(scope[1], ticket_id, scope[0])

    @router.patch("/tickets/{ticket_id}", response_model=Ticket)
    def update_ticket(ticket_id: int, body: TicketUpdate, scope=Depends(org_scope)) -> Ticket:
        user, org_id = scope
        can_work(user)
        cur = load(org_id, ticket_id, user)
        if user.role not in MANAGERS and (body.team_id is not None or body.assignee_id is not None
                                          or body.unassign or body.priority is not None):
            raise HTTPException(status_code=403, detail="Only admins and operators can assign or change priority")
        changes: dict = {}
        if body.unassign:
            changes.update(team_id=None, assignee_id=None)
        if body.team_id is not None:
            team_of(org_id, body.team_id)
            changes["team_id"] = body.team_id
        if body.assignee_id is not None:
            check_assignee(org_id, body.assignee_id)
            changes["assignee_id"] = body.assignee_id
        if body.priority and body.priority != cur.priority:
            start = datetime.fromisoformat(cur.created_at)
            changes.update(priority=body.priority, response_due=iso(start + SLA[body.priority][0]),
                           resolve_due=iso(start + SLA[body.priority][1]))
        if body.status and body.status != cur.status:
            changes["status"] = body.status
            if body.status in ("resolved", "closed"):
                changes["resolved_at"] = cur.resolved_at or iso(utcnow())
            elif cur.status in ("resolved", "closed"):
                changes["resolved_at"] = None  # reopened
        elif (changes.get("team_id") or changes.get("assignee_id")) and cur.status == "new":
            changes["status"] = "assigned"
        changes = {k: v for k, v in changes.items() if getattr(cur, k) != v}
        if not changes:
            return cur
        ts = iso(utcnow())
        extra = {"updated_at": ts, **({"first_response_at": ts} if cur.first_response_at is None else {})}
        allc = {**changes, **extra}
        portal._exec(f"UPDATE tickets SET {', '.join(f'{k}=?' for k in allc)} WHERE ticket_id=?",
                     (*allc.values(), ticket_id))
        names, teams, _ = context(org_id)
        for k in ("status", "priority", "team_id", "assignee_id"):
            if k in changes:
                old, new = getattr(cur, k), changes[k]
                if k == "team_id":
                    old, new = teams.get(old), teams.get(new)
                elif k == "assignee_id":
                    old, new = names.get(old), names.get(new)
                log(ticket_id, org_id, user, k.removesuffix("_id"), {"from": old, "to": new})
        portal.audit(org_id, user, "ticket.updated", f"T-{ticket_id}", ", ".join(changes))
        return load(org_id, ticket_id, user)

    @router.post("/tickets/{ticket_id}/comments", response_model=Ticket)
    def comment(ticket_id: int, body: CommentIn, scope=Depends(org_scope)) -> Ticket:
        user, org_id = scope
        can_work(user)
        load(org_id, ticket_id, user)
        log(ticket_id, org_id, user, "comment", {"body": body.body})
        ts = iso(utcnow())
        portal._exec("UPDATE tickets SET updated_at=?, first_response_at=COALESCE(first_response_at, ?) WHERE ticket_id=?",
                     (ts, ts, ticket_id))
        return load(org_id, ticket_id, user)

    # ---------- reports: the company's own data, for the company ----------
    @router.get("/reports/tickets")
    def ticket_report(scope=Depends(org_scope), days: int = 30) -> dict:
        user, org_id = scope
        sync_incidents(org_id)
        since = utcnow() - timedelta(days=days)
        ctx = context(org_id)
        all_t = [to_ticket(r, *ctx) for r in q("SELECT * FROM tickets WHERE organization_id=?", (org_id,))]
        recent = [t for t in all_t if datetime.fromisoformat(t.created_at) >= since]
        done = [t for t in recent if t.resolved_at]

        def hours(t):
            return (datetime.fromisoformat(t.resolved_at) - datetime.fromisoformat(t.created_at)).total_seconds() / 3600

        def group(key):
            out: dict = {}
            for t in recent:
                g = out.setdefault(key(t) or "Unassigned", {"opened": 0, "resolved": 0, "open_now": 0, "met": 0, "h": []})
                g["opened"] += 1
                g["open_now"] += t.status in OPEN_TICKET
                if t.resolved_at:
                    g["resolved"] += 1
                    g["h"].append(hours(t))
                    g["met"] += not t.resolve_breached
            return [{"name": k, "opened": g["opened"], "resolved": g["resolved"], "open_now": g["open_now"],
                     "avg_hours_to_resolve": round(sum(g["h"]) / len(g["h"]), 1) if g["h"] else None,
                     "sla_met_pct": round(100 * g["met"] / g["resolved"]) if g["resolved"] else None}
                    for k, g in sorted(out.items(), key=lambda kv: -kv[1]["opened"])]

        by_device: dict[str, int] = {}
        for t in recent:
            if t.device_id:
                by_device[t.device_id] = by_device.get(t.device_id, 0) + 1
        return {
            "days": days, "opened": len(recent), "resolved": len(done),
            "open_now": sum(t.status in OPEN_TICKET for t in all_t),
            "overdue_now": sum(t.status in OPEN_TICKET and (t.response_breached or t.resolve_breached) for t in all_t),
            "avg_hours_to_resolve": round(sum(map(hours, done)) / len(done), 1) if done else None,
            "sla_met_pct": round(100 * sum(not t.resolve_breached for t in done) / len(done)) if done else None,
            "from_monitoring": sum(t.source == "incident" for t in recent),
            "by_team": group(lambda t: t.team_name), "by_assignee": group(lambda t: t.assignee_name),
            "by_priority": group(lambda t: t.priority),
            "top_devices": sorted(({"device_id": k, "tickets": v} for k, v in by_device.items()),
                                  key=lambda r: -r["tickets"])[:10],
        }

    # ---------- activity log ----------
    @router.get("/audit")
    def audit_log(scope=Depends(org_scope), limit: int = 200) -> list[dict]:
        user, org_id = scope
        need_team_admin(user)
        return [dict(r) for r in q("SELECT * FROM audit_log WHERE organization_id=? ORDER BY audit_id DESC LIMIT ?",
                                   (org_id, min(limit, 1000)))]

    @router.get("/admin/audit")
    def platform_audit(user=Depends(current_user), organization_id: str | None = None, limit: int = 300) -> list[dict]:
        if user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Platform staff only")
        if organization_id:
            rows = q("SELECT * FROM audit_log WHERE organization_id=? ORDER BY audit_id DESC LIMIT ?",
                     (organization_id, min(limit, 2000)))
        else:
            rows = q("SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT ?", (min(limit, 2000),))
        return [dict(r) for r in rows]

    # ---------- exports: a company can take all of its data with it ----------
    def csv_response(name: str, header: list[str], rows: list[list]) -> Response:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})

    @router.get("/export/{kind}.csv")
    def export(kind: Literal["tickets", "ticket_history", "devices", "incidents", "audit", "sites", "teams"],
               scope=Depends(org_scope)) -> Response:
        user, org_id = scope
        need_team_admin(user)
        sync_incidents(org_id)
        portal.audit(org_id, user, "data.exported", kind)
        stamp = f"{org_id}-{kind}-{utcnow().strftime('%Y%m%d')}"
        if kind == "tickets":
            ctx = context(org_id)
            ts = [to_ticket(r, *ctx) for r in q("SELECT * FROM tickets WHERE organization_id=? ORDER BY ticket_id",
                                                (org_id,))]
            cols = ["ticket_id", "title", "priority", "status", "source", "team_name", "assignee_name", "device_id",
                    "incident_id", "incident_status", "created_by", "created_at", "first_response_at", "resolved_at",
                    "response_due", "resolve_due", "response_breached", "resolve_breached"]
            return csv_response(stamp, cols, [[getattr(t, c) for c in cols] for t in ts])
        if kind == "ticket_history":
            rows = q("SELECT ticket_id, created_at, actor_name, kind, detail FROM ticket_events WHERE organization_id=?"
                     " ORDER BY event_id", (org_id,))
            return csv_response(stamp, ["ticket_id", "at", "by", "change", "detail"], [list(r) for r in rows])
        if kind == "devices":
            cols = ["device_id", "name", "device_type", "profile_id", "site_id", "zone_id", "parent_device_id",
                    "automation_policy", "responsible_team", "enabled", "status", "open_incidents"]
            return csv_response(stamp, cols, [[getattr(d, c) for c in cols] for d in org_devices(org_id)])
        if kind == "incidents":
            ids = {d.device_id for d in org_devices(org_id)}
            inc = [i for i in store.list_incidents() if ids & set(i.affected_devices)]
            return csv_response(stamp, ["incident_id", "status", "severity", "created_at", "updated_at",
                                        "affected_devices", "probable_cause", "external_ticket"],
                                [[i.incident_id, i.status, i.severity, i.created_at.isoformat(), i.updated_at.isoformat(),
                                  " ".join(i.affected_devices),
                                  i.rca.ranked_causes[0].device_id if i.rca.ranked_causes else "",
                                  i.ticket.external_ticket_id if i.ticket else ""] for i in inc])
        if kind == "audit":
            rows = q("SELECT created_at, actor_name, action, target, detail FROM audit_log WHERE organization_id=?"
                     " ORDER BY audit_id", (org_id,))
            return csv_response(stamp, ["at", "by", "action", "target", "detail"], [list(r) for r in rows])
        if kind == "sites":
            return csv_response(stamp, ["site_id", "name", "address", "contact"],
                                [[s.site_id, s.name, s.address, s.contact] for s in portal.list_sites(org_id)])
        return csv_response(stamp, ["team_id", "name", "description", "active", "members"],
                            [[t.team_id, t.name, t.description, t.active, "; ".join(m["full_name"] for m in t.members)]
                             for t in list_teams(scope)])

    def sync_all() -> None:
        for r in q("SELECT organization_id FROM organizations WHERE active=1"):
            sync_incidents(r["organization_id"])

    @router.get("/notifications")
    def notifications(scope=Depends(org_scope), limit: int = 200) -> list[dict]:
        """Email alerts sent (or not) for this company's tickets, newest first. Admins only."""
        need_team_admin(scope[0])
        return notifier.list(scope[1], limit) if notifier else []

    return sync_all
