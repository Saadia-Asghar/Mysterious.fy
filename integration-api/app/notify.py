"""Email alerts for tickets.

Every alert is first written to the `notifications` table (an outbox), then sent by SMTP.
So nothing is lost if the mail server is down: failed rows are retried on the next cycle
(up to MAX_ATTEMPTS), and every alert stays on record with its status.

SMTP is configured only through the environment / local .env (NMS_SMTP_*). Without it,
alerts are recorded with status `disabled` and nothing is sent.
"""
from __future__ import annotations

import logging
import smtplib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Callable

log = logging.getLogger("nms.notify")
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    sender: str = "nms@example.invalid"
    starttls: bool = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Notifier:
    def __init__(self, store, smtp: SmtpConfig | None, send: Callable[[EmailMessage], None] | None = None,
                 portal_url: str = "http://localhost:8000/app", background: bool = True):
        self.store = store
        self.smtp = smtp
        self.portal_url = portal_url.rstrip("/")
        self._send = send or self._smtp_send
        self._background = background
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.smtp is not None

    def init(self) -> None:
        with self.store._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id TEXT NOT NULL,
                    ticket_id INTEGER,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,          -- pending, sent, failed, disabled
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS notifications_status ON notifications(status);
                """
            )

    def queue(self, org_id: str, ticket_id: int | None, recipients: list[str], subject: str, body: str) -> None:
        if not recipients:
            return
        status = "pending" if self.enabled else "disabled"
        link = f"{self.portal_url}#/tickets/view?id={ticket_id}" if ticket_id else self.portal_url
        with self.store._connect() as conn:
            conn.executemany(
                "INSERT INTO notifications (organization_id, ticket_id, recipient, subject, body, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(org_id, ticket_id, r, subject, f"{body}\n\nOpen the ticket: {link}\n", status, _now())
                 for r in sorted(set(recipients))])
        if self.enabled:
            if self._background:
                threading.Thread(target=self.flush, daemon=True).start()
            else:
                self.flush()

    def flush(self) -> int:
        """Send pending (and retry failed) alerts. Returns how many were sent."""
        if not self.enabled:
            return 0
        sent = 0
        with self._lock:
            with self.store._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE status IN ('pending', 'failed') AND attempts < ?"
                    " ORDER BY notification_id", (MAX_ATTEMPTS,)).fetchall()
            for r in rows:
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = self.smtp.sender, r["recipient"], r["subject"]
                msg.set_content(r["body"])
                try:
                    self._send(msg)
                    status, error, sent_at = "sent", None, _now()
                    sent += 1
                except Exception as exc:  # keep it on record and retry next cycle
                    status, error, sent_at = "failed", str(exc)[:300], None
                    log.warning("email to %s failed: %s", r["recipient"], exc)
                with self.store._connect() as conn:
                    conn.execute("UPDATE notifications SET status=?, error=?, sent_at=?, attempts=attempts+1"
                                 " WHERE notification_id=?", (status, error, sent_at, r["notification_id"]))
        return sent

    def list(self, org_id: str | None = None, limit: int = 200) -> list[dict]:
        sql, params = "SELECT * FROM notifications", []
        if org_id:
            sql, params = sql + " WHERE organization_id=?", [org_id]
        with self.store._connect() as conn:
            rows = conn.execute(sql + " ORDER BY notification_id DESC LIMIT ?", (*params, limit)).fetchall()
        return [{k: r[k] for k in r.keys() if k != "body"} for r in rows]

    def _smtp_send(self, msg: EmailMessage) -> None:
        s = self.smtp
        with smtplib.SMTP(s.host, s.port, timeout=20) as client:
            if s.starttls:
                client.starttls()
            if s.user and s.password:
                client.login(s.user, s.password)
            client.send_message(msg)
