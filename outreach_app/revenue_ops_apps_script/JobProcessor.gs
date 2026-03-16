const JobProcessor = (() => {
  function process(job) {
    const contextInfo = buildContext_(job);
    const renderedPrompt = PromptRegistry.renderPrompt(contextInfo.promptKey, {
      context_json: JSON.stringify(contextInfo.context, null, 2),
    });
    const aiResult = AiClient.generateStructuredJson(job.job_type, renderedPrompt);
    const outputRow = persistOutput_(job, renderedPrompt, aiResult);
    const applyResult = applyOutput_(job, aiResult.parsed, outputRow.output_id, renderedPrompt.version);
    if (applyResult === true) {
      Repository.updateRow('AI_Outputs', outputRow.__rowNumber, {
        updated_at: Utils.nowIso(),
        applied_to_record_at: Utils.nowIso(),
        status: 'applied',
      });
    }
    return {
      outputId: outputRow.output_id,
      applied: applyResult === true,
    };
  }

  function buildContext_(job) {
    switch (job.job_type) {
      case 'lead_score':
        return {
          promptKey: 'lead_score',
          context: LeadService.buildLeadScoringContext(job.entity_id),
        };
      case 'account_brief':
        return {
          promptKey: 'account_brief',
          context: AccountService.buildAccountBriefContext(job.entity_id),
        };
      case 'followup_draft':
        return {
          promptKey: 'followup_draft',
          context: DraftService.buildFollowupDraftContext(job.entity_type, job.entity_id),
        };
      case 'meeting_summary':
        return {
          promptKey: 'meeting_summary',
          context: MeetingService.buildMeetingSummaryContext(job.entity_id),
        };
      case 'deal_risk_scan':
        return {
          promptKey: 'deal_risk_scan',
          context: DealService.buildDealRiskContext(job.entity_id),
        };
      default:
        throw new Error('Unsupported job type: ' + job.job_type);
    }
  }

  function persistOutput_(job, prompt, aiResult) {
    return Repository.append('AI_Outputs', [{
      output_id: Utils.uuid('out'),
      created_at: Utils.nowIso(),
      updated_at: Utils.nowIso(),
      job_id: job.job_id,
      job_type: job.job_type,
      entity_type: job.entity_type,
      entity_id: job.entity_id,
      prompt_key: prompt.promptKey,
      prompt_version: prompt.version,
      schema_version: aiResult.schemaVersion,
      model_name: aiResult.modelName,
      output_json: Utils.limitCellText(JSON.stringify(aiResult.parsed)),
      confidence: aiResult.confidence,
      approved_by: '',
      approved_at: '',
      applied_to_record_at: '',
      status: 'generated',
      error_message: '',
    }])[0];
  }

  function applyOutput_(job, parsed, outputId, promptVersion) {
    const meta = {
      outputId: outputId,
      promptVersion: promptVersion,
      payloadHash: job.payload_hash,
    };

    switch (job.job_type) {
      case 'lead_score':
        LeadService.applyLeadScore(job.entity_id, parsed, meta);
        return true;
      case 'account_brief':
        AccountService.applyAccountBrief(job.entity_id, parsed, meta);
        return true;
      case 'followup_draft':
        DraftService.applyFollowupRecommendation(job.entity_type, job.entity_id, parsed, outputId);
        return false;
      case 'meeting_summary':
        MeetingService.applyMeetingSummary(job.entity_id, parsed, meta);
        return true;
      case 'deal_risk_scan':
        DealService.applyDealRisk(job.entity_id, parsed, meta);
        return true;
      default:
        throw new Error('Unsupported job type: ' + job.job_type);
    }
  }

  return {
    process,
  };
})();
