# Glassbox Operator v0.2

Includes RAG store, Google Sheets tools, and agent-friendly endpoints.

## Merged Platform

This repo now runs as a two-service platform instead of four separate apps:

- `outreach_app` is the CRM and execution plane.
  - Native operator endpoints: tasks, runs, RAG, Sheets, evidence packs
  - Vendored GTM service mounted at `/crm/gtm/*`
  - Agent bridge endpoints at `/agent/crm/*`
- `pr_monitor_app` is the monitoring and biotech intelligence plane.
  - Native narrative monitoring and agent job endpoints
  - Vendored biotech radar mounted at `/radar/*`
  - Agent bridge endpoints at `/agent/radar/*`
- `dashboard_app` is the separate React reporting layer.
  - Served on its own container and port
  - Proxies `/api/outreach/*` to `outreach_app`
  - Proxies `/api/monitor/*` to `pr_monitor_app`

HubSpot is removed from the runtime architecture. CRM handoff now goes through Google Sheets plus downstream Apps Script automation.

### Key merged endpoints

- `outreach_app`
  - `GET /agent/tools`
  - `GET /agent/crm/leads`
  - `POST /agent/crm/pipeline/ingest`
  - `POST /agent/crm/sequences/run-due`
  - `GET /crm/gtm/leads`
  - `GET /crm/gtm/metrics/summary`
- `pr_monitor_app`
  - `GET /agent/radar/companies`
  - `GET /agent/radar/programs`
  - `GET /agent/radar/opportunities`
  - `POST /agent/radar/pipeline/run`
  - `POST /agent/radar/watchlist/sync`
  - `GET /radar/api/opportunities`
  - `GET /radar/dashboard`

Run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export AUTO_CREATE_DB=true
uvicorn app.main:app --reload
```

Open: `http://localhost:8000/docs`

Agent endpoints require `X-API-Key` if `AGENT_API_KEYS` is configured.

Dashboard:

- `http://localhost:8103`

## Scheduled monitoring runs

Both apps can run continuously on intervals:

- `pr_monitor_app`: set `INGEST_ENABLE_SCHEDULER=true` for in-process ingestion ticks.
- `pr_monitor_app` pipeline jobs: run Celery worker + beat (`pr_monitor_worker`, `pr_monitor_beat` in `docker-compose.yml`).
- `outreach_app`: set `SCHEDULE_ENABLE_RUNNER=true` to process queued tasks on an interval.

`outreach_app` scheduler env vars:

- `SCHEDULE_POLL_SECONDS` (default `60`)
- `SCHEDULE_BATCH_SIZE` (default `10`)
- `SCHEDULE_REQUESTED_BY` (default `scheduler`)

## Google Sheets auth

Set `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` to the _JSON string_ of your service account key (or use ADC).

Also share the target spreadsheet with the service account email (Editor for writes).

Example:

```bash
export GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"
```

## Agent endpoints

- `GET /agent/tools` lists available tools.
- `POST /agent/tool_call` runs one tool.
- `POST /agent/execute` runs a multi-step plan (list of tool calls).

Protect agent endpoints with `AGENT_API_KEYS` and pass `X-API-Key: <key>`.

CAN: I put together a working “RAG store + Google Sheets integration + agent-callable API” service (FastAPI) that lets an agent:

- **Upsert/query/delete** from a **DB-backed RAG store**
- **Read/append/update/clear** a **Google Sheet**
- Call those capabilities through a single **agent tool-call endpoint** (`/agent/tool_call`)
- Get **policy-gated approvals** automatically for higher-risk actions (e.g., Sheets writes)
- Retrieve a full **evidence pack** for every run (tool inputs/outputs + artifacts)

[Download the project](sandbox:/mnt/data/glassbox_operator.zip)

---

## What you get

### 1) RAG store (DB-backed)

- Stores documents + chunks in SQLite (or any SQLAlchemy-supported DB)
- Uses a deterministic **hash-embedding fallback** (works offline)
- Optional OpenAI embeddings if you set `OPENAI_API_KEY`
- API endpoints + agent tool endpoints

### 2) Google Sheets integration

- Uses Google Sheets API via **service account JSON**
- Supports:
  - read range
  - append rows
  - update range
  - clear range

- Exposed both as:
  - direct REST endpoints: `/sheets/*`
  - agent tool calls: `sheets.read_range`, `sheets.append_rows`, etc.

### 3) Agent endpoint to “run, get data, modify”

Agent can call tools like:

- `rag.query`
- `rag.upsert_text`
- `sheets.read_range`
- `sheets.append_rows`
- `sheets.update_range`
- `sheets.clear_range`

…via one endpoint:

- `POST /agent/tool_call`

For multi-step workflows, use:

- `POST /agent/execute`

### 4) Evidence packs

Every run writes a folder like:

- `data/artifacts/run_<RUN_ID>/`
  - `tool_calls.jsonl`
  - `run_manifest.json`
  - `evidence_index.json`
  - `outputs/*`
  - `artifacts/*`

And you can download a zip:

- `GET /runs/{run_id}/evidence/download`

### OpenAI onboarding env vars

Layer 0 onboarding now accepts these env vars directly:

```bash
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_LLM_MODEL=gpt-4.1
ONBOARDING_AGENT_ENABLED=true
```

Usage:

