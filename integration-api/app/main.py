import hmac
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import analysis, zabbix
from app.osticket import OsTicketClient, TicketError
from app.profiles import ProfileCatalog
from app.schemas import (
    Device,
    DeviceCreate,
    DeviceProfile,
    Event,
    EventCreate,
    AnomalyOut,
    IncidentAnalysis,
    StoredIncident,
    SyncResult,
    TicketMapping,
    Telemetry,
    TelemetryCreate,
    TopologyEdge,
)
from app.settings import Settings
from app.store import DeviceAlreadyExists, EdgeAlreadyExists, EventAlreadyExists, Store, new_event_id
from app.zabbix import ZabbixWebhook

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings, ticket_provider: OsTicketClient | None = None) -> FastAPI:
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
            # Recovery. Stored and used for verification from M12 onward; acknowledged for now.
            response.status_code = 202
            return {"status": "recovery_received", "event_id": event_id}
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
        now = datetime.now(timezone.utc)
        created, updated = [], []
        tickets: list[TicketMapping] = []
        errors: dict[str, str] = {}
        for inc in analysis.analyze(store.list_events(), store.list_edges(), window_seconds):
            (created if store.upsert_incident(inc, now) else updated).append(inc.incident_id)
            if ticket_provider is None or store.get_ticket_mapping(inc.incident_id) is not None:
                continue
            if not analysis.severity_at_least(inc.severity, settings.ticket_min_severity):
                continue
            try:
                number = ticket_provider.create_ticket(*analysis.ticket_text(inc))
            except TicketError as exc:
                errors[inc.incident_id] = str(exc)
                store.set_ticket_error(inc.incident_id, str(exc))
                continue
            mapping = TicketMapping(
                incident_id=inc.incident_id,
                provider=ticket_provider.provider,
                external_ticket_id=number,
                created_at=now,
            )
            store.insert_ticket_mapping(mapping)
            tickets.append(mapping)
        return SyncResult(
            incidents_created=created,
            incidents_updated=updated,
            tickets_created=tickets,
            ticket_errors=errors,
            ticketing="enabled" if ticket_provider else "disabled",
        )

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
