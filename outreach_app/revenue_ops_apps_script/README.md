# Revenue Ops AI — Google Apps Script CRM Automation

This project is a container-bound Google Apps Script implementation for running a lightweight CRM and sales-automation operating system from Google Sheets.

It creates:

- A structured workbook with tabs for leads, accounts, contacts, deals, activities, tasks, AI jobs, AI outputs, prompts, routing rules, config, and logs
- Additional visibility tabs for a host-backed platform dashboard, PR events, and radar opportunities
- Installable edit and time-driven triggers
- A webhook endpoint for inbound leads, meeting transcripts, and external activities
- An AI job queue using Apps Script + Google Sheets
- Gmail draft generation for AI-produced follow-up emails
- Daily rep and manager digests

## Files

- `appsscript.json` — manifest and scopes
- `DataModel.gs` — all sheet schemas, enum values, default config, default routing rules, default prompts
- `Config.gs` — config + secret loading
- `Utils.gs` — shared helpers
- `Logging.gs` — structured logging
- `Repositories.gs` — sheet CRUD layer
- `Setup.gs` — workbook creation/repair and trigger installation
- `ActivityService.gs` — activity logging helpers
- `TaskService.gs` — task dedupe helpers
- `RoutingService.gs` — lead routing and round robin
- `PromptRegistry.gs` — prompt library access
- `AiSchemas.gs` — JSON Schemas for structured outputs
- `AiClient.gs` — OpenAI Responses API client
- `LeadService.gs` — lead intake, normalization, scoring workflow
- `AccountService.gs` — account brief workflow
- `DealService.gs` — stale-deal audit + risk scoring
- `MeetingService.gs` — transcript ingestion + meeting summary workflow
- `DraftService.gs` — follow-up draft workflow + Gmail draft creation
- `JobProcessor.gs` — job execution + AI output persistence
- `JobQueue.gs` — queueing, leasing, retries, dead-letter handling
- `Validation.gs` — sheet edit validation
- `SelectionService.gs` — selected-row context utilities
- `Menu.gs` — custom menu + UI entry points
- `Triggers.gs` — installable/time-driven trigger entry points
- `Webhook.gs` — `doGet` / `doPost` web app endpoint
- `SidebarServer.gs` + `Sidebar.html` — command-center sidebar
- `SmokeTests.gs` — quick manual tests

## Setup

1. Create a Google Sheet that will act as the revenue ops workbook.
2. Open **Extensions → Apps Script**.
3. Replace the project files with the files in this folder.
4. In Apps Script **Project Settings → Script Properties**, set:
   - `OPENAI_API_KEY` = your OpenAI API key
   - `OUTREACH_API_KEY` = the outreach host API key used for `/agent/*` endpoints
5. Run `setupProject()` manually once from the Apps Script editor.
6. Approve the required permissions.
7. Reload the spreadsheet and use the **Revenue Ops** menu.
8. Deploy the script as a **Web app**:
   - Execute as: **Me**
   - Who has access: whichever level matches your security requirements
9. Copy the web app URL for inbound webhooks.

`setupProject()` automatically:

- Binds the active spreadsheet ID into script properties
- Creates or repairs all required sheets
- Seeds default config rows
- Seeds default routing rules
- Seeds default prompts
- Creates the webhook secret in script properties
- Installs triggers:
  - On edit
  - Every 5 minutes
  - Hourly
  - Daily

