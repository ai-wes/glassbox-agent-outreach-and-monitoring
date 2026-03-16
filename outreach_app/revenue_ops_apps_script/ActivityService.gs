const ActivityService = (() => {
  function logActivity(activity) {
    const record = Object.assign({
      activity_id: Utils.uuid('act'),
      created_at: Utils.nowIso(),
      entity_type: '',
      entity_id: '',
      channel: 'system',
      direction: 'internal',
      timestamp: Utils.nowIso(),
      subject: '',
      snippet: '',
      source_ref: '',
      sentiment: 'unknown',
      intent_tag: 'unknown',
      metadata_json: '',
    }, activity || {});

    if (typeof record.metadata_json === 'object') {
      record.metadata_json = Utils.limitCellText(Utils.stableStringify(record.metadata_json));
    }

    return Repository.append('Activities', [record])[0];
  }

  function logSystemNote(entityType, entityId, subject, snippet, metadata) {
    return logActivity({
      entity_type: entityType,
      entity_id: entityId,
      channel: 'system',
      direction: 'internal',
      subject: subject,
      snippet: snippet,
      metadata_json: metadata || {},
    });
  }

  function getRecentActivities(entityType, entityId, limit) {
    const items = Repository.filter('Activities', (activity) => {
      return String(activity.entity_type) === String(entityType) &&
        String(activity.entity_id) === String(entityId);
    });
    return Utils.sortByDateDesc(items, ['timestamp', 'created_at']).slice(0, limit || 10);
  }

  function ingestExternalActivity(payload) {
    const safePayload = Utils.stripSecrets(payload || {});
    return logActivity({
      entity_type: safePayload.entity_type || '',
      entity_id: safePayload.entity_id || '',
      channel: safePayload.channel || 'external',
      direction: safePayload.direction || 'inbound',
      timestamp: safePayload.timestamp || Utils.nowIso(),
      subject: safePayload.subject || safePayload.event_type || 'External activity',
      snippet: safePayload.snippet || safePayload.notes || '',
      source_ref: safePayload.source_ref || safePayload.event_type || '',
      sentiment: safePayload.sentiment || 'unknown',
      intent_tag: safePayload.intent_tag || 'unknown',
      metadata_json: safePayload,
    });
  }

  return {
    getRecentActivities,
    ingestExternalActivity,
    logActivity,
    logSystemNote,
  };
})();
