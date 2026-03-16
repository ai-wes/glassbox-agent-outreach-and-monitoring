const LeadService = (() => {
  function ingestInboundLead(payload) {
    const safePayload = Utils.stripSecrets(payload || {});
    const normalized = normalizeInboundLead_(safePayload || {});
    const owner = normalized.owner || RoutingService.selectOwnerForLead(normalized);
    normalized.owner = owner;

    const account = AccountService.getOrCreateFromLead(normalized);
    const contact = getOrCreateContactFromLead_(normalized, account);

    let lead = findExistingLead_(normalized);
    const existedAlready = !!lead;
    const validationErrors = ValidationService.validateLead(normalized);

    if (lead) {
      lead = Repository.updateRow('Leads', lead.__rowNumber, Object.assign({}, normalized, {
        updated_at: Utils.nowIso(),
        owner: lead.owner || owner,
        last_touch_at: safePayload.timestamp || Utils.nowIso(),
        validation_errors: validationErrors.join(' | '),
        needs_review: validationErrors.length ? true : Utils.parseBoolean(lead.needs_review, false),
      }));
    } else {
      lead = Repository.append('Leads', [Object.assign({
        lead_id: Utils.uuid('lead'),
        created_at: Utils.nowIso(),
        updated_at: Utils.nowIso(),
        fit_score: '',
        intent_score: '',
        timing_score: '',
        priority_score: '',
        status: 'new',
        next_action: '',
        next_action_due: '',
        last_touch_at: Utils.nowIso(),
        last_ai_hash: '',
        needs_review: validationErrors.length > 0,
        validation_errors: validationErrors.join(' | '),
        latest_followup_draft_id: '',
      }, normalized)])[0];
    }

    ActivityService.logActivity({
      entity_type: 'lead',
      entity_id: lead.lead_id,
      channel: safePayload.channel || 'webhook',
      direction: 'inbound',
      timestamp: safePayload.timestamp || Utils.nowIso(),
      subject: safePayload.subject || 'Inbound lead',
      snippet: normalized.raw_inbound_text || normalized.normalized_summary || '',
      source_ref: safePayload.source_ref || safePayload.source || normalized.source || '',
      metadata_json: safePayload,
    });

    enqueueLeadScoreIfChanged(lead.lead_id);
    if (account && Utils.isBlank(account.account_brief)) {
      AccountService.enqueueAccountBriefIfChanged(account.account_id);
    }

    TaskService.ensureOpenTask({
      entity_type: 'lead',
      entity_id: lead.lead_id,
      owner: lead.owner || owner,
      task_type: 'new_lead_followup',
      due_at: Utils.addHours(Utils.nowIso(), 4),
      priority: 'high',
      auto_generated: true,
      notes: 'Review and respond to new inbound lead.',
    });

    return {
      lead_id: lead.lead_id,
      account_id: account.account_id,
      contact_id: contact ? contact.contact_id : '',
      owner: lead.owner || owner,
      created: !existedAlready,
    };
  }

  function normalizeInboundLead_(payload) {
    const fullName = payload.full_name || payload.name || [payload.first_name, payload.last_name].filter(Boolean).join(' ');
    const splitName = Utils.splitName(fullName);
    const email = Utils.normalizeEmail(payload.email || '');
    const domain = Utils.normalizeDomain(payload.domain || payload.website || Utils.domainFromEmail(email));
    const rawText = [
      payload.message,
      payload.notes,
      payload.use_case,
      payload.company_description,
      payload.context,
    ].filter((item) => !Utils.isBlank(item)).join('\n\n');

    return {
      source: Utils.normalizeWhitespace(payload.source || 'unknown'),
      first_name: Utils.normalizeWhitespace(payload.first_name || splitName.firstName),
      last_name: Utils.normalizeWhitespace(payload.last_name || splitName.lastName),
      email: email,
      company: Utils.normalizeCompanyName(payload.company || payload.account_name || ''),
      domain: domain,
      title: Utils.normalizeWhitespace(payload.title || ''),
      country: Utils.normalizeWhitespace(payload.country || ''),
      raw_inbound_text: Utils.limitCellText(rawText || Utils.stableStringify(payload)),
      normalized_summary: Utils.truncate(rawText || payload.summary || '', 500),
      owner: Utils.normalizeEmail(payload.owner || ''),
    };
  }

  function findExistingLead_(normalized) {
    if (normalized.email) {
      const byEmail = Repository.findByField('Leads', 'email', normalized.email);
      if (byEmail) {
        return byEmail;
      }
    }

    if (normalized.domain && normalized.company) {
      const byCompany = Repository.filter('Leads', (lead) => {
        return Utils.normalizeDomain(lead.domain) === normalized.domain &&
          Utils.normalizeCompanyName(lead.company) === normalized.company;
      })[0];
      if (byCompany) {
        return byCompany;
      }
    }

    return null;
  }

  function getOrCreateContactFromLead_(lead, account) {
    if (!lead.email) {
      return null;
    }
    const existing = Repository.findByField('Contacts', 'email', lead.email);
    if (existing) {
      return Repository.updateRow('Contacts', existing.__rowNumber, {
        updated_at: Utils.nowIso(),
        account_id: existing.account_id || account.account_id,
        name: existing.name || [lead.first_name, lead.last_name].filter(Boolean).join(' '),
        title: existing.title || lead.title,
      });
    }

    return Repository.append('Contacts', [{
      contact_id: Utils.uuid('contact'),
      created_at: Utils.nowIso(),
      updated_at: Utils.nowIso(),
      account_id: account.account_id,
      name: [lead.first_name, lead.last_name].filter(Boolean).join(' '),
      email: lead.email,
      title: lead.title || '',
      role_type: '',
      persona: '',
      linkedin_url: '',
      influence_score: '',
    }])[0];
  }

  function buildLeadScoringContext(leadId) {
    const lead = Repository.getById('Leads', leadId);
    if (!lead) {
      throw new Error('Lead not found: ' + leadId);
    }
    const account = findAccountForLead_(lead);
    const contact = lead.email ? Repository.findByField('Contacts', 'email', lead.email) : null;
    const activities = ActivityService.getRecentActivities('lead', leadId, 10);
    const tasks = TaskService.getOpenTasks('lead', leadId);

    return {
      lead: Utils.pick(lead, [
        'lead_id', 'source', 'first_name', 'last_name', 'email', 'company', 'domain', 'title',
        'country', 'raw_inbound_text', 'normalized_summary', 'owner', 'status', 'last_touch_at'
      ]),
      account: account ? Utils.pick(account, ['account_id', 'domain', 'account_name', 'industry', 'size_band', 'tier', 'owner']) : {},
      contact: contact ? Utils.pick(contact, ['contact_id', 'name', 'email', 'title', 'persona', 'influence_score']) : {},
      recent_activities: activities.map((activity) => Utils.pick(activity, ['timestamp', 'channel', 'direction', 'subject', 'snippet'])),
      open_tasks: tasks.map((task) => Utils.pick(task, ['task_type', 'due_at', 'priority', 'notes'])),
      derived_signals: {
        has_email: !!lead.email,
        has_title: !!lead.title,
        inbound_text_length: String(lead.raw_inbound_text || '').length,
      }
    };
  }

  function enqueueLeadScoreIfChanged(leadId) {
    const lead = Repository.getById('Leads', leadId);
    if (!lead) {
      throw new Error('Lead not found: ' + leadId);
    }
    const context = buildLeadScoringContext(leadId);
    const prompt = PromptRegistry.getActivePrompt('lead_score');
    const payloadHash = Utils.hashObject({
      promptVersion: prompt.version,
      context: context,
    });
    if (lead.last_ai_hash === payloadHash) {
      return null;
    }
    const priority = Utils.asInt(lead.priority_score, 0) >= ConfigService.getNumber('HIGH_PRIORITY_THRESHOLD', 85) ? 95 : 70;
    return JobQueue.enqueueJob('lead_score', 'lead', leadId, payloadHash, priority, Session.getEffectiveUser().getEmail());
  }

  function applyLeadScore(leadId, output, meta) {
    const lead = Repository.getById('Leads', leadId);
    if (!lead) {
      throw new Error('Lead not found: ' + leadId);
    }

    const fitScore = Utils.clamp(Utils.asInt(output.fit_score, 0), 0, 100);
    const intentScore = Utils.clamp(Utils.asInt(output.intent_score, 0), 0, 100);
    const timingScore = Utils.clamp(Utils.asInt(output.timing_score, 0), 0, 100);
    const priorityScore = Utils.clamp(Utils.asInt(output.priority_score, 0), 0, 100);
    const missingFields = Utils.ensureArray(output.missing_fields);

    const patch = {
      updated_at: Utils.nowIso(),
      fit_score: fitScore,
      intent_score: intentScore,
      timing_score: timingScore,
      priority_score: priorityScore,
      next_action: output.next_action || lead.next_action || '',
      next_action_due: lead.next_action_due || Utils.addHours(Utils.nowIso(), 24),
      last_ai_hash: meta.payloadHash,
      needs_review: missingFields.length > 0 || priorityScore >= ConfigService.getNumber('LEAD_REVIEW_THRESHOLD', 70) || !Utils.isBlank(lead.validation_errors),
    };
    const updated = Repository.updateRow('Leads', lead.__rowNumber, patch);

    if (priorityScore >= ConfigService.getNumber('LEAD_REVIEW_THRESHOLD', 70)) {
      TaskService.ensureOpenTask({
        entity_type: 'lead',
        entity_id: leadId,
        owner: updated.owner || '',
        task_type: 'lead_review',
        due_at: updated.next_action_due || Utils.addHours(Utils.nowIso(), 24),
        priority: priorityScore >= ConfigService.getNumber('HIGH_PRIORITY_THRESHOLD', 85) ? 'urgent' : 'high',
        auto_generated: true,
        notes: output.reason_summary || updated.next_action || 'AI flagged this lead for follow-up.',
      });
    }

    ActivityService.logSystemNote('lead', leadId, 'AI lead score updated', output.reason_summary || '', {
      output_id: meta.outputId,
      prompt_version: meta.promptVersion,
      buyer_persona: output.buyer_persona,
      missing_fields: missingFields,
    });

    return updated;
  }

  function runFollowupReminderScan() {
    const now = new Date();
    const followupOverdueHours = ConfigService.getNumber('FOLLOWUP_OVERDUE_HOURS', 24);
    const leads = Repository.filter('Leads', (lead) => {
      return ['new', 'working', 'qualified', 'nurture'].indexOf(String(lead.status || 'new')) !== -1;
    });

    let count = 0;
    leads.forEach((lead) => {
      const dueDate = Utils.toDate(lead.next_action_due || lead.created_at);
      if (!dueDate) {
        return;
      }
      const hoursSinceDue = (now.getTime() - dueDate.getTime()) / 3600000;
      if (hoursSinceDue < followupOverdueHours) {
        return;
      }
      count += 1;
      TaskService.ensureOpenTask({
        entity_type: 'lead',
        entity_id: lead.lead_id,
        owner: lead.owner || '',
        task_type: 'lead_followup_due',
        due_at: Utils.nowIso(),
        priority: Utils.asInt(lead.priority_score, 0) >= ConfigService.getNumber('HIGH_PRIORITY_THRESHOLD', 85) ? 'urgent' : 'high',
        auto_generated: true,
        notes: 'Lead follow-up is overdue.',
      });
      if (Utils.asInt(lead.priority_score, 0) >= ConfigService.getNumber('LEAD_REVIEW_THRESHOLD', 70)) {
        DraftService.enqueueFollowupDraft('lead', lead.lead_id);
      }
    });

    return count;
  }

  function findAccountForLead_(lead) {
    if (lead.domain) {
      const byDomain = Repository.findByField('Accounts', 'domain', lead.domain);
      if (byDomain) {
        return byDomain;
      }
    }
    if (lead.company) {
      return Repository.findByField('Accounts', 'account_name', lead.company);
    }
    return null;
  }

  return {
    applyLeadScore,
    buildLeadScoringContext,
    enqueueLeadScoreIfChanged,
    ingestInboundLead,
    runFollowupReminderScan,
  };
})();
