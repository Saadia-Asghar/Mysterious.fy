"""Analytics feeds for Grafana (M13 extension). Pure functions over stored NMS records.

Grafana only displays these numbers; everything is computed here from what the NMS stored.
MTTR counts only incidents whose recovery Zabbix confirmed (first healthy verification), so a
command that merely reported success never shortens it. MTTD is not computed: it needs the
true fault start time, which only a test harness knows.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone

from app.schemas import Device, Event, StoredIncident, VerificationResult


def _day(ts: datetime) -> datetime:
    ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def daily(events: list[Event], incidents: list[StoredIncident]) -> list[dict]:
    rows: dict[datetime, dict] = defaultdict(lambda: {"raw_events": 0, "incidents": 0, "resolved": 0, "escalated": 0})
    for e in events:
        rows[_day(e.started_at)]["raw_events"] += 1
    for inc in incidents:
        r = rows[_day(inc.created_at)]
        r["incidents"] += 1
        r["resolved"] += inc.status == "resolved"
        r["escalated"] += inc.status == "escalated"
    return [{"day": d, **v} for d, v in sorted(rows.items())]


def recovery_times(incidents: list[StoredIncident], verifications: list[VerificationResult]) -> list[dict]:
    first_healthy: dict[str, datetime] = {}
    for v in sorted(verifications, key=lambda v: v.observed_at):
        if v.healthy:
            first_healthy.setdefault(v.incident_id, v.observed_at)
    rows = []
    for inc in incidents:
        done = first_healthy.get(inc.incident_id)
        if inc.status == "resolved" and done is not None:
            rows.append({"incident_id": inc.incident_id, "created_at": inc.created_at, "resolved_at": done,
                         "minutes": round((done - inc.created_at).total_seconds() / 60, 2)})
    return rows


def device_rows(incidents: list[StoredIncident], devices: list[Device]) -> list[dict]:
    known = {d.device_id: d for d in devices}
    affected, causes = Counter(), Counter()
    for inc in incidents:
        affected.update(set(inc.affected_devices))
        if inc.rca.ranked_causes:
            causes[inc.rca.ranked_causes[0].device_id] += 1
    rows = []
    for dev in set(affected) | set(causes):
        d = known.get(dev)
        rows.append({"device_id": dev, "device_type": d.device_type if d else "unknown",
                     "site_id": d.site_id if d else "unknown",
                     "incidents": affected[dev], "times_probable_cause": causes[dev]})
    return sorted(rows, key=lambda r: (-r["times_probable_cause"], -r["incidents"], r["device_id"]))


def cause_types(incidents: list[StoredIncident], devices: list[Device]) -> list[dict]:
    known = {d.device_id: d.device_type for d in devices}
    counts = Counter(known.get(inc.rca.ranked_causes[0].device_id, "unknown") if inc.rca.ranked_causes else "none"
                     for inc in incidents)
    return [{"cause_type": t, "incidents": n} for t, n in counts.most_common()]


def site_rows(incidents: list[StoredIncident], devices: list[Device]) -> list[dict]:
    site_of = {d.device_id: d.site_id for d in devices}
    rows: dict[str, dict] = {}
    for d in devices:
        rows.setdefault(d.site_id, {"site_id": d.site_id, "devices": 0, "incidents": 0, "open": 0,
                                    "resolved": 0, "escalated": 0})["devices"] += 1
    for inc in incidents:
        for site in {site_of.get(dev, "unknown") for dev in inc.affected_devices}:
            r = rows.setdefault(site, {"site_id": site, "devices": 0, "incidents": 0, "open": 0,
                                       "resolved": 0, "escalated": 0})
            r["incidents"] += 1
            if inc.status in ("open", "action_pending", "verifying"):
                r["open"] += 1
            elif inc.status in ("resolved", "escalated"):
                r[inc.status] += 1
    return sorted(rows.values(), key=lambda r: (-r["incidents"], r["site_id"]))
