// Zabbix webhook media type: "NMS Integration".
// Sends problem/recovery events to the integration API (POST /integrations/zabbix/events).
//
// Media type parameters (Alerts > Media types > Create > Type: Webhook):
//   url            http://<integration-host>:8000/integrations/zabbix/events
//   token          {$NMS.WEBHOOK.TOKEN}   (optional; must match NMS_ZABBIX_WEBHOOK_TOKEN)
//   eventid        {EVENT.ID}
//   host           {HOST.HOST}            (Zabbix host name == NMS device_id, e.g. CAM-001)
//   nms_event_type {EVENT.TAGS.nms_event_type}
//   severity       {EVENT.NSEVERITY}
//   value          {EVENT.VALUE}          (1 = problem, 0 = recovery)
//   event_date     {EVENT.DATE}           (e.g. 2026.11.26, Zabbix server time zone; the image uses UTC)
//   event_time     {EVENT.TIME}           (e.g. 11:10:52)
//   (Older setups may still pass clock = {EVENT.TIMESTAMP}; it is used when it is a number.)
// Scope: Problem and Recovery operations.
function eventClock(p) {
    if (p.clock && /^\d+$/.test(p.clock)) {
        return p.clock;
    }
    var d = /^(\d{4})\.(\d{2})\.(\d{2})$/.exec(p.event_date || '');
    var t = /^(\d{2}):(\d{2}):(\d{2})$/.exec(p.event_time || '');
    if (d && t) {
        return String(Math.floor(Date.UTC(+d[1], +d[2] - 1, +d[3], +t[1], +t[2], +t[3]) / 1000));
    }
    return String(Math.floor(Date.now() / 1000));  // macro not resolved: use the send time
}
try {
    var p = JSON.parse(value);
    var body = {
        eventid: p.eventid,
        host: p.host,
        nms_event_type: p.nms_event_type,
        severity: p.severity,
        value: p.value,
        clock: eventClock(p)
    };
    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    if (p.token && p.token.indexOf('{$') !== 0) {
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
