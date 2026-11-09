"""osTicket connector (M6): opens a human ticket for an NMS incident.

Uses osTicket's REST API: POST {base}/api/tickets.json with header X-API-Key.
osTicket API keys are bound to the caller's IP address; create the key in
Admin Panel -> Manage -> API Keys for the integration service's address.
On success osTicket returns 201 and the ticket number as plain text.
"""
from dataclasses import dataclass

import httpx


class TicketError(RuntimeError):
    pass


@dataclass
class OsTicketClient:
    base_url: str
    api_key: str
    reporter_email: str
    reporter_name: str = "NMS Integration"
    transport: httpx.BaseTransport | None = None
    timeout: float = 10.0

    provider = "osticket"

    def create_ticket(self, subject: str, message: str) -> str:
        url = self.base_url.rstrip("/") + "/api/tickets.json"
        payload = {
            "name": self.reporter_name,
            "email": self.reporter_email,
            "subject": subject[:255],
            "message": "data:text/plain;charset=utf-8," + message,
            "source": "API",
            "alert": True,
            "autorespond": False,
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                r = client.post(url, json=payload, headers={"X-API-Key": self.api_key})
        except httpx.HTTPError as exc:
            raise TicketError(f"osTicket unreachable: {exc}") from exc
        if r.status_code != 201:
            raise TicketError(f"osTicket returned HTTP {r.status_code}: {r.text[:200]}")
        ticket_id = r.text.strip()
        if not ticket_id:
            raise TicketError("osTicket returned an empty ticket number")
        return ticket_id
