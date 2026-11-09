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


class TicketMapping(BaseModel):
    incident_id: str
    provider: str
    external_ticket_id: str
    created_at: datetime


class StoredIncident(IncidentAnalysis):
    status: Literal["open", "action_pending", "verifying", "resolved", "escalated"]
    updated_at: datetime
    ticket: TicketMapping | None = None
    ticket_error: str | None = None


class SyncResult(BaseModel):
    incidents_created: list[str]
    incidents_updated: list[str]
    tickets_created: list[TicketMapping]
    ticket_errors: dict[str, str]
    ticketing: Literal["enabled", "disabled"]


class AnomalyOut(BaseModel):
    device_id: str
    metric_name: str
    timestamp: datetime
    value: float
    baseline_median: float
    robust_z: float
    anomaly_score: float
    is_anomaly: bool
    direction: Literal["high", "low", "normal"]
    model_version: str


ExecutionStatus = Literal["pending", "rejected_by_policy", "running", "completed", "failed"]


class RemediationRequest(BaseModel):
    playbook_id: Identifier
    device_id: Identifier | None = None


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)


class ExecutionTimestamps(BaseModel):
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Execution(BaseModel):
    execution_id: str
    incident_id: str
    device_id: str
    playbook_id: str
    policy: Policy
    status: ExecutionStatus
    reason: str
    detail: str | None = None
    approved_by: str | None = None
    timestamps: ExecutionTimestamps


class VerificationResult(BaseModel):
    execution_id: str
    incident_id: str
    device_id: str
    source: Literal["zabbix"] = "zabbix"
    healthy: bool
    observed_at: datetime
    summary: str


class VerifyOutcome(BaseModel):
    verification: VerificationResult
    incident_status: str
    ticket: TicketMapping | None = None
    ticket_error: str | None = None


class GrafanaSummary(BaseModel):
    incidents_total: int
    open: int
    action_pending: int
    verifying: int
    resolved: int
    escalated: int
    raw_events: int
    alert_reduction_percent: float
    remediations_completed: int
    remediations_failed: int
    remediations_blocked: int
    verified_healthy: int
    verified_unhealthy: int


class GrafanaIncidentRow(BaseModel):
    incident_id: str
    created_at: datetime
    severity: str
    status: str
    affected_devices: str
    affected_count: int
    event_count: int
    top_cause: str | None
    top_cause_score: float | None
    top_cause_reason: str | None
    correlation_reason: str
    ticket_id: str | None
    remediation_status: str | None
    verified_healthy: bool | None


class GrafanaExecutionRow(BaseModel):
    execution_id: str
    incident_id: str
    device_id: str
    playbook_id: str
    policy: str
    status: str
    reason: str
    approved_by: str | None
    requested_at: datetime
    finished_at: datetime | None
    last_verification: str | None
    last_verified_at: datetime | None
    healthy: bool | None
