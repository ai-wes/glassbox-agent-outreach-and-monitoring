const ValidationService = (() => {
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function validateLead(record) {
    const errors = [];
    const email = Utils.normalizeEmail(record.email);
    const company = Utils.normalizeCompanyName(record.company);

    if (!email && !company) {
      errors.push('Lead must have at least an email or a company.');
    }
    if (email && !EMAIL_RE.test(email)) {
      errors.push('Lead email is not valid.');
    }
    if (record.status && DataModel.ENUMS.LEAD_STATUS.indexOf(record.status) === -1) {
      errors.push('Lead status is not recognized.');
    }
    ['fit_score', 'intent_score', 'timing_score', 'priority_score'].forEach((field) => {
      if (!Utils.isBlank(record[field])) {
        const score = Utils.asNumber(record[field], null);
        if (score === null || score < 0 || score > 100) {
          errors.push(field + ' must be between 0 and 100.');
        }
      }
    });
    if (record.next_action_due && !Utils.toDate(record.next_action_due)) {
      errors.push('Lead next_action_due must be a valid date.');
    }
    return errors;
  }

  function validateDeal(record) {
    const errors = [];
    if (record.stage && DataModel.ENUMS.DEAL_STAGE.indexOf(record.stage) === -1) {
      errors.push('Deal stage is not recognized.');
    }
    if (!Utils.isBlank(record.amount) && Utils.asNumber(record.amount, null) === null) {
      errors.push('Deal amount must be numeric.');
    }
    if (!Utils.isBlank(record.probability)) {
      const probability = Utils.asNumber(record.probability, null);
      if (probability === null || probability < 0 || probability > 100) {
        errors.push('Deal probability must be between 0 and 100.');
      }
    }
    if (record.close_date && !Utils.toDate(record.close_date)) {
      errors.push('Deal close_date must be a valid date.');
    }
    if (record.stage && ['proposal', 'negotiation'].indexOf(record.stage) !== -1 && Utils.isBlank(record.amount)) {
      errors.push('Advanced deals should include an amount.');
    }
    return errors;
  }

  function validateAccount(record) {
    const errors = [];
    if (record.domain && record.domain.indexOf('.') === -1) {
      errors.push('Account domain does not look valid.');
    }
    return errors;
  }

  function handleEditEvent(e) {
    try {
      if (!e || !e.range) {
        return;
      }
      const sheet = e.range.getSheet();
      const sheetName = sheet.getName();
      const rowNumber = e.range.getRow();
      if (rowNumber < 2) {
        if (sheetName === 'Prompt_Library') {
          PromptRegistry.invalidate();
        }
        if (sheetName === 'Config') {
          ConfigService.invalidateCache();
        }
        return;
      }

      if (sheetName === 'Leads') {
        const lead = Repository.getRecordByRow('Leads', rowNumber);
        const errors = validateLead(lead);
        Repository.updateRow('Leads', rowNumber, {
          updated_at: Utils.nowIso(),
          validation_errors: errors.join(' | '),
          needs_review: errors.length ? true : Utils.parseBoolean(lead.needs_review, false),
        });
        LeadService.enqueueLeadScoreIfChanged(lead.lead_id);
        return;
      }

      if (sheetName === 'Deals') {
        const deal = Repository.getRecordByRow('Deals', rowNumber);
        const errors = validateDeal(deal);
        Repository.updateRow('Deals', rowNumber, {
          updated_at: Utils.nowIso(),
          validation_errors: errors.join(' | '),
          needs_review: errors.length ? true : Utils.parseBoolean(deal.needs_review, false),
        });
        DealService.enqueueDealRiskIfChanged(deal.deal_id);
        return;
      }

      if (sheetName === 'Accounts') {
        const account = Repository.getRecordByRow('Accounts', rowNumber);
        const errors = validateAccount(account);
        if (errors.length || Utils.isBlank(account.account_brief)) {
          Repository.updateRow('Accounts', rowNumber, {
            updated_at: Utils.nowIso(),
          });
          AccountService.enqueueAccountBriefIfChanged(account.account_id);
        }
        return;
      }

      if (sheetName === 'Prompt_Library') {
        PromptRegistry.invalidate();
        return;
      }

      if (sheetName === 'Config') {
        ConfigService.invalidateCache();
      }
    } catch (error) {
      LogService.error('ValidationService.handleEditEvent', error, {
        message: 'Failed handling installable edit.',
      });
    }
  }

  return {
    handleEditEvent,
    validateAccount,
    validateDeal,
    validateLead,
  };
})();
