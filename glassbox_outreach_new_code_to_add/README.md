# Glassbox Outreach Platform

This repository implements the core of a data‑driven outbound pipeline for B2B go‑to‑market operations.  It provides a deterministic backend, a worker system for scraping and enrichment, and a light operator console via Google Sheets and Apps Script.  The design follows a "glassbox" ethos: every fact about a lead is captured alongside evidence, and state transitions are audited.

## Architecture

The system comprises several components:

* **FastAPI backend**: exposes REST endpoints for submitting and monitoring jobs, managing leads, and integrating with other services such as Sheets and agents.  The API is built on top of SQLAlchemy and Postgres for persistence and uses Pydantic for schema validation.
* **Celery worker**: executes long‑running tasks such as discovering target companies and contacts via Playwright, enriching and verifying emails, and scoring leads.  Workers communicate with the backend via a shared database and use Redis as a task broker.
* **Playwright scraping layer**: encapsulated in helper functions and tasks to collect data from websites.  Each scrape stores raw HTML snapshots, extracted fields, timestamps, and selectors to enable reproducibility.
* **Google Sheets integration**: connectors are provided for syncing leads and job statuses to Sheets, enabling operators to review and approve leads without needing to interact with the database directly.  A complementary Apps Script adds custom menus and triggers within Sheets to queue jobs and refresh data.
* **Docker environment**: the project includes `docker-compose.yml` and individual `Dockerfile`s to orchestrate the API, worker, Redis, and Postgres services locally or in production.

## Getting Started

### Prerequisites

* Docker and Docker Compose installed locally.
* A Google service account with permission to access your target spreadsheet, along with a credentials JSON file.

### Running the stack locally

1. Copy your Google service account JSON into `api/.secrets/credentials.json`.
2. Create a `.env` file in `api/` with the following variables:

   ```bash
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/outreach
   REDIS_BROKER_URL=redis://redis:6379/0
   GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id
   GOOGLE_SERVICE_ACCOUNT_FILE=.secrets/credentials.json
   ```

3. Run `docker-compose up --build` from the repository root.  The API will be accessible at `http://localhost:8000` and Celery workers will start processing tasks.

4. Open your Google Sheet to interact with the system via custom menus provided by the Apps Script.

### Structure

```
glassbox_outreach/
├── README.md
├── docker-compose.yml
├── api/
│   ├── Dockerfile
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── crud.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── health.py
│   │   │   ├── jobs.py
│   │   │   └── leads.py
│   │   ├── celery_app.py
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   ├── discovery.py
│   │   │   ├── enrichment.py
│   │   │   ├── scoring.py
│   │   │   └── sync_sheets.py
│   │   ├── playwright_utils.py
│   │   └── sheets.py
│   ├── requirements.txt
│   └── .secrets/ (ignored via .gitignore)
├── worker/
│   ├── Dockerfile
│   └── celery_worker.py
└── apps_script/
    ├── Code.gs
    └── appsscript.json
```

This initial version sets up the skeleton for Phase 1 described in the specification: discovery via Playwright, enrichment, scoring, and syncing to Google Sheets.  Subsequent phases can extend the models, tasks, and API endpoints as needed.