import sqlite3
from datetime import datetime
from pathlib import Path

from app.schemas import Device, Event, Telemetry, TelemetryCreate


class DeviceAlreadyExists(Exception):
    pass


class EventAlreadyExists(Exception):
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
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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
