from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.profiles import ProfileCatalog
from app.schemas import Device, DeviceCreate, DeviceProfile, Event, EventCreate, Telemetry, TelemetryCreate
from app.settings import Settings
from app.store import DeviceAlreadyExists, EventAlreadyExists, Store, new_event_id

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings) -> FastAPI:
    store = Store(settings.database_path)
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

    return app


def _require_device(store: Store, device_id: str) -> Device:
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Unknown device_id {device_id}")
    return device


app = create_app(Settings.from_env())
