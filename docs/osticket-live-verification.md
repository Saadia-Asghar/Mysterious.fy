
# Live osTicket Integration Verification

**Contributor:** Ali Abbas  
**Date:** 26 November 2026  
**Milestone:** M6 - Live Ticketing Integration  
**Branch:** feature/osticket-live

## 1. Objective

The objective of this task was to verify the existing NMS ticketing
connector against a live osTicket instance instead of relying only
on simulated API responses.

The verification covers API authentication, incident synchronization,
automatic ticket generation, error handling, root cause information,
and duplicate ticket prevention.

## 2. Testing Environment

| Component | Configuration |
|---|---|
| Operating System | Windows |
| Terminal | PowerShell |
| Container Platform | Docker Desktop |
| osTicket Version | 1.18.4 |
| Database | MariaDB 10.11 |
| Backend Framework | FastAPI |
| API Server | Uvicorn |
| HTTP Client | HTTPX |
| NMS Integration API | http://127.0.0.1:8000 |
| osTicket Server | http://127.0.0.1:8081 |
| Docker Gateway | 172.18.0.1 |

## 3. Implementation and Configuration

The following steps were completed during live integration testing:

1. Deployed osTicket and MariaDB using Docker.
2. Verified that the database container was healthy.
3. Accessed the osTicket staff and administration panels.
4. Configured IP-bound API authentication.
5. Identified the actual caller IP through Docker logs.
6. Investigated and resolved HTTP 401 authentication errors.
7. Verified direct API connectivity using Python HTTPX.
8. Configured the NMS environment variables.
9. Started the NMS integration API using Uvicorn.
10. Created a test company and network site.
11. Registered a test network switch.
12. Submitted a simulated network failure.
13. Synchronized incidents and verified automatic ticket creation.
14. Tested repeated incident synchronization.
15. Added a reusable verification script.

## 4. Test Device Configuration

| Parameter | Value |
|---|---|
| Company | GIKI Network Solutions |
| Site | GIKI Network Lab |
| Site ID | GIKI-LAB-01 |
| Device ID | SW-GIKI-001 |
| Device Name | Test Core Switch |
| Device Type | Network Switch |
| Device Profile | network_switch_basic |
| Management Address | 192.0.2.10 |
| Automation Policy | Monitor Only |

The management address is a reserved documentation address.
The device was registered specifically for simulated testing.

## 5. Simulated Network Failure

The following event was submitted through the NMS integration API:

```json
{
  "event_id": "LIVE-OSTICKET-001",
  "device_id": "SW-GIKI-001",
  "event_type": "device_unreachable",
  "severity": "high",
  "started_at": "2026-11-26T14:02:00Z",
  "source": "simulation"
}
```

The event was processed through the incident synchronization
endpoint using the following configuration:

- Correlation window: 120 seconds
- Correlation method: upstream_anchor_quorum_v2
- Root cause analysis method: topology_time_v1

## 6. Live Ticket Creation Results

| Parameter | Result |
|---|---|
| Direct API Response | HTTP 201 Created |
| Direct API Test Ticket | 211534 |
| Automatic NMS Ticket | 455897 |
| Incident ID | INC-LIVE-OSTICKET-001 |
| Affected Device | SW-GIKI-001 |
| Incident Severity | High |
| Probable Root Cause | SW-GIKI-001 |
| RCA Heuristic Score | 1.00 |
| Ticket Creation Method | Automatic |
| Automation Policy | Human Handling |
| Integration Status | Successful |

The automatically generated ticket contained the incident ID,
severity, affected device, event details, correlation results,
and probable root cause information.

The RCA score is a heuristic ranking score and should not be
interpreted as a statistical probability.

## 7. API Authentication Troubleshooting

Initial ticket creation attempts returned the following error:

HTTP 401 - Valid API key required

The following troubleshooting steps were performed:

- Inspected Docker container logs.
- Identified 172.18.0.1 as the caller IP address.
- Verified API key status and ticket creation permissions.
- Replaced the previous API key.
- Investigated PowerShell HTTP request errors.
- Tested the API directly using Python HTTPX.
- Updated the NMS environment configuration.
- Restarted the Uvicorn application server.

The direct HTTPX request returned HTTP 201 Created,
confirming successful authentication.

Following the configuration update, the NMS successfully
generated an automatic incident ticket in osTicket.

