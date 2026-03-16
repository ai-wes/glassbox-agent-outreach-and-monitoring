const DraftService = (() => {
  function buildFollowupDraftContext(entityType, entityId) {
    if (entityType === 'lead') {
      return buildLeadFollowupContext_(entityId);
    }
    if (entityType === 'deal') {
      return buildDealFollowupContext_(entityId);
    }
    throw new Error('Unsupported draft entity type: ' + entityType);
  }

  function enqueueFollowupDraft(entityType, entityId) {
    const context = buildFollowupDraftContext(entityType, entityId);
    const prompt = PromptRegistry.getActivePrompt('followup_draft');
    const payloadHash = Utils.hashObject({
      promptVersion: prompt.version,
      context: context,
    });
    return JobQueue.enqueueJob('followup_draft', entityType, entityId, payloadHash, 75, Session.getEffectiveUser().getEmail());
  }

  function applyFollowupRecommendation(entityType, entityId, output, outputId) {
    const patch = {
      updated_at: Utils.nowIso(),
      needs_review: true,
    };

    if (entityType === 'lead') {
      const lead = Repository.getById('Leads', entityId);
      if (!lead) {
        throw new Error('Lead not found: ' + entityId);
      }
      Repository.updateRow('Leads', lead.__rowNumber, Object.assign({}, patch, {
        next_action: 'Review AI-generated draft and send',
        latest_followup_draft_id: outputId,
      }));
      TaskService.ensureOpenTask({
        entity_type: 'lead',
        entity_id: entityId,
        owner: lead.owner || '',
        task_type: 'review_ai_draft',
        due_at: Utils.addHours(Utils.nowIso(), 4),
        priority: output.approval_required ? 'high' : 'medium',
        auto_generated: true,
        notes: (output.risk_flags || []).join(' | ') || 'Review AI-generated follow-up draft.',
      });
    }

    if (entityType === 'deal') {
      const deal = Repository.getById('Deals', entityId);
      if (!deal) {
        throw new Error('Deal not found: ' + entityId);
      }
      Repository.updateRow('Deals', deal.__rowNumber, Object.assign({}, patch, {
        next_step: deal.next_step || 'Review AI-generated draft and send',
      }));
      TaskService.ensureOpenTask({
        entity_type: 'deal',
        entity_id: entityId,
        owner: deal.owner || '',
        task_type: 'review_ai_draft',
        due_at: Utils.addHours(Utils.nowIso(), 4),
        priority: output.approval_required ? 'high' : 'medium',
        auto_generated: true,
        notes: (output.risk_flags || []).join(' | ') || 'Review AI-generated follow-up draft.',
      });
    }

    ActivityService.logSystemNote(entityType, entityId, 'AI follow-up draft ready', output.subject || '', {
      output_id: outputId,
      risk_flags: output.risk_flags || [],
      approval_required: !!output.approval_required,
    });

    return true;
  }

  function createDraftFromLatestOutput(entityType, entityId) {
    const outputRow = getLatestFollowupOutput_(entityType, entityId);
    if (!outputRow) {
      throw new Error('No follow-up draft AI output found. Generate the draft first.');
    }
    const draft = Utils.parseJson(outputRow.output_json, null);
    if (!draft) {
      throw new Error('Latest follow-up output could not be parsed.');
    }
    const recipient = resolveRecipient_(entityType, entityId);
    if (!recipient) {
      throw new Error('Unable to determine recipient email for ' + entityType + ' ' + entityId);
    }

    const htmlBody = draft.body_html
      ? Utils.sanitizeEmailHtml(draft.body_html)
      : '<p>' + Utils.nl2br(Utils.htmlEscape(draft.body_text || '')) + '</p>';

    const options = {
      htmlBody: htmlBody,
    };
    const senderName = ConfigService.getString('OUTREACH_SENDER_NAME', '');
    const replyTo = ConfigService.getString('DEFAULT_REPLY_TO', '');
    if (senderName) {
      options.name = senderName;
    }
    if (replyTo) {
      options.replyTo = replyTo;
    }

    const createdDraft = GmailApp.createDraft(recipient, draft.subject || '(No subject)', draft.body_text || '', options);

    ActivityService.logActivity({
      entity_type: entityType,
      entity_id: entityId,
      channel: 'email',
      direction: 'draft',
      timestamp: Utils.nowIso(),
      subject: draft.subject || '',
      snippet: Utils.truncate(draft.body_text || '', 500),
      source_ref: 'gmail_draft:' + createdDraft.getId(),
      metadata_json: {
        output_id: outputRow.output_id,
        draft_id: createdDraft.getId(),
        recipient: recipient,
      },
    });

    if (entityType === 'lead') {
      const lead = Repository.getById('Leads', entityId);
      if (lead) {
        Repository.updateRow('Leads', lead.__rowNumber, {
          updated_at: Utils.nowIso(),
          latest_followup_draft_id: outputRow.output_id,
          next_action: 'Draft created in Gmail. Review and send.',
          needs_review: true,
        });
      }
    }

    return {
      draftId: createdDraft.getId(),
      recipient: recipient,
      subject: draft.subject || '',
    };
  }

  function getLatestFollowupOutput_(entityType, entityId) {
    return Repository.getLatest('AI_Outputs', (output) => {
      return String(output.job_type) === 'followup_draft' &&
        String(output.entity_type) === String(entityType) &&
        String(output.entity_id) === String(entityId);
    }, ['updated_at', 'created_at']);
  }

  function buildLeadFollowupContext_(leadId) {
    const lead = Repository.getById('Leads', leadId);
    if (!lead) {
      throw new Error('Lead not found: ' + leadId);
    }
    const account = lead.domain ? Repository.findByField('Accounts', 'domain', lead.domain) : null;
    const activities = ActivityService.getRecentActivities('lead', leadId, 10);
    return {
      entity_type: 'lead',
      recipient: {
        email: lead.email,
        first_name: lead.first_name,
        last_name: lead.last_name,
        title: lead.title,
      },
      lead: Utils.pick(lead, [
        'lead_id', 'source', 'company', 'domain', 'title', 'country',
        'normalized_summary', 'fit_score', 'intent_score', 'timing_score', 'priority_score',
        'next_action', 'next_action_due'
      ]),
      account: account ? Utils.pick(account, ['account_id', 'account_name', 'domain', 'account_brief', 'pain_points', 'proof_points']) : {},
      recent_activities: activities.map((item) => Utils.pick(item, ['timestamp', 'channel', 'direction', 'subject', 'snippet'])),
      sender_context: {
        sender_name: ConfigService.getString('OUTREACH_SENDER_NAME', ''),
      }
    };
  }

  function buildDealFollowupContext_(dealId) {
    const deal = Repository.getById('Deals', dealId);
    if (!deal) {
      throw new Error('Deal not found: ' + dealId);
    }
    const account = deal.account_id ? Repository.getById('Accounts', deal.account_id) : null;
    const contact = resolveDealContact_(deal);
    const activities = ActivityService.getRecentActivities('deal', dealId, 10);
    return {
      entity_type: 'deal',
      recipient: contact ? Utils.pick(contact, ['email', 'name', 'title']) : {},
      deal: Utils.pick(deal, [
        'deal_id', 'stage', 'amount', 'close_date', 'probability', 'next_step',
        'next_step_due', 'stall_reason', 'risk_score', 'health_score', 'ai_stage_recommendation'
      ]),
      account: account ? Utils.pick(account, ['account_id', 'account_name', 'domain', 'account_brief', 'pain_points', 'proof_points']) : {},
      recent_activities: activities.map((item) => Utils.pick(item, ['timestamp', 'channel', 'direction', 'subject', 'snippet'])),
      sender_context: {
        sender_name: ConfigService.getString('OUTREACH_SENDER_NAME', ''),
      }
    };
  }

  function resolveRecipient_(entityType, entityId) {
    if (entityType === 'lead') {
      const lead = Repository.getById('Leads', entityId);
      return lead ? lead.email : '';
    }
    if (entityType === 'deal') {
      const deal = Repository.getById('Deals', entityId);
      const contact = deal ? resolveDealContact_(deal) : null;
      return contact ? contact.email : '';
    }
    return '';
  }

  function resolveDealContact_(deal) {
    if (deal.primary_contact_id) {
      const byId = Repository.getById('Contacts', deal.primary_contact_id);
      if (byId) {
        return byId;
      }
    }
    if (deal.account_id) {
      return Repository.filter('Contacts', (contact) => String(contact.account_id) === String(deal.account_id))[0] || null;
    }
    return null;
  }

  return {
    applyFollowupRecommendation,
    buildFollowupDraftContext,
    createDraftFromLatestOutput,
    enqueueFollowupDraft,
  };
})();
