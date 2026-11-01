# Team start

The repository is public: https://github.com/Saadia-Asghar/Mysterious.fy

Documentation for implementation is on the `dev` branch. `main` remains the previous stable commit until a merge is explicitly approved.

## Read before writing code

1. [../README.md](../README.md)
2. [architecture.md](architecture.md)
3. [data-contracts.md](data-contracts.md)
4. [fyp-specification.md](fyp-specification.md) for the full academic scope
5. [milestones.md](milestones.md) for what is in scope now

Work from `dev`. Create `feature/<name>` from `dev` only when a change should stay isolated. Merge that branch back to `dev` only. Do not open feature work directly against `main`.

## Ownership from the specification

| Area | Owner | Starts |
|---|---|---|
| Grafana and generic visualization | Saadia | Design from the architecture now. Live dashboards after Zabbix has data. |
| Zabbix, device monitoring, controlled self-healing | Zakarya or Ali | Monitoring design now. Installation when the team approves the services milestone. |
| osTicket and incident integration | The other of Zakarya or Ali | Ticket content from the data contracts now. Live tickets after the integration service exists. |
| Intelligence, integration decisions, evaluation | Shared | Contracts and fault scenarios now. Algorithms at their milestones. |
| Architecture, documentation, testing | Shared | This documentation. |

The specification does not assign Zabbix versus osTicket between Zakarya and Ali. Those two people choose the split. It does not change the component boundaries.

## What each workstream can do with the documentation

**Visualization.** Design the five dashboard levels and the variables `$organization`, `$site`, `$zone`, `$device_type`, and `$device`. Plan one camera dashboard. Leave anomaly, RCA, ticket, and verification panels bound to the records in the data contracts. Do not compute those values inside Grafana.

**Monitoring.** Design the `ip_camera_basic` Zabbix template: ICMP availability, latency, packet loss, and the three triggers. Keep camera rules in that template. Do not put real camera addresses in Git. Self-healing design stays on an approved playbook for a test service, followed by a Zabbix health check.

**Incidents.** Define the osTicket fields that match an incident: context, severity, detection time and source, probable cause, affected devices, responsible team, and escalation when automation is not allowed or does not verify.

**Integration.** Implement later against the contracts. The service normalizes Zabbix problems, enriches them, calls intelligence, and either opens a ticket or requests a permitted playbook.

**Intelligence.** Correlation inputs are events plus `depends_on` edges. RCA output is a ranked list on an `incident_id`. The first anomaly model must be interpretable. Do not publish accuracy numbers until an experiment log exists.

## Information the team still needs to supply

- Whether the first endpoint is an authorized camera, a lab host, or a simulator, and its address
- Whether services will run on a lab machine or another host
- Zabbix, Grafana, osTicket, and PostgreSQL versions
- Whether sample identifiers stay `GIKI` / `FCSE` or become neutral lab IDs
- Which person takes Zabbix and which person takes osTicket

Do not invent those values in code or in committed configuration.

## Safety

- Default camera policy is `monitor_only`
- No AI-invented device commands
- No destructive tests on infrastructure the team is not authorized to use
- No secrets in Git
- No fabricated experiment results