The exact underlying cause of the earlier authentication
failure was not conclusively isolated.

## 8. Automated Testing

The existing osTicket automated tests were executed using:

```bash
python -m pytest tests/test_osticket.py -v
```

| Test | Result |
|---|---|
| Switch outage creates one meaningful ticket | Passed |
| Incident synchronization is idempotent | Passed |
| Failed ticket creation supports retry | Passed |
| Low-severity incidents do not create tickets | Passed |
| Ticketing disabled without configuration | Passed |
| Unknown incident returns HTTP 404 | Passed |

Total tests: 6

Passed: 6

Failed: 0

A dependency deprecation warning was reported but did not
cause any test failures.

## 9. Live Duplicate Ticket Prevention

Repeated incident synchronization was tested against the
running osTicket instance.

The verification script executed the incident synchronization
endpoint twice using the existing test incident.

Repeated incident synchronization completed successfully
without new ticket creation or ticket errors.

The existing incident was updated instead of creating
another incident.

The second synchronization returned no newly created tickets,
demonstrating application-level duplicate prevention for
the tested incident.

The osTicket dashboard can also be inspected to independently
confirm that no duplicate external ticket was created.

## 10. Live Verification Script

A reusable verification script was added at:

`scripts/verify_osticket_live.py`

The script performs the following operations:

- Connects to the running NMS integration API.
- Executes incident synchronization twice.
- Checks whether ticketing is enabled.
- Checks for ticket creation errors.
- Checks for unexpected new tickets during repeated synchronization.
- Reports the verification result.

Run the script from the repository root:

```bash
python scripts/verify_osticket_live.py
```

Windows users can also execute:

```powershell
.\.venv\Scripts\python.exe scripts/verify_osticket_live.py
```

The NMS integration API and osTicket containers must be running.

A valid test incident must already exist before executing
the verification script.

The script does not independently generate a network failure
or verify the external osTicket database.

## 11. Environment Configuration

The following environment variables are required for
the osTicket connector:

```env
NMS_OSTICKET_URL=http://127.0.0.1:8081
NMS_OSTICKET_API_KEY=YOUR_API_KEY
NMS_OSTICKET_REPORTER_EMAIL=nms@example.com
```

The API key must be registered against the actual caller IP
address and must have ticket creation permissions.

The caller IP may vary between Docker environments.
Docker logs should be inspected before configuring the key.

## 12. Security Considerations

- API keys must not be committed to GitHub.
- Database passwords must remain in the local .env file.
- The .env file must remain excluded through .gitignore.
- API keys should be restricted to authorized caller IP addresses.
- Exposed API keys should be replaced.
- Network monitoring must only target authorized devices.
- Credentials should not appear in documentation or screenshots.

## 13. Limitations and Future Improvements

The following improvements remain within the future scope:

- Verify ticket generation from actual Zabbix-detected failures.
- Map NMS incident severity to osTicket ticket priority.
- Investigate automatic assignment to responsible teams.
- Support ticket updates following device recovery.
- Investigate bidirectional ticket status synchronization.
- Evaluate SLA-based escalation.
- Extend live testing to multiple connected devices.
- Add automated external ticket verification.

These improvements should be evaluated against the existing
repository implementation before development.

The current live verification used a simulated network failure
rather than an actual Zabbix-detected network outage.

## 14. Contribution Summary

This contribution extends the existing simulated osTicket
verification by testing the connector against a running
Docker-hosted osTicket instance.

The contribution includes:

- Live osTicket deployment and configuration.
- API authentication troubleshooting.
- Direct API connectivity verification.
- Automatic incident-based ticket generation.
- Verification of incident information and root cause details.
- Repeated synchronization testing.
- A reusable live verification script.
- Setup, security, and troubleshooting documentation.

## 15. Conclusion

The existing NMS ticketing connector was successfully verified
against a live osTicket deployment.

A simulated network switch failure was processed by the NMS
integration service and resulted in the automatic creation
of osTicket ticket 455897.

The generated ticket included incident details, severity,
affected devices, event correlation, and probable root causes.

All six existing automated tests passed, and repeated
synchronization completed without ticket creation errors
or unexpected additional tickets.

This verification demonstrates that the existing ticketing
connector can operate against a real osTicket instance,
providing a foundation for future live network monitoring
and automated incident management.
