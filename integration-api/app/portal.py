"""Customer portal, phase 1: organizations, sites, users, login, and tenant-scoped devices.

Every portal call is scoped to the caller's organization. A super_admin can act on any
organization by passing ?organization_id=. The existing pipeline endpoints (/devices,
/events, /grafana/...) are unchanged; they are internal and used by Zabbix and Grafana.
"""
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.profiles import ProfileCatalog
from app.schemas import Device, Identifier, Policy, TopologyEdge
from app.store import DeviceAlreadyExists, Store

Role = Literal["super_admin", "admin", "operator", "viewer"]
WRITE_ROLES = {"super_admin", "admin"}
TOKEN_TTL_SECONDS = 12 * 3600
OPEN_STATUSES = {"open", "action_pending", "verifying", "escalated"}
EMAIL = r"^[^@\s]+@[^@\s]+$"


# ---------- schemas ----------
class Organization(BaseModel):
    organization_id: Identifier
    name: str = Field(min_length=1)


class SiteIn(BaseModel):
    site_id: Identifier
    name: str = Field(min_length=1)
    address: str = ""
    contact: str = ""


class Site(SiteIn):
    organization_id: str


class UserIn(BaseModel):
    email: str = Field(pattern=EMAIL)
    full_name: str = Field(min_length=1)
    password: str = Field(min_length=8)
    role: Role = "operator"


class User(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: Role
    organization_id: str


class SetupIn(BaseModel):
    organization: Organization
    email: str = Field(pattern=EMAIL)
    full_name: str = Field(min_length=1)
    password: str = Field(min_length=8)


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    token: str
    user: User


class PortalDeviceIn(BaseModel):
    device_id: Identifier
    name: str = Field(min_length=1)
    profile_id: Identifier
    site_id: Identifier
    zone_id: str = "default"
    management_address: str = Field(min_length=1)
    responsible_team: str = "noc"
    parent_device_id: Identifier | None = None
    automation_policy: Policy | None = None
    enabled: bool = True


class PortalDeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    site_id: Identifier | None = None
    zone_id: str | None = None
    management_address: str | None = Field(default=None, min_length=1)
    responsible_team: str | None = None
    automation_policy: Policy | None = None
    enabled: bool | None = None


class PortalDevice(Device):
    status: Literal["ok", "problem", "disabled"]
    open_incidents: int
    parent_device_id: str | None = None


class Overview(BaseModel):
    organization: Organization
    sites: int
    devices: int
    devices_ok: int
    devices_problem: int
    devices_disabled: int
    open_incidents: int
    by_type: dict[str, int]
    by_site: list[dict]


# ---------- passwords and tokens (stdlib only) ----------
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)), stored)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(user_id: int, secret: bytes, now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + TOKEN_TTL_SECONDS)
    body = _b64(json.dumps({"uid": user_id, "exp": exp}).encode())
    sig = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str, secret: bytes) -> int | None:
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
    return int(data["uid"]) if data.get("exp", 0) > time.time() else None


