// Zabbix webhook media type "NMS Integration": sends problem and recovery events to the
// integration API (POST /integrations/zabbix/events).
//
// monitoring-zabbix/provision.py (command: setup) creates this media type from this file and defines
// its parameters: url, token, eventid, host, nms_event_type, severity, value.
// Zabbix host name == NMS device_id (e.g. CAM-001). value: 1 = problem, 0 = recovery.
try {
    var p = JSON.parse(value);
    var body = {
        eventid: p.eventid,
        host: p.host,
        // A recovery message may not expand the tag macro; the API ignores the type on recovery.
        nms_event_type: p.nms_event_type || 'unknown',
        severity: p.severity,
        value: p.value,
        // The EVENT.TIMESTAMP macro does not exist in Zabbix 7.0 LTS (added in 7.2), so the event time is
        // the time this alert is sent, normally within a few seconds of the event.
        clock: String(Math.floor(Date.now() / 1000))
    };
    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    if (p.token) {
        req.addHeader('X-NMS-Webhook-Token: ' + p.token);
    }
    var resp = req.post(p.url, JSON.stringify(body));
    var status = req.getStatus();
    Zabbix.log(4, '[NMS webhook] ' + status + ' ' + resp);
    if (status < 200 || status >= 300) {
        throw 'NMS integration returned HTTP ' + status + ': ' + resp;
    }
    return 'OK';
} catch (error) {
    Zabbix.log(3, '[NMS webhook] failed: ' + error);
    throw 'NMS webhook failed: ' + error;
}
