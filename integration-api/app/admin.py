"""Platform admin (us, the NMS provider): watch every company, suspend or reactivate,
answer support requests, and post notices to one company or to all.

Super admins are "staff". Company users can open support requests for their own
company and read notices meant for them.
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

Priority = Literal["low", "normal", "high", "urgent"]
SupportStatus = Literal["open", "in_progress", "waiting_customer", "resolved"]
Level = Literal["info", "warning", "critical"]
OPEN_INCIDENT = {"open", "action_pending", "verifying", "escalated"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CompanyRow(BaseModel):
    organization_id: str
    name: str
    active: bool
    users: int
    sites: int
    devices: int
    devices_problem: int
    open_incidents: int
    open_support: int
    health: Literal["good", "attention", "critical", "no_devices"]


class CompanyCreate(BaseModel):
    """A new customer and its first login, created by us; we hand the email and password to them."""
    organization_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    name: str = Field(min_length=1)
    admin_name: str = Field(min_length=1)
    admin_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$")
    admin_password: str = Field(min_length=8)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    active: bool | None = None


class SupportIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    priority: Priority = "normal"


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class StatusIn(BaseModel):
    status: SupportStatus


class Message(BaseModel):
    message_id: int
    author_name: str
    from_staff: bool
    body: str
    created_at: str


class SupportRequest(BaseModel):
    request_id: int
    organization_id: str
    organization_name: str
    subject: str
    priority: Priority
    status: SupportStatus
    created_by: str
    created_at: str
    updated_at: str
    messages: list[Message] = []


class NoticeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    level: Level = "info"
    organization_id: str | None = None  # None = every company


class Notice(NoticeIn):
    notice_id: int
    created_at: str


def health(devices: int, problem: int) -> str:
    if devices == 0:
        return "no_devices"
    return "critical" if problem / devices >= 0.25 else "attention" if problem else "good"


def register(router: APIRouter, store, portal, current_user, org_scope, org_devices) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)  # runs at app build, before the lifespan init
    with store._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS support_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS support_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL REFERENCES support_requests(request_id),
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                from_staff INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notices (
                notice_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                level TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def staff(user=Depends(current_user)):
        if user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Platform staff only")
        return user

    def org_names() -> dict[str, str]:
        return {o.organization_id: o.name for o in portal.list_orgs()}

    def load_request(request_id: int, with_messages: bool = True) -> SupportRequest | None:
        rows = portal._all("SELECT * FROM support_requests WHERE request_id=?", (request_id,))
        if not rows:
            return None
        r = dict(rows[0])
        msgs = [Message(message_id=m["message_id"], author_name=m["author_name"], from_staff=bool(m["from_staff"]),
                        body=m["body"], created_at=m["created_at"])
                for m in portal._all("SELECT * FROM support_messages WHERE request_id=? ORDER BY message_id",
                                     (request_id,))] if with_messages else []
        return SupportRequest(**r, organization_name=org_names().get(r["organization_id"], r["organization_id"]),
                              messages=msgs)

    def visible_request(request_id: int, user) -> SupportRequest:
        req = load_request(request_id)
        if req is None or (user.role != "super_admin" and req.organization_id != user.organization_id):
            raise HTTPException(status_code=404, detail="Unknown support request")
        return req

    def add_message(request_id: int, user, body: str) -> None:
        portal._exec("INSERT INTO support_messages (request_id, author_id, author_name, from_staff, body, created_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)",
                     (request_id, user.user_id, user.full_name, int(user.role == "super_admin"), body, now()))

    def company_rows() -> list[CompanyRow]:
        incidents = [i for i in store.list_incidents() if i.status in OPEN_INCIDENT]
        out = []
        for org in portal.list_orgs():
            oid = org.organization_id
            devs = org_devices(oid)
            ids = {d.device_id for d in devs}
            problem = sum(d.status == "problem" for d in devs)
            support = portal._all("SELECT COUNT(*) c FROM support_requests WHERE organization_id=? AND status!='resolved'",
                                  (oid,))[0]["c"]
            out.append(CompanyRow(
                organization_id=oid, name=org.name, active=portal.org_active(oid),
                users=len(portal.list_users(oid)), sites=len(portal.list_sites(oid)), devices=len(devs),
                devices_problem=problem, open_incidents=sum(1 for i in incidents if ids.intersection(i.affected_devices)),
                open_support=support, health=health(len(devs), problem)))
        return out

    # ---------- companies (staff) ----------
    @router.get("/admin/companies", response_model=list[CompanyRow])
    def companies(_=Depends(staff)) -> list[CompanyRow]:
        return company_rows()

    @router.post("/admin/companies", response_model=CompanyRow, status_code=201)
    def create_company(body: CompanyCreate, _=Depends(staff)) -> CompanyRow:
        from app.portal import Organization, UserIn
        if portal.get_org(body.organization_id):
            raise HTTPException(status_code=409, detail="Company ID already used")
        if portal.find_user(body.admin_email):
            raise HTTPException(status_code=409, detail="Email already used")
        portal.add_org(Organization(organization_id=body.organization_id, name=body.name))
        portal.add_user(body.organization_id, UserIn(email=body.admin_email, full_name=body.admin_name,
                                                     password=body.admin_password, role="admin"))
        return next(c for c in company_rows() if c.organization_id == body.organization_id)

    @router.patch("/admin/companies/{organization_id}", response_model=CompanyRow)
    def update_company(organization_id: str, body: CompanyUpdate, user=Depends(staff)) -> CompanyRow:
        if portal.get_org(organization_id) is None:
            raise HTTPException(status_code=404, detail="Unknown company")
        if body.active is False and organization_id == user.organization_id:
            raise HTTPException(status_code=409, detail="You cannot suspend your own company")
        if body.name:
            portal.rename_org(organization_id, body.name)
        if body.active is not None:
            portal.set_org_active(organization_id, body.active)
        return next(c for c in company_rows() if c.organization_id == organization_id)

    # ---------- support requests ----------
    @router.post("/support", response_model=SupportRequest, status_code=201)
    def open_request(body: SupportIn, user=Depends(current_user)) -> SupportRequest:
        ts = now()
        rid = portal._exec(
            "INSERT INTO support_requests (organization_id, subject, priority, status, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, 'open', ?, ?, ?)",
            (user.organization_id, body.subject, body.priority, user.full_name, ts, ts))
        add_message(rid, user, body.message)
        return load_request(rid)

    @router.get("/support", response_model=list[SupportRequest])
    def list_requests(status: SupportStatus | None = None, organization_id: str | None = None,
                      user=Depends(current_user)) -> list[SupportRequest]:
        sql, params = "SELECT request_id FROM support_requests WHERE 1=1", []
        if user.role != "super_admin":
            sql += " AND organization_id=?"
            params.append(user.organization_id)
        elif organization_id:
            sql += " AND organization_id=?"
            params.append(organization_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        rows = portal._all(sql + " ORDER BY CASE status WHEN 'resolved' THEN 1 ELSE 0 END, updated_at DESC, request_id DESC",
                           tuple(params))
        return [load_request(r["request_id"], with_messages=False) for r in rows]

    @router.get("/support/{request_id}", response_model=SupportRequest)
    def get_request(request_id: int, user=Depends(current_user)) -> SupportRequest:
        return visible_request(request_id, user)

    @router.post("/support/{request_id}/messages", response_model=SupportRequest)
    def reply(request_id: int, body: MessageIn, user=Depends(current_user)) -> SupportRequest:
        req = visible_request(request_id, user)
        add_message(request_id, user, body.message)
        # staff reply -> waiting for the customer; customer reply -> back to staff (reopens if resolved)
        if user.role == "super_admin":
            status = "resolved" if req.status == "resolved" else "waiting_customer"
        else:
            status = "open"
        portal._exec("UPDATE support_requests SET status=?, updated_at=? WHERE request_id=?", (status, now(), request_id))
        return load_request(request_id)

    @router.patch("/support/{request_id}", response_model=SupportRequest)
    def set_status(request_id: int, body: StatusIn, user=Depends(current_user)) -> SupportRequest:
        visible_request(request_id, user)
        if user.role != "super_admin" and body.status not in {"resolved", "open"}:
            raise HTTPException(status_code=403, detail="Customers can only close or reopen a request")
        portal._exec("UPDATE support_requests SET status=?, updated_at=? WHERE request_id=?",
                     (body.status, now(), request_id))
        return load_request(request_id)

    # ---------- notices ----------
    @router.post("/admin/notices", response_model=Notice, status_code=201)
    def post_notice(body: NoticeIn, _=Depends(staff)) -> Notice:
        if body.organization_id and portal.get_org(body.organization_id) is None:
            raise HTTPException(status_code=404, detail="Unknown company")
        ts = now()
        nid = portal._exec("INSERT INTO notices (organization_id, title, body, level, created_at) VALUES (?, ?, ?, ?, ?)",
                           (body.organization_id, body.title, body.body, body.level, ts))
        return Notice(**body.model_dump(), notice_id=nid, created_at=ts)

    @router.delete("/admin/notices/{notice_id}", status_code=204)
    def delete_notice(notice_id: int, _=Depends(staff)) -> None:
        portal._exec("DELETE FROM notices WHERE notice_id=?", (notice_id,))

    @router.get("/notices", response_model=list[Notice])
    def notices(user=Depends(current_user)) -> list[Notice]:
        if user.role == "super_admin":
            rows = portal._all("SELECT * FROM notices ORDER BY notice_id DESC LIMIT 100")
        else:
            rows = portal._all("SELECT * FROM notices WHERE organization_id IS NULL OR organization_id=? "
                               "ORDER BY notice_id DESC LIMIT 20", (user.organization_id,))
        return [Notice(**dict(r)) for r in rows]
