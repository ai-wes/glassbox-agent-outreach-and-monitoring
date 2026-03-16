function doGet(e) {
  const response = {
    ok: true,
    timestamp: Utils.nowIso(),
    runtime: ConfigService.describeRuntime(),
    queue: JobQueue.getQueueSummary(),
  };
  return jsonResponse_(response);
}

function doPost(e) {
  try {
    const payload = parseWebhookPayload_(e);
    verifyWebhookSecret_(payload, e);

    const safePayload = Utils.stripSecrets(payload || {});
    const eventType = safePayload.event_type || safePayload.type || 'lead';
    let result;
    switch (eventType) {
      case 'lead':
      case 'inbound_lead':
      case 'lead_created':
        result = LeadService.ingestInboundLead(safePayload);
        break;
      case 'meeting_transcript':
        result = MeetingService.ingestMeetingTranscript(safePayload);
        break;
      case 'activity':
        result = ActivityService.ingestExternalActivity(safePayload);
        break;
      case 'healthcheck':
        result = { ok: true, timestamp: Utils.nowIso() };
        break;
      default:
        throw new Error('Unsupported webhook event_type: ' + eventType);
    }

    return jsonResponse_({
      ok: true,
      event_type: eventType,
      result: result,
    });
  } catch (error) {
    LogService.error('doPost', error, {
      message: 'Webhook request failed.',
    });
    return jsonResponse_({
      ok: false,
      error: Utils.stringifyError(error),
    });
  }
}

function parseWebhookPayload_(e) {
  if (!e) {
    return {};
  }
  if (e.postData && e.postData.contents) {
    const parsed = Utils.parseJson(e.postData.contents, null);
    if (parsed) {
      return parsed;
    }
  }
  return e.parameter || {};
}

function verifyWebhookSecret_(payload, e) {
  const provided = (payload && payload.secret) || (e && e.parameter && e.parameter.secret) || '';
  const expected = ConfigService.getWebhookSecret();
  if (!expected || !Utils.secureEquals(provided, expected)) {
    throw new Error('Invalid webhook secret.');
  }
}

function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
