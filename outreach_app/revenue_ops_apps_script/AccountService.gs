const AccountService = (() => {
  function getOrCreateFromLead(lead) {
    const domain = Utils.normalizeDomain(lead.domain || Utils.domainFromEmail(lead.email));
    const accountName = Utils.normalizeCompanyName(lead.company);

    let existing = null;
    if (domain) {
      existing = Repository.findByField('Accounts', 'domain', domain);
    }
    if (!existing && accountName) {
      existing = Repository.findByField('Accounts', 'account_name', accountName);
    }

    if (existing) {
      return Repository.updateRow('Accounts', existing.__rowNumber, {
        updated_at: Utils.nowIso(),
        owner: existing.owner || lead.owner || '',
        domain: existing.domain || domain,
        account_name: existing.account_name || accountName,
      });
    }

    const account = {
      account_id: Utils.uuid('acct'),
      created_at: Utils.nowIso(),
      updated_at: Utils.nowIso(),
      domain: domain,
      account_name: accountName,
      industry: '',
      size_band: '',
      tier: '',
      owner: lead.owner || '',
      account_brief: '',
      pain_points: '',
      proof_points: '',
      champion: '',
      risk_flags: '',
      health_score: '',
      last_ai_hash: '',
    };
    return Repository.append('Accounts', [account])[0];
  }

  function buildAccountBriefContext(accountId) {
    const account = Repository.getById('Accounts', accountId);
    if (!account) {
      throw new Error('Account not found: ' + accountId);
    }
    const relatedLeads = Repository.filter('Leads', (lead) => {
      return Utils.normalizeDomain(lead.domain) === Utils.normalizeDomain(account.domain) ||
        Utils.normalizeCompanyName(lead.company) === Utils.normalizeCompanyName(account.account_name);
    }).slice(0, 10);

    const relatedDeals = Repository.filter('Deals', (deal) => String(deal.account_id) === String(accountId)).slice(0, 10);
    const activities = ActivityService.getRecentActivities('account', accountId, 10);

    return {
      account: Utils.pick(account, ['account_id', 'domain', 'account_name', 'industry', 'size_band', 'tier', 'owner', 'account_brief']),
      related_leads: relatedLeads.map((lead) => Utils.pick(lead, ['lead_id', 'source', 'title', 'country', 'status', 'priority_score', 'normalized_summary'])),
      related_deals: relatedDeals.map((deal) => Utils.pick(deal, ['deal_id', 'stage', 'amount', 'close_date', 'probability', 'next_step'])),
      recent_activities: activities.map((activity) => Utils.pick(activity, ['timestamp', 'channel', 'direction', 'subject', 'snippet'])),
    };
  }

  function enqueueAccountBriefIfChanged(accountId) {
    const context = buildAccountBriefContext(accountId);
    const prompt = PromptRegistry.getActivePrompt('account_brief');
    const payloadHash = Utils.hashObject({
      promptVersion: prompt.version,
      context: context,
    });
    const account = Repository.getById('Accounts', accountId);
    if (account && account.last_ai_hash === payloadHash && !Utils.isBlank(account.account_brief)) {
      return null;
    }
    return JobQueue.enqueueJob('account_brief', 'account', accountId, payloadHash, 50, Session.getEffectiveUser().getEmail());
  }

  function applyAccountBrief(accountId, output, meta) {
    const account = Repository.getById('Accounts', accountId);
    if (!account) {
      throw new Error('Account not found: ' + accountId);
    }
    const patch = {
      updated_at: Utils.nowIso(),
      account_brief: output.company_summary || '',
      pain_points: Utils.limitCellText(JSON.stringify(output.likely_pain_points || [])),
      proof_points: Utils.limitCellText(JSON.stringify(output.proof_points || [])),
      risk_flags: Utils.limitCellText(JSON.stringify(output.objections || [])),
      health_score: account.health_score || '',
      last_ai_hash: meta.payloadHash,
    };
    const updated = Repository.updateRow('Accounts', account.__rowNumber, patch);

    ActivityService.logSystemNote('account', accountId, 'AI account brief updated', output.company_summary || '', {
      output_id: meta.outputId,
      prompt_version: meta.promptVersion,
    });

    return updated;
  }

  return {
    applyAccountBrief,
    buildAccountBriefContext,
    enqueueAccountBriefIfChanged,
    getOrCreateFromLead,
  };
})();
