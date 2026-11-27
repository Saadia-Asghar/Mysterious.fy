"""Zabbix connector: turns a Zabbix webhook payload into the normalized Event contract.

The payload is produced by the media type in monitoring-zabbix/media-types/nms_webhook.js.
Device identity: the Zabbix host name IS the NMS device_id (e.g. CAM-001).
Event type: taken from the trigger tag `nms_event_type`, which must match a trigger in
the device's profile. Nothing here is camera-specific.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import EventCreate, Severity

ZABBIX_SEVERITIES: dict[str, Severity] = {
    "0": "not_classified",
    "1": "information",
    "2": "warning",
    "3": "average",
    "4": "high",
    "5": "disaster",
    "not classified": "not_classified",
    "information": "information",
    "warning": "warning",
    "average": "average",
    "high": "high",
    "disaster": "disaster",
}


class ZabbixWebhook(BaseModel):
    """Fields sent by the NMS webhook media type. Values arrive as strings from Zabbix macros."""

    eventid: str = Field(pattern=r"^\d+$")
    host: str = Field(min_length=1)
    nms_event_type: str = Field(min_length=1)
    severity: str
    value: Literal["0", "1"]  # 1 = problem, 0 = recovery
    clock: str = Field(pattern=r"^\d+$")


class UnknownSeverity(ValueError):
    pass


def event_id_for(eventid: str) -> str:
    """Stable, traceable ID: the same Zabbix event always maps to the same NMS event."""
    return f"ZBX-{eventid}"


def normalize(payload: ZabbixWebhook) -> EventCreate:
    severity = ZABBIX_SEVERITIES.get(payload.severity.strip().lower())
    if severity is None:
        raise UnknownSeverity(payload.severity)
    return EventCreate(
        event_id=event_id_for(payload.eventid),
        device_id=payload.host,
        event_type=payload.nms_event_type,
        severity=severity,
        started_at=datetime.fromtimestamp(int(payload.clock), tz=timezone.utc),
        source="zabbix",
    )
