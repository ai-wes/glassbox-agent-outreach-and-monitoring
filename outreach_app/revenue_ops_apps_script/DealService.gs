const DealService = (() => {
  function buildDealRiskContext(dealId) {
    const deal = Repository.getById('Deals', dealId);
    if (!deal) {
      throw new Error('Deal not found: ' + dealId);
    }
    const account = deal.account_id ? Repository.getById('Accounts', deal.account_id) : null;
    const contact = getPrimaryContact_(deal);
    const activities = ActivityService.getRecentActivities('deal', dealId, 12);
    const tasks = TaskService.getOpenTasks('deal', dealId);

    return {
      deal: Utils.pick(deal, [
        'deal_id', 'account_id', 'primary_contact_id', 'owner', 'stage', 'amount',
        'close_date', 'probability', 'next_step', 'next_step_due', 'stall_reason',
        'risk_flags', 'risk_score', 'health_score', 'last_activity_at'
      ]),
      account: account ? Utils.pick(account, ['account_id', 'account_name', 'domain', 'owner', 'account_brief']) : {},
      primary_contact: contact ? Utils.pick(contact, ['contact_id', 'name', 'email', 'title', 'persona']) : {},
      recent_activities: activities.map((activity) => Utils.pick(activity, ['timestamp', 'channel', 'direction', 'subject', 'snippet'])),
      open_tasks: tasks.map((task) => Utils.pick(task, ['task_type', 'due_at', 'priority', 'notes'])),
      derived_signals: computeDerivedSignals_(deal, activities),
    };
  }

  function computeDerivedSignals_(deal, activities) {
    const now = new Date();
    const lastActivity = Utils.toDate(deal.last_activity_at || (activities[0] && activities[0].timestamp));
    const closeDate = Utils.toDate(deal.close_date);
    return {
      has_next_step: !Utils.isBlank(deal.next_step),
      next_step_due_present: !Utils.isBlank(deal.next_step_due),
      days_since_last_activity: lastActivity ? Math.floor((now.getTime() - lastActivity.getTime()) / 86400000) : null,
      close_date_is_past: closeDate ? closeDate.getTime() < now.getTime() : false,
      advanced_stage_without_amount: ['proposal', 'negotiation'].indexOf(String(deal.stage || '')) !== -1 && Utils.isBlank(deal.amount),
    };
  }

  function enqueueDealRiskIfChanged(dealId) {
    const deal = Repository.getById('Deals', dealId);
    if (!deal) {
      throw new Error('Deal not found: ' + dealId);
    }
    const context = buildDealRiskContext(dealId);
    const prompt = PromptRegistry.getActivePrompt('deal_risk_scan');
    const payloadHash = Utils.hashObject({
      promptVersion: prompt.version,
      context: context,
    });
    if (deal.last_ai_hash === payloadHash) {
      return null;
    }
    return JobQueue.enqueueJob('deal_risk_scan', 'deal', dealId, payloadHash, 65, Session.getEffectiveUser().getEmail());
  }

  function applyDealRisk(dealId, output, meta) {
    const deal = Repository.getById('Deals', dealId);
    if (!deal) {
      throw new Error('Deal not found: ' + dealId);
    }

    const patch = {
      updated_at: Utils.nowIso(),
      risk_flags: Utils.limitCellText(JSON.stringify(output.risk_flags || [])),
      risk_score: Utils.clamp(Utils.asInt(output.risk_score, 0), 0, 100),
      health_score: Utils.clamp(Utils.asInt(output.health_score, 0), 0, 100),
      ai_stage_recommendation: output.stage_recommendation || '',
      needs_review: !!output.manager_attention || !Utils.isBlank(deal.validation_errors),
      stall_reason: deal.stall_reason || output.reason_summary || '',
      last_ai_hash: meta.payloadHash,
    };

    const updated = Repository.updateRow('Deals', deal.__rowNumber, patch);

    if (output.manager_attention || Utils.asInt(output.risk_score, 0) >= 75) {
      TaskService.ensureOpenTask({
        entity_type: 'deal',
        entity_id: dealId,
        owner: updated.owner || '',
        task_type: 'deal_rescue',
        due_at: Utils.addHours(Utils.nowIso(), 6),
        priority: 'urgent',
        auto_generated: true,
        notes: output.recommended_action || output.reason_summary || 'Deal requires manager review.',
      });
    }

    ActivityService.logSystemNote('deal', dealId, 'AI deal risk scan updated', output.reason_summary || '', {
      output_id: meta.outputId,
      prompt_version: meta.promptVersion,
      manager_attention: output.manager_attention,
    });

    return updated;
  }

  function runStaleDealAudit() {
    const staleAfterDays = ConfigService.getNumber('DEAL_STALE_AFTER_DAYS', 10);
    const now = new Date();
    const openDeals = Repository.filter('Deals', (deal) => {
      return ['closed_won', 'closed_lost'].indexOf(String(deal.stage || '')) === -1;
    });

    let queued = 0;
    openDeals.forEach((deal) => {
      const issues = [];
      if (Utils.isBlank(deal.next_step)) {
        issues.push('No next step');
      }
      if (deal.next_step_due && Utils.toDate(deal.next_step_due) && Utils.toDate(deal.next_step_due).getTime() < now.getTime()) {
        issues.push('Next step overdue');
      }
      const lastActivity = Utils.toDate(deal.last_activity_at);
      if (!lastActivity || ((now.getTime() - lastActivity.getTime()) / 86400000) >= staleAfterDays) {
        issues.push('Stale activity');
      }
      if (deal.close_date && Utils.toDate(deal.close_date) && Utils.toDate(deal.close_date).getTime() < now.getTime()) {
        issues.push('Close date in past');
      }
      if (['proposal', 'negotiation'].indexOf(String(deal.stage || '')) !== -1 && Utils.isBlank(deal.amount)) {
        issues.push('Missing amount');
      }

      if (!issues.length) {
        return;
      }

      Repository.updateRow('Deals', deal.__rowNumber, {
        updated_at: Utils.nowIso(),
        needs_review: true,
        stall_reason: deal.stall_reason || issues.join('; '),
      });

      TaskService.ensureOpenTask({
        entity_type: 'deal',
        entity_id: deal.deal_id,
        owner: deal.owner || '',
        task_type: 'deal_hygiene',
        due_at: Utils.nowIso(),
        priority: issues.indexOf('Stale activity') !== -1 ? 'high' : 'medium',
        auto_generated: true,
        notes: 'Deal audit flags: ' + issues.join(', '),
      });

      enqueueDealRiskIfChanged(deal.deal_id);
      queued += 1;
    });

    return queued;
  }

  function touchDealActivity(dealId, timestamp) {
    const deal = Repository.getById('Deals', dealId);
    if (!deal) {
      return null;
    }
    return Repository.updateRow('Deals', deal.__rowNumber, {
      updated_at: Utils.nowIso(),
      last_activity_at: timestamp || Utils.nowIso(),
    });
  }

  function getPrimaryContact_(deal) {
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
    applyDealRisk,
    buildDealRiskContext,
    enqueueDealRiskIfChanged,
    runStaleDealAudit,
    touchDealActivity,
  };
})();