- `OPENAI_API_KEY`: used by the Python OpenAI Agents SDK onboarding flow.
- `OPENAI_API_BASE`: optional base URL for OpenAI-compatible providers. If unset, defaults to `https://api.openai.com/v1`.
- `OPENAI_LLM_MODEL`: model used for Layer 0 onboarding agent runs. It is also accepted by the fallback LLM path.

If you want a different model only for onboarding, set:

```bash
ONBOARDING_AGENT_MODEL=gpt-4.1
```

Typical local run:

```bash
export OPENAI_API_KEY=...
export OPENAI_API_BASE=https://api.openai.com/v1
export OPENAI_LLM_MODEL=gpt-4.1
export ONBOARDING_AGENT_ENABLED=true
docker compose up -d --build
```

---

## The exact API endpoints you asked for

### RAG REST endpoints

- `POST /rag/upsert`
- `POST /rag/query`
- `DELETE /rag/document`
- `DELETE /rag/namespace/{namespace}`

### Sheets REST endpoints

- `POST /sheets/read`
- `POST /sheets/append`
- `POST /sheets/update`
- `POST /sheets/clear`

### Agent endpoints (the “single endpoint” for running tools)

Protected by `X-API-Key` if you set `AGENT_API_KEYS`.

- `GET /agent/tools` → list tools + risk tiers + JSON schemas
- `POST /agent/tool_call` → run one tool call
- `POST /agent/execute` → run multi-step plan (list of tool calls)

### Orchestrator endpoints (tasks/runs)

- `POST /tasks`
- `POST /tasks/{task_id}/run`
- `POST /runs/{run_id}/approve`
- `GET /runs/{run_id}/evidence`
- `GET /runs/{run_id}/evidence/download`

---

## How approvals work (important for “modify sheets”)

Tools are assigned a risk tier:

- Tier 0: readonly (no approval)
- Tier 1: internal write (no approval)
- Tier 2: external-impact (defaults to **needs approval**)
- Tier 3: financial/legal (defaults to **needs approval**)

By default:

- **Sheets reads** are Tier 0 → run immediately
- **Sheets writes** are Tier 2 → service returns an **approval challenge** with a token

Then you approve it:

- `POST /runs/{run_id}/approve` with the token

If you want Sheets writes to be fully autonomous, set:

```bash
export TIER2_REQUIRES_APPROVAL=false
```

---

## Quickstart

### Run locally

```bash
cd glassbox_operator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AUTO_CREATE_DB=true
export AGENT_API_KEYS="change-me-agent-key"

uvicorn app.main:app --reload
```

Open docs:

```text
http://localhost:8000/docs
```

---

## Google Sheets auth (service account)

1. Create a Google Cloud service account + key JSON
2. Share the target sheet with the service account email (Editor for writes)
3. Export JSON as a string:

```bash
export GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON="$(cat service_account.json)"
```

---

## Example calls

### 1) RAG upsert (REST)

```bash
curl -s http://localhost:8000/rag/upsert \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "company",
    "doc_id": "handbook_v1",
    "title": "Company Handbook",
    "source": "internal",
    "text": "We sell X. Our ICP is Y. Objections include Z...",
    "metadata": {"owner":"ops"}
  }' | jq
```

### 2) RAG query (REST)

```bash
curl -s http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "company",
    "query": "What is our ICP?",
    "top_k": 5
  }' | jq
```

### 3) Sheets read (agent tool call)

```bash
curl -s http://localhost:8000/agent/tool_call \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-agent-key" \
  -d '{
    "tool": "sheets.read_range",
    "args": {
      "spreadsheet_id": "YOUR_SHEET_ID",
      "range_a1": "Leads!A1:E20",
      "major_dimension": "ROWS"
    },
    "title": "Read leads sheet",
    "domain": "gtm",
    "requested_by": "agent"
  }' | jq
```

### 4) Sheets append (agent tool call → will likely require approval)

```bash
curl -s http://localhost:8000/agent/tool_call \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-agent-key" \
  -d '{
    "tool": "sheets.append_rows",
    "args": {
      "spreadsheet_id": "YOUR_SHEET_ID",
      "range_a1": "Leads!A:E",
      "values": [
        ["Acme Bio", "Jane Doe", "jane@acme.com", "Warm", "2026-03-04"]
      ],
      "value_input_option": "USER_ENTERED",
      "insert_data_option": "INSERT_ROWS"
    },
    "title": "Append new lead",
    "domain": "gtm",
    "requested_by": "agent"
  }' | jq
```

If you get back an approval challenge, approve it:

```bash
curl -s http://localhost:8000/runs/RUN_ID_HERE/approve \
  -H "Content-Type: application/json" \
  -d '{
    "token": "APPROVAL_TOKEN_HERE",
    "approved_by": "operator",
    "notes": "Approved sheets append"
  }' | jq
```

---

## What to plug into your agent

If your agent supports tool calling, the simplest pattern is:

1. Call `GET /agent/tools` to learn available tools + schemas
2. When it needs data from Sheets:
   - call `POST /agent/tool_call` with `tool="sheets.read_range"`

3. When it needs to write:
   - call `POST /agent/tool_call` with `tool="sheets.append_rows"` or `sheets.update_range`
   - if it receives an approval response, escalate to operator (or disable Tier2 approvals)

---
