import hmac
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from uuid import uuid4

import httpx

from app import analysis, remediation, zabbix
from collections.abc import Callable

from app.osticket import OsTicketClient, TicketError
from app.zabbix_api import ZabbixApiClient, ZabbixApiError
from app.profiles import ProfileCatalog
from app.schemas import (
    Device,
    DeviceCreate,
    DeviceProfile,
    Event,
    EventCreate,
    AnomalyOut,
    ApprovalRequest,
    Execution,
    ExecutionTimestamps,
    GrafanaExecutionRow,
    GrafanaIncidentRow,
    GrafanaSummary,
    RemediationRequest,
    IncidentAnalysis,
    StoredIncident,
    SyncResult,
    TicketMapping,
    Telemetry,
    TelemetryCreate,
    TopologyEdge,
    VerificationResult,
    VerifyOutcome,
)
from app.settings import Settings
from app.store import DeviceAlreadyExists, EdgeAlreadyExists, EventAlreadyExists, Store, new_event_id
from app.zabbix import ZabbixWebhook

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    settings: Settings,
    ticket_provider: OsTicketClient | None = None,
    remediation_transport: httpx.BaseTransport | None = None,
    zabbix_api: ZabbixApiClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    if zabbix_api is None and settings.zabbix_api_url and settings.zabbix_api_token:
        zabbix_api = ZabbixApiClient(url=settings.zabbix_api_url, token=settings.zabbix_api_token)
    playbooks = remediation.PlaybookCatalog(settings.playbooks_dir)
    store = Store(settings.database_path)
    if ticket_provider is None and settings.osticket_url and settings.osticket_api_key:
        ticket_provider = OsTicketClient(
            base_url=settings.osticket_url,
            api_key=settings.osticket_api_key,
            reporter_email=settings.osticket_reporter_email or "nms@example.invalid",
        )
    profiles = ProfileCatalog(settings.profiles_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.init()
        profiles.load()
        playbooks.load()
        app.state.settings = settings
        app.state.store = store
        app.state.profiles = profiles
        yield

    app = FastAPI(
        title="NMS Integration Service",
        summary="Normalizes devices, telemetry, and events for the generic NMS.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def console() -> str:
        return (STATIC_DIR / "console.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "nms-integration",
            "profiles": len(profiles.all()),
            "devices": store.count_devices(),
        }

    @app.get("/profiles", response_model=list[DeviceProfile])
    def list_profiles() -> list[DeviceProfile]:
        return profiles.all()

    @app.get("/profiles/{profile_id}", response_model=DeviceProfile)
    def get_profile(profile_id: str) -> DeviceProfile:
        profile = profiles.get(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Unknown profile_id {profile_id}")
        return profile

    @app.post("/devices", response_model=Device, status_code=201)
    def create_device(body: DeviceCreate) -> Device:
        profile = profiles.get(body.profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail=f"Unknown profile_id {body.profile_id}")
        if body.device_type != profile.device_type:
            raise HTTPException(
                status_code=422,
                detail=f"device_type must match profile {profile.profile_id}: {profile.device_type}",
            )
        device = Device(
            **body.model_dump(exclude={"automation_policy"}),
            automation_policy=body.automation_policy or profile.default_policy,
        )
        try:
            store.insert_device(device)
        except DeviceAlreadyExists:
            raise HTTPException(status_code=409, detail=f"Device {device.device_id} already exists") from None
        return device

    @app.get("/devices", response_model=list[Device])
    def list_devices() -> list[Device]:
        return store.list_devices()

    @app.get("/devices/{device_id}", response_model=Device)
    def get_device(device_id: str) -> Device:
        device = store.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"Unknown device_id {device_id}")
        return device

    @app.post("/events", response_model=Event, status_code=201)
    def create_event(body: EventCreate) -> Event:
        return _ingest_event(body)

    @app.post("/integrations/zabbix/events")
    def zabbix_event(
        body: ZabbixWebhook,
        response: Response,
        x_nms_webhook_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        if settings.zabbix_webhook_token and not hmac.compare_digest(
            x_nms_webhook_token or "", settings.zabbix_webhook_token
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook token")
        event_id = zabbix.event_id_for(body.eventid)
        if body.value == "0":
            # Recovery: Zabbix says this host's problem cleared. Counts as a healthy observation
            # for any incident waiting on verification of an action on this device.
            response.status_code = 202
            verified = []
            for execution in _awaiting_verification(device_id=body.host):
                outcome = _record_verification(
                    execution, True, f"Zabbix recovery event {event_id} for {body.host}"
                )
                verified.append({"incident_id": execution.incident_id, "incident_status": outcome.incident_status})
            return {"status": "recovery_received", "event_id": event_id, "verified": verified}
        try:
            normalized = zabbix.normalize(body)
        except zabbix.UnknownSeverity:
            raise HTTPException(status_code=422, detail=f"Unknown Zabbix severity {body.severity}") from None
        existing = store.get_event(event_id)
        if existing is not None:
            # Zabbix retries deliveries; the same problem must not create a second event.
            response.status_code = 200
            return {"status": "duplicate", "event": existing.model_dump(mode="json")}
        event = _ingest_event(normalized)
        response.status_code = 201
        return {"status": "created", "event": event.model_dump(mode="json")}

    def _ingest_event(body: EventCreate) -> Event:
        device = _require_device(store, body.device_id)
        profile = profiles.get(device.profile_id)
        if profile is None or body.event_type not in profile.triggers:
            raise HTTPException(
                status_code=422,
                detail=f"event_type {body.event_type} is not declared on profile {device.profile_id}",
            )
        event = Event(
            event_id=body.event_id or new_event_id(),
            device_id=body.device_id,
            event_type=body.event_type,
            severity=body.severity,
            started_at=body.started_at,
            source=body.source,
        )
        try:
            store.insert_event(event)
        except EventAlreadyExists:
            raise HTTPException(status_code=409, detail=f"Event {event.event_id} already exists") from None
        return event

    @app.get("/events", response_model=list[Event])
    def list_events() -> list[Event]:
        return store.list_events()

    @app.post("/telemetry", response_model=Telemetry, status_code=201)
    def create_telemetry(body: TelemetryCreate) -> Telemetry:
        device = _require_device(store, body.device_id)
        profile = profiles.get(device.profile_id)
        allowed = {metric.metric_name: metric.unit for metric in profile.metrics} if profile else {}
        if body.metric_name not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"metric_name {body.metric_name} is not declared on profile {device.profile_id}",
            )
        if body.unit != allowed[body.metric_name]:
            raise HTTPException(
                status_code=422,
                detail=f"unit for {body.metric_name} must be {allowed[body.metric_name]}",
            )
        return store.insert_telemetry(body)

    @app.get("/telemetry", response_model=list[Telemetry])
    def list_telemetry(device_id: str | None = None) -> list[Telemetry]:
        if device_id is not None:
            _require_device(store, device_id)
        return store.list_telemetry(device_id)

    @app.post("/topology/edges", response_model=TopologyEdge, status_code=201)
    def create_edge(body: TopologyEdge) -> TopologyEdge:
        _require_device(store, body.from_device_id)
        _require_device(store, body.to_device_id)
        topology = analysis.build_topology(store.list_edges())
        try:
            topology.add(body.from_device_id, body.to_device_id)
        except analysis.TopologyCycle as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        try:
            store.insert_edge(body)
        except EdgeAlreadyExists:
            raise HTTPException(status_code=409, detail="Edge already exists") from None
        return body

    @app.get("/topology/edges", response_model=list[TopologyEdge])
    def list_edges() -> list[TopologyEdge]:
        return store.list_edges()

    @app.get("/intelligence/incidents", response_model=list[IncidentAnalysis])
    def analyze_incidents(window_seconds: int = analysis.DEFAULT_WINDOW_SECONDS) -> list[IncidentAnalysis]:
        if not 1 <= window_seconds <= 3600:
            raise HTTPException(status_code=422, detail="window_seconds must be between 1 and 3600")
        return analysis.analyze(store.list_events(), store.list_edges(), window_seconds)

    @app.get("/intelligence/anomalies", response_model=list[AnomalyOut])
    def anomalies(
        device_id: str | None = None,
        metric_name: str | None = None,
        only_anomalies: bool = False,
        window: int = 30,
        threshold: float = 3.5,
    ) -> list[AnomalyOut]:
        """Robust z-score anomaly scores for stored telemetry (model robust_zscore_v1)."""
        if not 10 <= window <= 1000 or not 0 < threshold <= 20:
            raise HTTPException(status_code=422, detail="window must be 10-1000 and threshold 0-20")
        if device_id is not None:
            _require_device(store, device_id)
        rows = store.list_telemetry(device_id)
        if metric_name is not None:
            rows = [r for r in rows if r.metric_name == metric_name]
        results = analysis.score_anomalies(rows, window=window, threshold=threshold)
        return [r for r in results if r.is_anomaly] if only_anomalies else results

    @app.post("/incidents/sync", response_model=SyncResult)
    def sync_incidents(window_seconds: int = analysis.DEFAULT_WINDOW_SECONDS) -> SyncResult:
        """Correlate stored events into incidents, persist them, and open a human ticket
        for each incident at or above the ticket severity that does not have one yet."""
        if not 1 <= window_seconds <= 3600:
            raise HTTPException(status_code=422, detail="window_seconds must be between 1 and 3600")
        now = _now()
        created, updated = [], []
        tickets: list[TicketMapping] = []
        errors: dict[str, str] = {}
        for inc in analysis.analyze(store.list_events(), store.list_edges(), window_seconds):
            (created if store.upsert_incident(inc, now) else updated).append(inc.incident_id)
            if ticket_provider is None or store.get_ticket_mapping(inc.incident_id) is not None:
                continue
            if not analysis.severity_at_least(inc.severity, settings.ticket_min_severity):
                continue
            result = _open_ticket(inc)
            if isinstance(result, str):
                errors[inc.incident_id] = result
            else:
                tickets.append(result)
        return SyncResult(
            incidents_created=created,
            incidents_updated=updated,
            tickets_created=tickets,
            ticket_errors=errors,
            ticketing="enabled" if ticket_provider else "disabled",
        )

    def _now() -> datetime:
        return clock() if clock else datetime.now(timezone.utc)

    def _open_ticket(inc, note: str | None = None) -> TicketMapping | str:
        """Open one osTicket ticket for an incident. Returns the mapping, or an error string."""
        try:
            number = ticket_provider.create_ticket(*analysis.ticket_text(inc, note))
        except TicketError as exc:
            store.set_ticket_error(inc.incident_id, str(exc))
            return str(exc)
        mapping = TicketMapping(
            incident_id=inc.incident_id,
            provider=ticket_provider.provider,
            external_ticket_id=number,
            created_at=_now(),
        )
        store.insert_ticket_mapping(mapping)
        return mapping

    def _awaiting_verification(device_id: str | None = None) -> list[Execution]:
        """Latest completed execution of every incident in `verifying`."""
        waiting = []
        for inc in store.list_incidents():
            if inc.status != "verifying":
                continue
            done = [e for e in store.list_executions(inc.incident_id) if e.status == "completed"]
            if done and (device_id is None or done[-1].device_id == device_id):
                waiting.append(done[-1])
        return waiting

    def _record_verification(execution: Execution, healthy: bool, summary: str) -> VerifyOutcome:
        """Store one monitoring observation and move the incident:
        healthy -> resolved; unhealthy after the deadline -> escalated (+ human ticket);
        unhealthy before the deadline -> stays verifying (Zabbix may still be catching up)."""
        now = _now()
        result = VerificationResult(
            execution_id=execution.execution_id,
            incident_id=execution.incident_id,
            device_id=execution.device_id,
            healthy=healthy,
            observed_at=now,
            summary=summary,
        )
        store.insert_verification(result)
        status = "verifying"
        ticket, ticket_error = None, None
        finished = execution.timestamps.finished_at or now
        if healthy:
            status = "resolved"
        elif (now - finished).total_seconds() >= settings.verify_timeout_seconds:
            status = "escalated"
        store.set_incident_status(execution.incident_id, status, now)
        if status == "escalated" and ticket_provider is not None:
            ticket = store.get_ticket_mapping(execution.incident_id)
            if ticket is None:
                inc = store.get_incident(execution.incident_id)
                note = (
                    f"Automated remediation {execution.execution_id} ({execution.playbook_id}) completed, "
                    f"but Zabbix still reports {execution.device_id} unhealthy after "
                    f"{settings.verify_timeout_seconds}s. Human action required."
                )
                opened = _open_ticket(inc, note)
                ticket, ticket_error = (None, opened) if isinstance(opened, str) else (opened, None)
        return VerifyOutcome(verification=result, incident_status=status, ticket=ticket, ticket_error=ticket_error)

    def _verify_with_zabbix(execution: Execution) -> VerifyOutcome:
        if zabbix_api is None:
            raise HTTPException(status_code=503, detail="Zabbix API is not configured (NMS_ZABBIX_API_URL/TOKEN)")
        try:
            problems = zabbix_api.open_problems(execution.device_id)
        except ZabbixApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        if problems:
            names = ", ".join(p.get("name", "?") for p in problems[:3])
            return _record_verification(execution, False, f"Zabbix reports {len(problems)} open problem(s): {names}")
        return _record_verification(execution, True, "Zabbix reports no open problems")

    @app.post("/executions/{execution_id}/verify", response_model=VerifyOutcome)
    def verify_execution(execution_id: str) -> VerifyOutcome:
        execution = store.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail=f"Unknown execution_id {execution_id}")
        waiting = {e.execution_id for e in _awaiting_verification()}
        if execution_id not in waiting:
            raise HTTPException(status_code=409, detail="Execution is not awaiting verification")
        return _verify_with_zabbix(execution)

    @app.post("/verification/sweep", response_model=list[VerifyOutcome])
    def verification_sweep() -> list[VerifyOutcome]:
        """Verify every incident in `verifying`. Call periodically (e.g. every 30 s)."""
        return [_verify_with_zabbix(e) for e in _awaiting_verification()]

    # ---- Grafana feeds (M13): flat, read-only tables for the Infinity data source ----

    @app.get("/grafana/summary", response_model=list[GrafanaSummary])
    def grafana_summary() -> list[GrafanaSummary]:
        incidents = store.list_incidents()
        executions = store.list_executions()
        verifications = store.list_verifications()
        by_status = {s: sum(i.status == s for i in incidents) for s in
                     ("open", "action_pending", "verifying", "resolved", "escalated")}
        raw = len(store.list_events())
        reduction = round(100 * (1 - len(incidents) / raw), 1) if raw and incidents else 0.0
        return [GrafanaSummary(
            incidents_total=len(incidents),
            **by_status,
            raw_events=raw,
            alert_reduction_percent=reduction,
            remediations_completed=sum(e.status == "completed" for e in executions),
            remediations_failed=sum(e.status == "failed" for e in executions),
            remediations_blocked=sum(e.status == "rejected_by_policy" for e in executions),
            verified_healthy=sum(v.healthy for v in verifications),
            verified_unhealthy=sum(not v.healthy for v in verifications),
        )]

    @app.get("/grafana/incidents", response_model=list[GrafanaIncidentRow])
    def grafana_incidents(status: str | None = None) -> list[GrafanaIncidentRow]:
        rows = []
        for inc in reversed(store.list_incidents()):
            if status and inc.status != status:
                continue
            top = inc.rca.ranked_causes[0] if inc.rca.ranked_causes else None
            execs = store.list_executions(inc.incident_id)
            verifs = store.list_verifications(incident_id=inc.incident_id)
            rows.append(GrafanaIncidentRow(
                incident_id=inc.incident_id,
                created_at=inc.created_at,
                severity=inc.severity,
                status=inc.status,
                affected_devices=", ".join(inc.affected_devices),
                affected_count=len(inc.affected_devices),
                event_count=len(inc.event_ids),
                top_cause=top.device_id if top else None,
                top_cause_score=top.score if top else None,
                top_cause_reason=top.reason if top else None,
                correlation_reason=inc.correlation.reason,
                ticket_id=inc.ticket.external_ticket_id if inc.ticket else None,
                remediation_status=execs[-1].status if execs else None,
                verified_healthy=verifs[-1].healthy if verifs else None,
            ))
        return rows

    @app.get("/grafana/executions", response_model=list[GrafanaExecutionRow])
    def grafana_executions() -> list[GrafanaExecutionRow]:
        rows = []
        for e in reversed(store.list_executions()):
            verifs = store.list_verifications(execution_id=e.execution_id)
            last = verifs[-1] if verifs else None
            rows.append(GrafanaExecutionRow(
                execution_id=e.execution_id,
                incident_id=e.incident_id,
                device_id=e.device_id,
                playbook_id=e.playbook_id,
                policy=e.policy,
                status=e.status,
                reason=e.reason,
                approved_by=e.approved_by,
                requested_at=e.timestamps.requested_at,
                finished_at=e.timestamps.finished_at,
                last_verification=last.summary if last else None,
                last_verified_at=last.observed_at if last else None,
                healthy=last.healthy if last else None,
            ))
        return rows

    @app.get("/verifications", response_model=list[VerificationResult])
    def list_verifications(incident_id: str | None = None, execution_id: str | None = None) -> list[VerificationResult]:
        return store.list_verifications(incident_id, execution_id)

    def _run(execution: Execution) -> Execution:
        device = _require_device(store, execution.device_id)
        playbook = playbooks.get(execution.playbook_id)
        execution.status = "running"
        execution.timestamps.started_at = _now()
        store.save_execution(execution)
        ok, detail = remediation.execute(playbook, device, remediation_transport)
        execution.status = "completed" if ok else "failed"
        execution.detail = detail
        execution.timestamps.finished_at = _now()
        store.save_execution(execution)
        # completed -> monitoring must confirm health (M12); failed -> a human takes over
        store.set_incident_status(execution.incident_id, "verifying" if ok else "escalated", _now())
        return execution

    @app.get("/playbooks", response_model=list[remediation.Playbook])
    def list_playbooks() -> list[remediation.Playbook]:
        return playbooks.all()

    @app.post("/incidents/{incident_id}/remediation", response_model=Execution, status_code=201)
    def request_remediation(incident_id: str, body: RemediationRequest) -> Execution:
        incident = store.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Unknown incident_id {incident_id}")
        if incident.status in ("resolved", "escalated"):
            raise HTTPException(status_code=409, detail=f"Incident is {incident.status}")
        if any(e.status in ("pending", "running") for e in store.list_executions(incident_id)):
            raise HTTPException(status_code=409, detail="A remediation is already pending or running")
        candidates = [c.device_id for c in incident.rca.ranked_causes] + incident.affected_devices
        top = incident.rca.ranked_causes[0].device_id if incident.rca.ranked_causes else None
        device_id = body.device_id or top
        if device_id is None or device_id not in candidates:
            raise HTTPException(status_code=422, detail="device_id must be an affected device or ranked cause")
        device = _require_device(store, device_id)
        playbook = playbooks.get(body.playbook_id)
        if playbook is None:
            raise HTTPException(status_code=404, detail=f"Unknown playbook_id {body.playbook_id}")
        profile = profiles.get(device.profile_id)
        decision = remediation.decide(device, profile, playbook)
        execution = Execution(
            execution_id=f"EXE-{uuid4().hex[:12]}",
            incident_id=incident_id,
            device_id=device_id,
            playbook_id=playbook.playbook_id,
            policy=device.automation_policy,
            status="pending" if decision.status == "run" else decision.status,
            reason=decision.reason,
            timestamps=ExecutionTimestamps(requested_at=_now()),
        )
        store.save_execution(execution)
        if decision.status == "pending":
            store.set_incident_status(incident_id, "action_pending", _now())
        if decision.status == "run":
            execution = _run(execution)
        return execution

    @app.post("/executions/{execution_id}/approve", response_model=Execution)
    def approve(execution_id: str, body: ApprovalRequest) -> Execution:
        execution = _require_pending(execution_id)
        execution.approved_by = body.approved_by
        return _run(execution)

    @app.post("/executions/{execution_id}/reject", response_model=Execution)
    def reject(execution_id: str, body: ApprovalRequest) -> Execution:
        execution = _require_pending(execution_id)
        execution.status = "rejected_by_policy"
        execution.reason = f"rejected by approver {body.approved_by}"
        execution.approved_by = body.approved_by
        execution.timestamps.finished_at = _now()
        store.save_execution(execution)
        store.set_incident_status(execution.incident_id, "escalated", _now())
        return execution

    def _require_pending(execution_id: str) -> Execution:
        execution = store.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail=f"Unknown execution_id {execution_id}")
        if execution.status != "pending" or execution.policy != "require_approval":
            raise HTTPException(status_code=409, detail=f"Execution is {execution.status}, not awaiting approval")
        return execution

    @app.get("/executions", response_model=list[Execution])
    def list_executions(incident_id: str | None = None) -> list[Execution]:
        return store.list_executions(incident_id)

    @app.get("/executions/{execution_id}", response_model=Execution)
    def get_execution(execution_id: str) -> Execution:
        execution = store.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail=f"Unknown execution_id {execution_id}")
        return execution

    @app.get("/incidents", response_model=list[StoredIncident])
    def list_incidents() -> list[StoredIncident]:
        return store.list_incidents()

    @app.get("/incidents/{incident_id}", response_model=StoredIncident)
    def get_incident(incident_id: str) -> StoredIncident:
        incident = store.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Unknown incident_id {incident_id}")
        return incident

    return app


def _require_device(store: Store, device_id: str) -> Device:
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Unknown device_id {device_id}")
    return device


app = create_app(Settings.from_env())
