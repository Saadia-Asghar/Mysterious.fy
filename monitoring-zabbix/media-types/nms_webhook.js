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
//   clock          {EVENT.TIMESTAMP}
// Scope: Problem and Recovery operations.
try {
    var p = JSON.parse(value);
    var body = {
        eventid: p.eventid,
        host: p.host,
        nms_event_type: p.nms_event_type,
        severity: p.severity,
        value: p.value,
        clock: p.clock
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
