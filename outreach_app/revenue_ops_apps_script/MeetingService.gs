const MeetingService = (() => {
  function ingestMeetingTranscript(payload) {
    const linkedEntityType = payload.linked_entity_type || payload.entity_type || 'deal';
    const linkedEntityId = payload.linked_entity_id || payload.entity_id;
    if (!linkedEntityId) {
      throw new Error('Meeting transcript payload must include linked_entity_id or entity_id.');
    }

    const metadata = {
      transcript_text: payload.transcript_text || payload.transcript || '',
      participants: payload.participants || [],
      linked_entity_type: linkedEntityType,
      linked_entity_id: linkedEntityId,
      meeting_url: payload.meeting_url || '',
      source: payload.source || 'webhook',
    };

    const activity = ActivityService.logActivity({
      entity_type: linkedEntityType,
      entity_id: linkedEntityId,
      channel: 'meeting',
      direction: 'inbound',
      timestamp: payload.timestamp || Utils.nowIso(),
      subject: payload.subject || 'Meeting transcript',
      snippet: Utils.truncate(metadata.transcript_text, 800),
      source_ref: payload.source_ref || payload.source || 'meeting_transcript',
      metadata_json: metadata,
    });

    if (linkedEntityType === 'deal') {
      DealService.touchDealActivity(linkedEntityId, payload.timestamp || Utils.nowIso());
    }

    JobQueue.enqueueJob(
      'meeting_summary',
      'activity',
      activity.activity_id,
      Utils.hashObject({
        promptVersion: PromptRegistry.getActivePrompt('meeting_summary').version,
        linkedEntityType: linkedEntityType,
        linkedEntityId: linkedEntityId,
        transcript: metadata.transcript_text,
      }),
      80,
      Session.getEffectiveUser().getEmail()
    );

    return activity;
  }

  function buildMeetingSummaryContext(activityId) {
    const activity = Repository.getById('Activities', activityId);
    if (!activity) {
      throw new Error('Activity not found: ' + activityId);
    }
    const metadata = Utils.parseJson(activity.metadata_json, {});
    const linkedEntityType = metadata.linked_entity_type || '';
    const linkedEntityId = metadata.linked_entity_id || '';

    let linkedEntity = {};
    if (linkedEntityType === 'deal') {
      const deal = Repository.getById('Deals', linkedEntityId) || {};
      linkedEntity = Utils.pick(deal, ['deal_id', 'stage', 'amount', 'close_date', 'probability', 'next_step', 'owner']);
    } else if (linkedEntityType === 'lead') {
      const lead = Repository.getById('Leads', linkedEntityId) || {};
      linkedEntity = Utils.pick(lead, ['lead_id', 'first_name', 'last_name', 'email', 'company', 'title', 'owner', 'status']);
    } else if (linkedEntityType === 'account') {
      const account = Repository.getById('Accounts', linkedEntityId) || {};
      linkedEntity = Utils.pick(account, ['account_id', 'account_name', 'domain', 'owner', 'account_brief']);
    }

    return {
      activity: Utils.pick(activity, ['activity_id', 'timestamp', 'subject', 'snippet']),
      transcript_text: Utils.truncate(metadata.transcript_text || '', 25000),
      participants: metadata.participants || [],
      linked_entity_type: linkedEntityType,
      linked_entity: linkedEntity,
      recent_linked_activities: linkedEntityId ? ActivityService.getRecentActivities(linkedEntityType, linkedEntityId, 8).map((item) => Utils.pick(item, ['timestamp', 'channel', 'subject', 'snippet'])) : [],
    };
  }

  function applyMeetingSummary(activityId, output, meta) {
    const activity = Repository.getById('Activities', activityId);
    if (!activity) {
      throw new Error('Activity not found: ' + activityId);
    }
    const metadata = Utils.parseJson(activity.metadata_json, {});
    const linkedEntityType = metadata.linked_entity_type || '';
    const linkedEntityId = metadata.linked_entity_id || '';

    Repository.updateRow('Activities', activity.__rowNumber, {
      metadata_json: Utils.limitCellText(JSON.stringify(Object.assign({}, metadata, { ai_output_id: meta.outputId }))),
    });

    ActivityService.logSystemNote(linkedEntityType || 'activity', linkedEntityId || activityId, 'AI meeting summary created', Utils.truncate((output.next_steps || []).join('; '), 500), {
      output_id: meta.outputId,
      stakeholders: output.stakeholders,
      next_steps: output.next_steps,
    });

    if (linkedEntityType === 'deal' && linkedEntityId) {
      const deal = Repository.getById('Deals', linkedEntityId);
      if (deal) {
        const fieldUpdate = output.fields_to_update || {};
        Repository.updateRow('Deals', deal.__rowNumber, {
          updated_at: Utils.nowIso(),
          next_step: fieldUpdate.next_step || deal.next_step || '',
          next_step_due: fieldUpdate.next_step_due || deal.next_step_due || '',
          ai_stage_recommendation: fieldUpdate.stage_hint || deal.ai_stage_recommendation || '',
          risk_flags: Utils.limitCellText(JSON.stringify(Utils.mergeUniqueStrings(Utils.parseJson(deal.risk_flags, []), fieldUpdate.risk_flags || []))),
          needs_review: true,
          last_activity_at: activity.timestamp || Utils.nowIso(),
        });
        TaskService.ensureOpenTask({
          entity_type: 'deal',
          entity_id: linkedEntityId,
          owner: deal.owner || '',
          task_type: 'meeting_followup',
          due_at: fieldUpdate.next_step_due || Utils.addDays(Utils.nowIso(), 2),
          priority: 'high',
          auto_generated: true,
          notes: (output.next_steps || []).join(' | ') || 'Review AI meeting summary and follow up.',
        });
      }
    }

    if (linkedEntityType === 'lead' && linkedEntityId) {
      const lead = Repository.getById('Leads', linkedEntityId);
      if (lead) {
        Repository.updateRow('Leads', lead.__rowNumber, {
          updated_at: Utils.nowIso(),
          next_action: (output.next_steps && output.next_steps[0]) || lead.next_action || '',
          next_action_due: (output.fields_to_update && output.fields_to_update.next_step_due) || lead.next_action_due || Utils.addDays(Utils.nowIso(), 2),
          needs_review: true,
          last_touch_at: activity.timestamp || Utils.nowIso(),
        });
        TaskService.ensureOpenTask({
          entity_type: 'lead',
          entity_id: linkedEntityId,
          owner: lead.owner || '',
          task_type: 'meeting_followup',
          due_at: (output.fields_to_update && output.fields_to_update.next_step_due) || Utils.addDays(Utils.nowIso(), 2),
          priority: 'high',
          auto_generated: true,
          notes: (output.next_steps || []).join(' | ') || 'Review AI meeting summary and follow up.',
        });
      }
    }

    return true;
  }

  return {
    applyMeetingSummary,
    buildMeetingSummaryContext,
    ingestMeetingTranscript,
  };
})();
