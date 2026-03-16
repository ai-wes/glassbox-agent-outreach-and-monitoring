const DataModel = (() => {
  const ENUMS = {
    LEAD_STATUS: ['new', 'working', 'qualified', 'nurture', 'disqualified', 'closed'],
    DEAL_STAGE: ['new', 'qualified', 'discovery', 'proposal', 'negotiation', 'closed_won', 'closed_lost'],
    TASK_STATUS: ['open', 'done', 'canceled'],
    TASK_PRIORITY: ['urgent', 'high', 'medium', 'low'],
    JOB_STATUS: ['pending', 'leased', 'completed', 'retry', 'failed', 'dead_letter'],
    OUTPUT_STATUS: ['generated', 'applied', 'approved', 'rejected', 'error'],
    SENTIMENT: ['positive', 'neutral', 'negative', 'mixed', 'unknown'],
    INTENT_TAG: ['interested', 'not_now', 'no_budget', 'wrong_person', 'needs_info', 'unresponsive', 'unknown'],
    BUYER_PERSONA: ['decision_maker', 'influencer', 'evaluator', 'practitioner', 'unknown'],
    DRAFT_TONE: ['warm', 'direct', 'consultative', 'urgent'],
    DRAFT_CTA: ['reply', 'meeting', 'resource_share', 'soft_close'],
  };

  const TABLES = {
    Leads: {
      idField: 'lead_id',
      frozenRows: 1,
      headers: [
        'lead_id',
        'created_at',
        'updated_at',
        'source',
        'first_name',
        'last_name',
        'email',
        'company',
        'domain',
        'title',
        'country',
        'raw_inbound_text',
        'normalized_summary',
        'owner',
        'fit_score',
        'intent_score',
        'timing_score',
        'priority_score',
        'status',
        'next_action',
        'next_action_due',
        'last_touch_at',
        'last_ai_hash',
        'needs_review',
        'validation_errors',
        'latest_followup_draft_id'
      ]
    },
    Accounts: {
      idField: 'account_id',
      frozenRows: 1,
      headers: [
        'account_id',
        'created_at',
        'updated_at',
        'domain',
        'account_name',
        'industry',
        'size_band',
        'tier',
        'owner',
        'account_brief',
        'pain_points',
        'proof_points',
        'champion',
        'risk_flags',
        'health_score',
        'last_ai_hash'
      ]
    },
    Contacts: {
      idField: 'contact_id',
      frozenRows: 1,
      headers: [
        'contact_id',
        'created_at',
        'updated_at',
        'account_id',
        'name',
        'email',
        'title',
        'role_type',
        'persona',
        'linkedin_url',
        'influence_score'
      ]
    },
    Deals: {
      idField: 'deal_id',
      frozenRows: 1,
      headers: [
        'deal_id',
        'created_at',
        'updated_at',
        'account_id',
        'primary_contact_id',
        'owner',
        'stage',
        'amount',
        'close_date',
        'probability',
        'next_step',
        'next_step_due',
        'stall_reason',
        'risk_flags',
        'risk_score',
        'health_score',
        'last_activity_at',
        'ai_stage_recommendation',
        'last_ai_hash',
        'needs_review',
        'validation_errors'
      ]
    },
    Activities: {
      idField: 'activity_id',
      frozenRows: 1,
      headers: [
        'activity_id',
        'created_at',
        'entity_type',
        'entity_id',
        'channel',
        'direction',
        'timestamp',
        'subject',
        'snippet',
        'source_ref',
        'sentiment',
        'intent_tag',
        'metadata_json'
      ]
    },
    Tasks: {
      idField: 'task_id',
      frozenRows: 1,
      headers: [
        'task_id',
        'created_at',
        'entity_type',
        'entity_id',
        'owner',
        'task_type',
        'due_at',
        'priority',
        'status',
        'auto_generated',
        'notes'
      ]
    },
    AI_Jobs: {
      idField: 'job_id',
      frozenRows: 1,
      headers: [
        'job_id',
        'created_at',
        'updated_at',
        'job_type',
        'entity_type',
        'entity_id',
        'payload_hash',
        'priority',
        'status',
        'attempt_count',
        'lease_owner',
        'leased_until',
        'next_retry_at',
        'requested_by',
        'error_message'
      ]
    },
    AI_Outputs: {
      idField: 'output_id',
      frozenRows: 1,
      headers: [
        'output_id',
        'created_at',
        'updated_at',
        'job_id',
        'job_type',
        'entity_type',
        'entity_id',
        'prompt_key',
        'prompt_version',
        'schema_version',
        'model_name',
        'output_json',
        'confidence',
        'approved_by',
        'approved_at',
        'applied_to_record_at',
        'status',
        'error_message'
      ]
    },
    Prompt_Library: {
      idField: 'prompt_key',
      frozenRows: 1,
      headers: [
        'prompt_key',
        'version',
        'purpose',
        'system_text',
        'user_text',
        'input_schema_version',
        'output_schema_version',
        'active'
      ]
    },
    Routing_Rules: {
      idField: 'rule_id',
      frozenRows: 1,
      headers: [
        'rule_id',
        'active',
        'priority',
        'source_match',
        'domain_match',
        'company_tier',
        'country_match',
        'owner',
        'round_robin_pool',
        'task_type',
        'notes'
      ]
    },
    Config: {
      idField: 'key',
      frozenRows: 1,
      headers: ['key', 'value', 'description']
    },
    Logs: {
      idField: 'trace_id',
      frozenRows: 1,
      headers: [
        'ts',
        'level',
        'function_name',
        'entity_type',
        'entity_id',
        'job_id',
        'message',
        'latency_ms',
        'response_code',
        'trace_id'
      ]
    },
    Dashboard: {
      idField: 'metric_key',
      frozenRows: 1,
      headers: [
        'metric_key',
        'section',
        'metric',
        'value',
        'detail',
        'updated_at'
      ]
    },
    PR_Events: {
      idField: 'event_id',
      frozenRows: 1,
      headers: [
        'event_id',
        'published_at',
        'created_at',
        'source_type',
        'title',
        'author',
        'url',
        'sentiment',
        'detected_entities',
        'raw_text_excerpt'
      ]
    },
    Radar_Opportunities: {
      idField: 'opportunity_id',
      frozenRows: 1,
      headers: [
        'opportunity_id',
        'company_id',
        'company_name',
        'program_id',
        'program_target',
        'asset_name',
        'indication',
        'stage',
        'status',
        'tier',
        'radar_score',
        'outreach_angle',
        'risk_hypothesis',
        'updated_at',
        'dossier_path',
        'sheet_row_reference'
      ]
    }
  };

  const DEFAULT_CONFIG = [
    { key: 'OPENAI_BASE_URL', value: 'https://api.openai.com/v1', description: 'Base URL for the OpenAI-compatible Responses API.' },
    { key: 'OPENAI_MODEL', value: 'gpt-5.4', description: 'Model name for structured AI jobs.' },
    { key: 'OPENAI_REASONING_EFFORT', value: 'low', description: 'Reasoning effort for GPT-5 family models: minimal, low, medium, or high.' },
    { key: 'OPENAI_VERBOSITY', value: 'low', description: 'Verbosity for text outputs: low, medium, or high.' },
    { key: 'OPENAI_MAX_OUTPUT_TOKENS', value: '2500', description: 'Upper bound for generated output tokens per AI job.' },
    { key: 'WORKER_BATCH_SIZE', value: '8', description: 'Number of AI jobs to lease per worker execution.' },
    { key: 'JOB_LEASE_MINUTES', value: '10', description: 'Lease duration for a claimed AI job.' },
    { key: 'MAX_JOB_ATTEMPTS', value: '5', description: 'Maximum number of attempts before a job is dead-lettered.' },
    { key: 'HIGH_PRIORITY_THRESHOLD', value: '85', description: 'Priority score at or above which a lead is considered hot.' },
    { key: 'LEAD_REVIEW_THRESHOLD', value: '70', description: 'Priority score at or above which a follow-up task is auto-created.' },
    { key: 'FOLLOWUP_OVERDUE_HOURS', value: '24', description: 'Hours after next_action_due before a lead is considered overdue.' },
    { key: 'DEAL_STALE_AFTER_DAYS', value: '10', description: 'Days since last activity before an open deal is considered stale.' },
    { key: 'DIGEST_HOUR_LOCAL', value: '8', description: 'Local hour (0-23) for the daily digest trigger.' },
    { key: 'ENABLE_REP_DIGEST', value: 'true', description: 'Whether to send daily rep digests.' },
    { key: 'ENABLE_MANAGER_DIGEST', value: 'true', description: 'Whether to send daily manager digests.' },
    { key: 'MANAGER_DIGEST_RECIPIENTS', value: '', description: 'Comma-separated email addresses for the manager digest.' },
    { key: 'ROUND_ROBIN_OWNERS', value: '', description: 'Fallback comma-separated owner emails for lead routing.' },
    { key: 'OUTREACH_SENDER_NAME', value: '', description: 'Optional sender name for generated Gmail drafts.' },
    { key: 'DEFAULT_REPLY_TO', value: '', description: 'Optional reply-to address for generated Gmail drafts.' },
    { key: 'ENABLE_AUTO_APPLY_SAFE_FIELDS', value: 'true', description: 'If true, safe AI fields are written back automatically.' },
    { key: 'LOG_TO_SHEET', value: 'true', description: 'If true, structured logs are written to the Logs sheet.' },
    { key: 'AUTOMATION_PAUSED', value: 'false', description: 'If true, scheduled queue processing, hourly maintenance, and daily digests are paused.' },
    { key: 'OUTREACH_API_BASE_URL', value: 'https://sales-outreach.glassbox-bio.com', description: 'Base URL for the outreach host used by the Sheets dashboard and PR/radar sync.' },
    { key: 'ENABLE_PLATFORM_SYNC', value: 'true', description: 'If true, hourly maintenance refreshes platform dashboard sheets from the outreach host.' },
    { key: 'PLATFORM_SYNC_LIMIT', value: '100', description: 'Maximum number of PR events and radar opportunities to sync into Sheets per refresh.' }
  ];

  const DEFAULT_ROUTING_RULES = [
    {
      rule_id: 'rule_default_round_robin',
      active: true,
      priority: 100,
      source_match: '',
      domain_match: '',
      company_tier: '',
      country_match: '',
      owner: '',
      round_robin_pool: 'default',
      task_type: 'new_lead_followup',
      notes: 'Fallback rule that assigns all unmatched leads using the default round-robin pool.'
    }
  ];

  const DEFAULT_PROMPTS = [
    {
      prompt_key: 'lead_score',
      version: '1.0.0',
      purpose: 'Score new or updated leads for fit, intent, urgency, and priority.',
      system_text: `You are an expert B2B revenue operations analyst.
Return only JSON that follows the supplied schema.
Be conservative, fact-aware, and grounded in the provided context.
Scores must be integers from 0 to 100.
Do not invent facts not supported by the context.
If the context is incomplete, lower confidence and list the missing fields.`,
      user_text: `Analyze this lead record and recommend the next best action.

Context JSON:
{{context_json}}

Scoring guidance:
- fit_score: ICP and role fit
- intent_score: buying signal strength
- timing_score: urgency and near-term readiness
- priority_score: overall execution priority, weighted toward fit and intent
- buyer_persona: choose the closest persona label
- routing_hint: short assignment suggestion
- next_action: precise next step, under 160 characters
- missing_fields: most important missing data points
- reason_summary: concise explanation for a sales rep`,
      input_schema_version: '1',
      output_schema_version: '1',
      active: true
    },
    {
      prompt_key: 'account_brief',
      version: '1.0.0',
      purpose: 'Generate a concise account brief and messaging angles.',
      system_text: `You are an account strategist for a B2B sales team.
Return only JSON that follows the schema.
Base conclusions on the provided context and clearly avoid pretending to know unprovided facts.
When unsure, phrase recommendations as hypotheses.`,
      user_text: `Create an account brief.

Context JSON:
{{context_json}}

Requirements:
- Keep the company_summary under 120 words.
- Provide practical pain points and proof points useful for outreach.
- Objections should be plausible but conservative.
- Recommended openers should each fit in one sentence.`,
      input_schema_version: '1',
      output_schema_version: '1',
      active: true
    },
    {
      prompt_key: 'followup_draft',
      version: '1.0.0',
      purpose: 'Create a personalized follow-up email draft.',
      system_text: `You are a senior B2B sales rep.
Return only JSON that follows the schema.
Draft concise, professional, truthful outreach with a clear call to action.
Never fabricate specifics such as meetings, pricing, or product capabilities that are not in the context.
Avoid spammy language.`,
      user_text: `Draft a follow-up email.

Context JSON:
{{context_json}}

Drafting rules:
- Subject under 70 characters.
- Body text under 220 words.
- Tone should fit the relationship and urgency.
- body_html should be safe, minimal HTML using paragraphs and line breaks only.
- risk_flags should capture anything a human should review before sending.`,
      input_schema_version: '1',
      output_schema_version: '1',
      active: true
    },
    {
      prompt_key: 'meeting_summary',
      version: '1.0.0',
      purpose: 'Summarize meeting transcripts into actionable CRM updates.',
      system_text: `You are a sales meeting analyst.
Return only JSON that follows the schema.
Extract concrete facts from the transcript, and keep inferences conservative.
When the transcript does not support a field, leave it empty or use an empty list.`,
      user_text: `Summarize this meeting transcript and propose safe CRM updates.

Context JSON:
{{context_json}}

Requirements:
- Stakeholders should include names if present, otherwise role labels.
- next_steps should be concrete and action oriented.
- fields_to_update should only contain information reasonably supported by the context.
- Do not recommend stage changes with high certainty unless the evidence is explicit.`,
      input_schema_version: '1',
      output_schema_version: '1',
      active: true
    },
    {
      prompt_key: 'deal_risk_scan',
      version: '1.0.0',
      purpose: 'Score deal risk and recommend rescue actions.',
      system_text: `You are a sales manager reviewing pipeline health.
Return only JSON that follows the schema.
Assess deal health conservatively, using only the context provided.
Health and risk scores must be integers from 0 to 100.`,
      user_text: `Review this deal for risk and recommend the next action.

Context JSON:
{{context_json}}

Requirements:
- health_score: higher is better
- risk_score: higher means more at risk
- risk_flags should be concrete and short
- stage_recommendation should be a suggested stage name or empty
- manager_attention should be true only for meaningful risk
- recommended_action should be one clear step`,
      input_schema_version: '1',
      output_schema_version: '1',
      active: true
    }
  ];

  function getTableNames() {
    return Object.keys(TABLES);
  }

  function getHeaders(sheetName) {
    if (!TABLES[sheetName]) {
      throw new Error('Unknown sheet: ' + sheetName);
    }
    return TABLES[sheetName].headers.slice();
  }

  function getIdField(sheetName) {
    if (!TABLES[sheetName]) {
      throw new Error('Unknown sheet: ' + sheetName);
    }
    return TABLES[sheetName].idField;
  }

  return {
    ENUMS,
    TABLES,
    DEFAULT_CONFIG,
    DEFAULT_ROUTING_RULES,
    DEFAULT_PROMPTS,
    getTableNames,
    getHeaders,
    getIdField,
  };
})();
