from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Policy = Literal["monitor_only", "recommend", "require_approval", "auto_remediate"]
Severity = Literal["not_classified", "information", "warning", "average", "high", "disaster"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


class MetricDefinition(BaseModel):
    metric_name: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class DeviceProfile(BaseModel):
    profile_id: Identifier
    device_type: str = Field(min_length=1)
    connectors: list[str] = Field(min_length=1)
    optional_connectors: list[str] = []
    metrics: list[MetricDefinition] = Field(min_length=1)
    triggers: list[str] = Field(min_length=1)
    dashboard: str = Field(min_length=1)
    capabilities: list[str] = []
    allowed_playbooks: list[str] = []
    default_policy: Policy


class DeviceCreate(BaseModel):
    device_id: Identifier
    name: str = Field(min_length=1)
    device_type: str = Field(min_length=1)
    profile_id: Identifier
    organization_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)
    management_address: str = Field(min_length=1)
    responsible_team: str = Field(min_length=1)
    automation_policy: Policy | None = None
    enabled: bool = True


class Device(DeviceCreate):
    automation_policy: Policy


class EventCreate(BaseModel):
    event_id: Identifier | None = None
    device_id: Identifier
    event_type: str = Field(min_length=1)
    severity: Severity
    started_at: datetime
    source: str = Field(min_length=1)


class Event(BaseModel):
    event_id: Identifier
    device_id: Identifier
    event_type: str
    severity: Severity
    started_at: datetime
    source: str


class TelemetryCreate(BaseModel):
    device_id: Identifier
    metric_name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    timestamp: datetime
    source: str = Field(min_length=1)


class Telemetry(TelemetryCreate):
    telemetry_id: int


class TopologyEdge(BaseModel):
    from_device_id: Identifier
    to_device_id: Identifier
    relationship: Literal["depends_on"] = "depends_on"


class RankedCauseOut(BaseModel):
    device_id: str
    score: float
    reason: str


class CorrelationOut(BaseModel):
    method: str
    reason: str


class RcaOut(BaseModel):
    method: str
    ranked_causes: list[RankedCauseOut]


class IncidentAnalysis(BaseModel):
    incident_id: str
    event_ids: list[str]
    affected_devices: list[str]
    severity: Severity
    status: Literal["open"]
    created_at: datetime
    correlation: CorrelationOut
    rca: RcaOut
