import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import json

from app.schemas import (
    Device,
    Event,
    Execution,
    IncidentAnalysis,
    StoredIncident,
    Telemetry,
    TelemetryCreate,
    TicketMapping,
    TopologyEdge,
    VerificationResult,
)


class DeviceAlreadyExists(Exception):
    pass


class EventAlreadyExists(Exception):
    pass


class EdgeAlreadyExists(Exception):
    pass


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    zone_id TEXT NOT NULL,
                    management_address TEXT NOT NULL,
                    responsible_team TEXT NOT NULL,
                    automation_policy TEXT NOT NULL,
                    enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id)
                );
                CREATE TABLE IF NOT EXISTS telemetry (
                    telemetry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id)
                );
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ticket_error TEXT
                );
                CREATE TABLE IF NOT EXISTS ticket_mappings (
                    incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id),
                    provider TEXT NOT NULL,
                    external_ticket_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
                    status TEXT NOT NULL,
                    body_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS verifications (
                    verification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL REFERENCES executions(execution_id),
                    incident_id TEXT NOT NULL,
                    body_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS topology_edges (
                    from_device_id TEXT NOT NULL,
                    to_device_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    PRIMARY KEY (from_device_id, to_device_id, relationship),
                    FOREIGN KEY (from_device_id) REFERENCES devices(device_id),
                    FOREIGN KEY (to_device_id) REFERENCES devices(device_id)
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error, and always close.
        (sqlite3's own context manager only commits; it never closes the connection.)"""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def count_devices(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0])

    def insert_device(self, device: Device) -> None:
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO devices (
                        device_id, name, device_type, profile_id, organization_id,
                        site_id, zone_id, management_address, responsible_team,
                        automation_policy, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device.device_id,
                        device.name,
                        device.device_type,
                        device.profile_id,
                        device.organization_id,
                        device.site_id,
                        device.zone_id,
                        device.management_address,
                        device.responsible_team,
                        device.automation_policy,
                        int(device.enabled),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DeviceAlreadyExists(device.device_id) from exc

    def list_devices(self) -> list[Device]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY device_id").fetchall()
        return [self._device(row) for row in rows]

    def get_device(self, device_id: str) -> Device | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return self._device(row) if row else None

    def insert_event(self, event: Event) -> None:
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO events (event_id, device_id, event_type, severity, started_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.device_id,
                        event.event_type,
                        event.severity,
                        event.started_at.isoformat(),
                        event.source,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise EventAlreadyExists(event.event_id) from exc

    def get_event(self, event_id: str) -> Event | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._event(row) if row else None

    def list_events(self) -> list[Event]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY started_at, event_id").fetchall()
        return [self._event(row) for row in rows]

    def insert_telemetry(self, reading: TelemetryCreate) -> Telemetry:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO telemetry (device_id, metric_name, value, unit, timestamp, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.device_id,
                    reading.metric_name,
                    reading.value,
                    reading.unit,
                    reading.timestamp.isoformat(),
                    reading.source,
                ),
            )
            telemetry_id = int(cursor.lastrowid)
        stored = Telemetry(telemetry_id=telemetry_id, **reading.model_dump())
        return stored

    def list_telemetry(self, device_id: str | None = None) -> list[Telemetry]:
        query = "SELECT * FROM telemetry"
        params: tuple[str, ...] = ()
        if device_id is not None:
            query += " WHERE device_id = ?"
            params = (device_id,)
        query += " ORDER BY timestamp, telemetry_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Telemetry(
                telemetry_id=row["telemetry_id"],
                device_id=row["device_id"],
                metric_name=row["metric_name"],
                value=row["value"],
                unit=row["unit"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                source=row["source"],
            )
            for row in rows
        ]

    def insert_edge(self, edge: TopologyEdge) -> None:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO topology_edges (from_device_id, to_device_id, relationship) VALUES (?, ?, ?)",
                    (edge.from_device_id, edge.to_device_id, edge.relationship),
                )
            except sqlite3.IntegrityError as exc:
                raise EdgeAlreadyExists(f"{edge.from_device_id}->{edge.to_device_id}") from exc

    def list_edges(self) -> list[TopologyEdge]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM topology_edges ORDER BY from_device_id, to_device_id"
            ).fetchall()
        return [TopologyEdge(**dict(row)) for row in rows]

    def upsert_incident(self, analysis: IncidentAnalysis, now: datetime) -> bool:
        """Insert a new incident or refresh its analysis. Returns True if it was new.
        Status belongs to the incident lifecycle and is never overwritten by re-analysis."""
        body = analysis.model_dump_json()
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM incidents WHERE incident_id = ?", (analysis.incident_id,)
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE incidents SET analysis_json = ?, updated_at = ? WHERE incident_id = ?",
                    (body, now.isoformat(), analysis.incident_id),
                )
                return False
            conn.execute(
                "INSERT INTO incidents (incident_id, status, analysis_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (analysis.incident_id, analysis.status, body, analysis.created_at.isoformat(), now.isoformat()),
            )
            return True

    def set_ticket_error(self, incident_id: str, error: str | None) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE incidents SET ticket_error = ? WHERE incident_id = ?", (error, incident_id))

    def insert_ticket_mapping(self, mapping: TicketMapping) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ticket_mappings (incident_id, provider, external_ticket_id, created_at)"
                " VALUES (?, ?, ?, ?)",
                (mapping.incident_id, mapping.provider, mapping.external_ticket_id, mapping.created_at.isoformat()),
            )
            conn.execute("UPDATE incidents SET ticket_error = NULL WHERE incident_id = ?", (mapping.incident_id,))

    def get_ticket_mapping(self, incident_id: str) -> TicketMapping | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ticket_mappings WHERE incident_id = ?", (incident_id,)).fetchone()
        return TicketMapping(**dict(row)) if row else None

    def list_incidents(self) -> list[StoredIncident]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM incidents ORDER BY created_at, incident_id").fetchall()
        return [self._incident(row) for row in rows]

    def get_incident(self, incident_id: str) -> StoredIncident | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return self._incident(row) if row else None

    def _incident(self, row: sqlite3.Row) -> StoredIncident:
        data = json.loads(row["analysis_json"])
        data.update(
            status=row["status"],
            updated_at=row["updated_at"],
            ticket=self.get_ticket_mapping(row["incident_id"]),
            ticket_error=row["ticket_error"],
        )
        return StoredIncident(**data)

    def set_incident_status(self, incident_id: str, status: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE incidents SET status = ?, updated_at = ? WHERE incident_id = ?",
                (status, now.isoformat(), incident_id),
            )

    def save_execution(self, execution: Execution) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO executions (execution_id, incident_id, status, body_json) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(execution_id) DO UPDATE SET status = excluded.status, body_json = excluded.body_json",
                (execution.execution_id, execution.incident_id, execution.status, execution.model_dump_json()),
            )

    def get_execution(self, execution_id: str) -> Execution | None:
        with self._connect() as conn:
            row = conn.execute("SELECT body_json FROM executions WHERE execution_id = ?", (execution_id,)).fetchone()
        return Execution.model_validate_json(row[0]) if row else None

    def list_executions(self, incident_id: str | None = None) -> list[Execution]:
        query, params = "SELECT body_json FROM executions", ()
        if incident_id is not None:
            query, params = query + " WHERE incident_id = ?", (incident_id,)
        with self._connect() as conn:
            rows = conn.execute(query + " ORDER BY rowid", params).fetchall()
        return [Execution.model_validate_json(r[0]) for r in rows]

    def insert_verification(self, v: VerificationResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO verifications (execution_id, incident_id, body_json) VALUES (?, ?, ?)",
                (v.execution_id, v.incident_id, v.model_dump_json()),
            )

    def list_verifications(self, incident_id: str | None = None, execution_id: str | None = None) -> list[VerificationResult]:
        query, params = "SELECT body_json FROM verifications WHERE 1=1", []
        if incident_id is not None:
            query += " AND incident_id = ?"
            params.append(incident_id)
        if execution_id is not None:
            query += " AND execution_id = ?"
            params.append(execution_id)
        with self._connect() as conn:
            rows = conn.execute(query + " ORDER BY verification_id", params).fetchall()
        return [VerificationResult.model_validate_json(r[0]) for r in rows]

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            device_id=row["device_id"],
            name=row["name"],
            device_type=row["device_type"],
            profile_id=row["profile_id"],
            organization_id=row["organization_id"],
            site_id=row["site_id"],
            zone_id=row["zone_id"],
            management_address=row["management_address"],
            responsible_team=row["responsible_team"],
            automation_policy=row["automation_policy"],
            enabled=bool(row["enabled"]),
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> Event:
        return Event(
            event_id=row["event_id"],
            device_id=row["device_id"],
            event_type=row["event_type"],
            severity=row["severity"],
            started_at=datetime.fromisoformat(row["started_at"]),
            source=row["source"],
        )


def new_event_id() -> str:
    from uuid import uuid4

    return f"EVT-{uuid4().hex[:12]}"