# ---------- storage (same SQLite file as the pipeline) ----------
class PortalStore:
    def __init__(self, store: Store) -> None:
        self.store = store

    def init(self) -> None:
        with self.store._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    organization_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sites (
                    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
                    site_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    contact TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (organization_id, site_id)
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(organizations)")}
            if "active" not in cols:  # databases created before company suspension existed
                conn.execute("ALTER TABLE organizations ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

    def org_active(self, org_id: str) -> bool:
        rows = self._all("SELECT active FROM organizations WHERE organization_id = ?", (org_id,))
        return bool(rows and rows[0]["active"])

    def set_org_active(self, org_id: str, active: bool) -> None:
        self._exec("UPDATE organizations SET active=? WHERE organization_id=?", (int(active), org_id))

    def rename_org(self, org_id: str, name: str) -> None:
        self._exec("UPDATE organizations SET name=? WHERE organization_id=?", (name, org_id))

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.store._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self.store._connect() as conn:
            return conn.execute(sql, params).lastrowid

    # organizations
    def user_count(self) -> int:
        return self._all("SELECT COUNT(*) c FROM users")[0]["c"]

    def add_org(self, org: Organization) -> None:
        self._exec("INSERT INTO organizations (organization_id, name) VALUES (?, ?)", (org.organization_id, org.name))

    def get_org(self, org_id: str) -> Organization | None:
        rows = self._all("SELECT organization_id, name FROM organizations WHERE organization_id = ?", (org_id,))
        return Organization(**dict(rows[0])) if rows else None

    def list_orgs(self) -> list[Organization]:
        return [Organization(**dict(r)) for r in self._all("SELECT organization_id, name FROM organizations ORDER BY name")]

    # sites
    def add_site(self, org_id: str, site: SiteIn) -> Site:
        self._exec("INSERT INTO sites VALUES (?, ?, ?, ?, ?)",
                   (org_id, site.site_id, site.name, site.address, site.contact))
        return Site(organization_id=org_id, **site.model_dump())

    def update_site(self, org_id: str, site: SiteIn) -> None:
        self._exec("UPDATE sites SET name=?, address=?, contact=? WHERE organization_id=? AND site_id=?",
                   (site.name, site.address, site.contact, org_id, site.site_id))

    def delete_site(self, org_id: str, site_id: str) -> None:
        self._exec("DELETE FROM sites WHERE organization_id=? AND site_id=?", (org_id, site_id))

    def list_sites(self, org_id: str) -> list[Site]:
        return [Site(**dict(r)) for r in
                self._all("SELECT * FROM sites WHERE organization_id=? ORDER BY name", (org_id,))]

    def get_site(self, org_id: str, site_id: str) -> Site | None:
        rows = self._all("SELECT * FROM sites WHERE organization_id=? AND site_id=?", (org_id, site_id))
        return Site(**dict(rows[0])) if rows else None

    # users
    def add_user(self, org_id: str, user: UserIn) -> User:
        uid = self._exec(
            "INSERT INTO users (email, full_name, role, organization_id, password_hash) VALUES (?, ?, ?, ?, ?)",
            (user.email.lower(), user.full_name, user.role, org_id, hash_password(user.password)))
        return User(user_id=uid, email=user.email.lower(), full_name=user.full_name, role=user.role,
                    organization_id=org_id)

    def find_user(self, email: str) -> sqlite3.Row | None:
        rows = self._all("SELECT * FROM users WHERE email=? AND active=1", (email.lower(),))
        return rows[0] if rows else None

    def get_user(self, user_id: int) -> User | None:
        rows = self._all("SELECT * FROM users WHERE user_id=? AND active=1", (user_id,))
        return self.to_user(rows[0]) if rows else None

    def list_users(self, org_id: str) -> list[User]:
        return [self.to_user(r) for r in
                self._all("SELECT * FROM users WHERE organization_id=? AND active=1 ORDER BY email", (org_id,))]

    def deactivate_user(self, org_id: str, user_id: int) -> None:
        self._exec("UPDATE users SET active=0 WHERE organization_id=? AND user_id=?", (org_id, user_id))

    @staticmethod
    def to_user(r: sqlite3.Row) -> User:
        return User(user_id=r["user_id"], email=r["email"], full_name=r["full_name"], role=r["role"],
                    organization_id=r["organization_id"])

    # devices: edit fields of a row in the pipeline's devices table
    def update_device(self, device: Device) -> None:
        self._exec(
            """UPDATE devices SET name=?, site_id=?, zone_id=?, management_address=?, responsible_team=?,
               automation_policy=?, enabled=? WHERE device_id=?""",
            (device.name, device.site_id, device.zone_id, device.management_address, device.responsible_team,
             device.automation_policy, int(device.enabled), device.device_id))


# ---------- router ----------
def make_router(store: Store, portal: PortalStore, profiles: ProfileCatalog, secret: bytes) -> APIRouter:
    router = APIRouter(prefix="/portal", tags=["portal"])

    def current_user(authorization: str | None = Header(default=None)) -> User:
        token = (authorization or "").removeprefix("Bearer ").strip()
        uid = read_token(token, secret) if token else None
        user = portal.get_user(uid) if uid is not None else None
        if user is None:
            raise HTTPException(status_code=401, detail="Login required")
        if user.role != "super_admin" and not portal.org_active(user.organization_id):
            raise HTTPException(status_code=403, detail="Your company's account is suspended. Contact support.")
        return user

    def org_scope(user: User = Depends(current_user),
                  organization_id: str | None = Query(default=None)) -> tuple[User, str]:
        if organization_id and organization_id != user.organization_id:
            if user.role != "super_admin":
                raise HTTPException(status_code=403, detail="Not your organization")
            if portal.get_org(organization_id) is None:
                raise HTTPException(status_code=404, detail="Unknown organization")
            return user, organization_id
        return user, user.organization_id

    def need_write(user: User) -> None:
        if user.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Admin role required")

    def org_devices(org_id: str) -> list[PortalDevice]:
        parents = {e.from_device_id: e.to_device_id for e in store.list_edges()}
        open_count: dict[str, int] = {}
        for inc in store.list_incidents():
            if inc.status in OPEN_STATUSES:
                for d in inc.affected_devices:
                    open_count[d] = open_count.get(d, 0) + 1
        out = []
        for d in store.list_devices():
            if d.organization_id != org_id:
                continue
            n = open_count.get(d.device_id, 0)
            status = "disabled" if not d.enabled else ("problem" if n else "ok")
            out.append(PortalDevice(**d.model_dump(), status=status, open_incidents=n,
                                    parent_device_id=parents.get(d.device_id)))
        return out

    def owned_device(org_id: str, device_id: str) -> Device:
        d = store.get_device(device_id)
        if d is None or d.organization_id != org_id:
            raise HTTPException(status_code=404, detail=f"Unknown device_id {device_id}")
        return d

    def one_device(org_id: str, device_id: str) -> PortalDevice:
        owned_device(org_id, device_id)
        return next(d for d in org_devices(org_id) if d.device_id == device_id)

    # setup and auth
    @router.get("/setup")
    def setup_needed() -> dict[str, bool]:
        return {"needed": portal.user_count() == 0}

    @router.post("/setup", response_model=LoginOut, status_code=201)
    def setup(body: SetupIn) -> LoginOut:
        if portal.user_count() > 0:
            raise HTTPException(status_code=409, detail="Already set up")
        if portal.get_org(body.organization.organization_id) is None:
            portal.add_org(body.organization)
        user = portal.add_user(body.organization.organization_id, UserIn(
            email=body.email, full_name=body.full_name, password=body.password, role="super_admin"))
        return LoginOut(token=make_token(user.user_id, secret), user=user)

    @router.post("/login", response_model=LoginOut)
    def login(body: LoginIn) -> LoginOut:
        row = portal.find_user(body.email)
        if row is None or not check_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Wrong email or password")
        user = PortalStore.to_user(row)
        if user.role != "super_admin" and not portal.org_active(user.organization_id):
            raise HTTPException(status_code=403, detail="Your company's account is suspended. Contact support.")
        return LoginOut(token=make_token(user.user_id, secret), user=user)

    @router.get("/me", response_model=User)
    def me(user: User = Depends(current_user)) -> User:
        return user

    # organizations
    @router.get("/organizations", response_model=list[Organization])
    def list_orgs(user: User = Depends(current_user)) -> list[Organization]:
        if user.role == "super_admin":
            return portal.list_orgs()
        return [portal.get_org(user.organization_id)]

    @router.post("/organizations", response_model=Organization, status_code=201)
    def add_org(body: Organization, user: User = Depends(current_user)) -> Organization:
        if user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin only")
        if portal.get_org(body.organization_id):
            raise HTTPException(status_code=409, detail="Organization exists")
        portal.add_org(body)
        return body

    # overview
    @router.get("/overview", response_model=Overview)
    def overview(scope=Depends(org_scope)) -> Overview:
        org_id = scope[1]
        devices = org_devices(org_id)
        sites = portal.list_sites(org_id)
        ids = {d.device_id for d in devices}
        open_inc = sum(1 for i in store.list_incidents()
                       if i.status in OPEN_STATUSES and ids.intersection(i.affected_devices))
        by_type: dict[str, int] = {}
        for d in devices:
            by_type[d.device_type] = by_type.get(d.device_type, 0) + 1
        by_site = []
        for s in sites:
            ds = [d for d in devices if d.site_id == s.site_id]
            by_site.append({"site_id": s.site_id, "name": s.name, "devices": len(ds),
                            "problem": sum(d.status == "problem" for d in ds)})
        return Overview(organization=portal.get_org(org_id), sites=len(sites), devices=len(devices),
                        devices_ok=sum(d.status == "ok" for d in devices),
                        devices_problem=sum(d.status == "problem" for d in devices),
                        devices_disabled=sum(d.status == "disabled" for d in devices),
                        open_incidents=open_inc, by_type=by_type, by_site=by_site)

    # sites
    @router.get("/sites", response_model=list[Site])
    def list_sites(scope=Depends(org_scope)) -> list[Site]:
        return portal.list_sites(scope[1])

    @router.post("/sites", response_model=Site, status_code=201)
    def add_site(body: SiteIn, scope=Depends(org_scope)) -> Site:
        user, org_id = scope
        need_write(user)
        if portal.get_site(org_id, body.site_id):
            raise HTTPException(status_code=409, detail=f"Site {body.site_id} exists")
        return portal.add_site(org_id, body)

    @router.put("/sites/{site_id}", response_model=Site)
    def edit_site(site_id: str, body: SiteIn, scope=Depends(org_scope)) -> Site:
        user, org_id = scope
        need_write(user)
        if site_id != body.site_id or portal.get_site(org_id, site_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown site {site_id}")
        portal.update_site(org_id, body)
        return portal.get_site(org_id, site_id)

    @router.delete("/sites/{site_id}", status_code=204)
    def delete_site(site_id: str, scope=Depends(org_scope)) -> None:
        user, org_id = scope
        need_write(user)
        if any(d.site_id == site_id for d in org_devices(org_id)):
            raise HTTPException(status_code=409, detail="Move or remove the site's devices first")
        portal.delete_site(org_id, site_id)

    # users
    @router.get("/users", response_model=list[User])
    def list_users(scope=Depends(org_scope)) -> list[User]:
        need_write(scope[0])
        return portal.list_users(scope[1])

    @router.post("/users", response_model=User, status_code=201)
    def add_user(body: UserIn, scope=Depends(org_scope)) -> User:
        user, org_id = scope
        need_write(user)
        if body.role == "super_admin" and user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Only a super admin can create a super admin")
        if portal.find_user(body.email):
            raise HTTPException(status_code=409, detail="Email already used")
        return portal.add_user(org_id, body)

    @router.delete("/users/{user_id}", status_code=204)
    def remove_user(user_id: int, scope=Depends(org_scope)) -> None:
        user, org_id = scope
        need_write(user)
        if user_id == user.user_id:
            raise HTTPException(status_code=409, detail="You cannot remove yourself")
        portal.deactivate_user(org_id, user_id)

    # devices
    @router.get("/devices", response_model=list[PortalDevice])
    def list_devices(scope=Depends(org_scope), site_id: str | None = None, device_type: str | None = None,
                     status: str | None = None, q: str | None = None) -> list[PortalDevice]:
        out = org_devices(scope[1])
        if site_id:
            out = [d for d in out if d.site_id == site_id]
        if device_type:
            out = [d for d in out if d.device_type == device_type]
        if status:
            out = [d for d in out if d.status == status]
        if q:
            ql = q.lower()
            out = [d for d in out if ql in d.device_id.lower() or ql in d.name.lower()]
        return out

    @router.get("/devices/{device_id}", response_model=PortalDevice)
    def get_device(device_id: str, scope=Depends(org_scope)) -> PortalDevice:
        return one_device(scope[1], device_id)

    @router.post("/devices", response_model=PortalDevice, status_code=201)
    def add_device(body: PortalDeviceIn, scope=Depends(org_scope)) -> PortalDevice:
        user, org_id = scope
        need_write(user)
        profile = profiles.get(body.profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Unknown profile_id {body.profile_id}")
        if portal.get_site(org_id, body.site_id) is None:
            raise HTTPException(status_code=422, detail=f"Unknown site {body.site_id}; add the site first")
        if body.parent_device_id:
            owned_device(org_id, body.parent_device_id)
        device = Device(device_id=body.device_id, name=body.name, device_type=profile.device_type,
                        profile_id=profile.profile_id, organization_id=org_id, site_id=body.site_id,
                        zone_id=body.zone_id or "default", management_address=body.management_address,
                        responsible_team=body.responsible_team or "noc",
                        automation_policy=body.automation_policy or profile.default_policy, enabled=body.enabled)
        try:
            store.insert_device(device)
        except DeviceAlreadyExists:
            raise HTTPException(status_code=409, detail=f"Device {device.device_id} already exists") from None
        if body.parent_device_id:
            store.insert_edge(TopologyEdge(from_device_id=device.device_id, to_device_id=body.parent_device_id))
        return one_device(org_id, device.device_id)

    @router.patch("/devices/{device_id}", response_model=PortalDevice)
    def edit_device(device_id: str, body: PortalDeviceUpdate, scope=Depends(org_scope)) -> PortalDevice:
        user, org_id = scope
        need_write(user)
        current = owned_device(org_id, device_id)
        changes = body.model_dump(exclude_none=True)
        if "site_id" in changes and portal.get_site(org_id, changes["site_id"]) is None:
            raise HTTPException(status_code=422, detail=f"Unknown site {changes['site_id']}")
        portal.update_device(current.model_copy(update=changes))
        return one_device(org_id, device_id)

    from app import admin  # local import: admin builds on this module's helpers
    admin.register(router, store, portal, current_user, org_scope, org_devices)
    return router
