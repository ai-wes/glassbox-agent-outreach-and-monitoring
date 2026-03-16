const AiSchemas = (() => {
  function leadScoreSchema() {
    return {
      schemaVersion: '1',
      name: 'lead_score',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: [
          'fit_score',
          'intent_score',
          'timing_score',
          'priority_score',
          'buyer_persona',
          'routing_hint',
          'next_action',
          'confidence',
          'missing_fields',
          'reason_summary'
        ],
        properties: {
          fit_score: { type: 'integer', minimum: 0, maximum: 100 },
          intent_score: { type: 'integer', minimum: 0, maximum: 100 },
          timing_score: { type: 'integer', minimum: 0, maximum: 100 },
          priority_score: { type: 'integer', minimum: 0, maximum: 100 },
          buyer_persona: { type: 'string', enum: DataModel.ENUMS.BUYER_PERSONA },
          routing_hint: { type: 'string', maxLength: 120 },
          next_action: { type: 'string', maxLength: 160 },
          confidence: { type: 'number', minimum: 0, maximum: 1 },
          missing_fields: {
            type: 'array',
            maxItems: 6,
            items: { type: 'string', maxLength: 80 }
          },
          reason_summary: { type: 'string', maxLength: 500 }
        }
      }
    };
  }

  function accountBriefSchema() {
    return {
      schemaVersion: '1',
      name: 'account_brief',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: [
          'company_summary',
          'likely_pain_points',
          'relevant_use_cases',
          'proof_points',
          'objections',
          'recommended_openers',
          'confidence'
        ],
        properties: {
          company_summary: { type: 'string', maxLength: 1200 },
          likely_pain_points: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 8 },
          relevant_use_cases: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 8 },
          proof_points: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 8 },
          objections: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 8 },
          recommended_openers: { type: 'array', items: { type: 'string', maxLength: 220 }, maxItems: 5 },
          confidence: { type: 'number', minimum: 0, maximum: 1 }
        }
      }
    };
  }

  function followupDraftSchema() {
    return {
      schemaVersion: '1',
      name: 'followup_draft',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: [
          'subject',
          'body_text',
          'body_html',
          'tone',
          'cta_type',
          'approval_required',
          'risk_flags',
          'confidence'
        ],
        properties: {
          subject: { type: 'string', maxLength: 120 },
          body_text: { type: 'string', maxLength: 4000 },
          body_html: { type: 'string', maxLength: 6000 },
          tone: { type: 'string', enum: DataModel.ENUMS.DRAFT_TONE },
          cta_type: { type: 'string', enum: DataModel.ENUMS.DRAFT_CTA },
          approval_required: { type: 'boolean' },
          risk_flags: { type: 'array', items: { type: 'string', maxLength: 120 }, maxItems: 8 },
          confidence: { type: 'number', minimum: 0, maximum: 1 }
        }
      }
    };
  }

  function meetingSummarySchema() {
    return {
      schemaVersion: '1',
      name: 'meeting_summary',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: [
          'stakeholders',
          'pains',
          'objections',
          'commitments',
          'next_steps',
          'fields_to_update',
          'confidence'
        ],
        properties: {
          stakeholders: {
            type: 'array',
            maxItems: 8,
            items: {
              type: 'object',
              additionalProperties: false,
              required: ['name', 'role', 'influence'],
              properties: {
                name: { type: 'string', maxLength: 120 },
                role: { type: 'string', maxLength: 120 },
                influence: { type: 'string', maxLength: 80 }
              }
            }
          },
          pains: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 10 },
          objections: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 10 },
          commitments: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 10 },
          next_steps: { type: 'array', items: { type: 'string', maxLength: 180 }, maxItems: 10 },
          fields_to_update: {
            type: 'object',
            additionalProperties: false,
            required: ['stage_hint', 'risk_flags', 'next_step', 'next_step_due'],
            properties: {
              stage_hint: { type: 'string', maxLength: 80 },
              risk_flags: { type: 'array', items: { type: 'string', maxLength: 120 }, maxItems: 8 },
              next_step: { type: 'string', maxLength: 180 },
              next_step_due: { type: 'string', maxLength: 40 }
            }
          },
          confidence: { type: 'number', minimum: 0, maximum: 1 }
        }
      }
    };
  }

  function dealRiskSchema() {
    return {
      schemaVersion: '1',
      name: 'deal_risk_scan',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: [
          'health_score',
          'risk_score',
          'risk_flags',
          'stage_recommendation',
          'manager_attention',
          'recommended_action',
          'confidence',
          'reason_summary'
        ],
        properties: {
          health_score: { type: 'integer', minimum: 0, maximum: 100 },
          risk_score: { type: 'integer', minimum: 0, maximum: 100 },
          risk_flags: { type: 'array', items: { type: 'string', maxLength: 120 }, maxItems: 8 },
          stage_recommendation: { type: 'string', maxLength: 80 },
          manager_attention: { type: 'boolean' },
          recommended_action: { type: 'string', maxLength: 180 },
          confidence: { type: 'number', minimum: 0, maximum: 1 },
          reason_summary: { type: 'string', maxLength: 500 }
        }
      }
    };
  }

  function get(jobType) {
    const map = {
      lead_score: leadScoreSchema,
      account_brief: accountBriefSchema,
      followup_draft: followupDraftSchema,
      meeting_summary: meetingSummarySchema,
      deal_risk_scan: dealRiskSchema,
    };
    const builder = map[jobType];
    if (!builder) {
      throw new Error('No schema registered for job type: ' + jobType);
    }
    return builder();
  }

  return {
    get,
  };
})();