## Config you can change in the `Config` sheet

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_REASONING_EFFORT`
- `OPENAI_VERBOSITY`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `WORKER_BATCH_SIZE`
- `JOB_LEASE_MINUTES`
- `MAX_JOB_ATTEMPTS`
- `HIGH_PRIORITY_THRESHOLD`
- `LEAD_REVIEW_THRESHOLD`
- `FOLLOWUP_OVERDUE_HOURS`
- `DEAL_STALE_AFTER_DAYS`
- `DIGEST_HOUR_LOCAL`
- `ENABLE_REP_DIGEST`
- `ENABLE_MANAGER_DIGEST`
- `MANAGER_DIGEST_RECIPIENTS`
- `ROUND_ROBIN_OWNERS`
- `OUTREACH_SENDER_NAME`
- `DEFAULT_REPLY_TO`
- `ENABLE_AUTO_APPLY_SAFE_FIELDS`
- `LOG_TO_SHEET`
- `OUTREACH_API_BASE_URL`
- `ENABLE_PLATFORM_SYNC`
- `PLATFORM_SYNC_LIMIT`

## Platform dashboard sync

The workbook can pull a live operational view from the outreach host and write it into:

- `Dashboard`
- `PR_Events`
- `Radar_Opportunities`

Menu actions:

- `Revenue Ops → Refresh Platform Views`
- `Revenue Ops → Open Command Center`

The command center sidebar now also shows the latest platform status bundle.
It also includes pause/resume controls for scheduled automation.

Required host endpoints:

- `/agent/platform/status`
- `/agent/platform/pr/events`
- `/agent/platform/radar/opportunities`

Authentication uses `X-API-Key` with the `OUTREACH_API_KEY` script property.

## Pause scheduled automation

The sidebar can pause or resume scheduled execution without deleting triggers.

When paused:

- the 5-minute AI queue trigger is skipped
- hourly maintenance is skipped
- daily digest automation is skipped

Manual menu actions still work.

## Webhook contract

All webhook requests must include the shared secret, either:

- In the JSON body as `secret`
- Or in the query string as `?secret=...`

### Example inbound lead request

```bash
curl -X POST "YOUR_WEB_APP_URL?secret=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "lead",
    "source": "website_form",
    "first_name": "Jordan",
    "last_name": "Lee",
    "email": "jordan.lee@example.com",
    "company": "Acme Robotics",
    "title": "Director of Revenue Operations",
    "country": "US",
    "message": "We are looking to improve lead routing and follow-up automation."
  }'
```

### Example meeting transcript request

```bash
curl -X POST "YOUR_WEB_APP_URL?secret=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "meeting_transcript",
    "linked_entity_type": "deal",
    "linked_entity_id": "deal_123",
    "subject": "Discovery call",
    "timestamp": "2026-03-07T09:30:00-08:00",
    "participants": ["Jane Buyer", "Alex Rep"],
    "transcript_text": "Customer approved budget and asked for pricing by Friday."
  }'
```

### Example external activity request

```bash
curl -X POST "YOUR_WEB_APP_URL?secret=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "activity",
    "entity_type": "lead",
    "entity_id": "lead_123",
    "channel": "email",
    "direction": "inbound",
    "timestamp": "2026-03-07T10:05:00-08:00",
    "subject": "Re: Intro",
    "snippet": "Can we talk next week?"
  }'
```

## Normal operating flow

### Inbound lead
1. Webhook hits `doPost`
2. Lead is normalized and deduped
3. Account and contact are upserted
4. Activity is logged
5. `lead_score` AI job is queued
6. `account_brief` AI job is queued if needed
7. Tasks are auto-created for follow-up

### AI worker
1. `processPendingJobs()` runs every 5 minutes
2. Jobs are leased with `LockService`
3. Prompt is rendered from `Prompt_Library`
4. Structured JSON is requested from the AI model
5. Output is stored in `AI_Outputs`
6. Safe fields are written back to the core sheets
7. Draft jobs become available for Gmail draft creation

### Draft generation
1. Select a row in **Leads** or **Deals**
2. Use **Revenue Ops → Generate Selected Follow-Up Draft**
3. Wait for the worker to process the queue
4. Use **Revenue Ops → Create Gmail Draft for Selected Record**

## Manual smoke tests

- `smokeTestIngestLead()`
- `smokeTestMeetingTranscript()`
- `smokeTestProcessQueue()`

## Notes

- Installable triggers run as the account that created them, so digests and background jobs execute under the script owner’s identity.
- The webhook endpoint uses a shared secret because Apps Script web apps do not expose request headers in the event object.
- Gmail draft creation is draft-first by design. The script never auto-sends sales email.
- This implementation keeps the workbook as the visible control plane. If volume grows, move the queue and canonical records to a database while keeping the sheet as the operator UI.
