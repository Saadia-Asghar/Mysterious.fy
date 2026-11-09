# osTicket ticketing

osTicket handles the human incident workflow: assignment, investigation, escalation, and anything automation is not allowed to fix.

## How the NMS uses it (M6)

`POST /incidents/sync` on the integration API:

1. Correlates stored events into incidents (M8) and ranks probable causes (M9).
2. Saves each incident in the NMS database. `incident_id` is `INC-<first event_id>`.
3. For each incident at or above `NMS_TICKET_MIN_SEVERITY` without a ticket, opens **one** osTicket ticket and stores the mapping `incident_id → external_ticket_id`.
4. If osTicket is down or rejects the key, the incident is still saved, the error is stored on it (`ticket_error`), and the next sync retries.

Re-running sync never opens a second ticket for the same incident. New events that join an incident update it in place.

The ticket subject names the incident, severity, number of affected devices and the probable cause. The body lists devices, events, the correlation reason and the ranked causes with their reasons.

`GET /incidents` and `GET /incidents/{incident_id}` show each incident with its ticket.

## Setup

1. Start the stack (see `docker/README.md`) and open osTicket at http://localhost:8081.
2. Admin Panel → Manage → API Keys → Add New. **IP address** must be the address the integration API connects from (when the API runs on the host and osTicket in Docker, this is usually the Docker gateway, e.g. `172.17.0.1`; check the osTicket log if requests are rejected). Tick *Can Create Tickets*.
3. Put the key in `.env` as `NMS_OSTICKET_API_KEY`, set `NMS_OSTICKET_URL`, restart the API.
4. Trigger an event, call `POST /incidents/sync`, and confirm the ticket appears in the staff panel.

Status: implemented and tested against a fake osTicket (`tests/test_osticket.py`). Not yet verified against a live osTicket (needs M1 running).
