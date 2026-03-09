# Platform Audit 2026-03-07

## 2026-03-08 Update

- `pr_monitor_app` now bootstraps the configured `RSS_FEEDS` into `sources` on startup and via `POST /admin/bootstrap/rss-sources`.
- The provided feed list has been seeded into `data/pr_monitor.db`, and the PR ingestion plane now has managed RSS sources instead of only `__subscription_ingestion__`.
- Raw market events are flowing from those feeds, but normalized `events` are still at `0`, so the enrichment / clustering / downstream processing path still needs stabilization.
- `GET /agent/reports/market/events` now falls back to recent `raw_events` when normalization has not populated `events`, so the dashboard and agent callers can still retrieve useful market signals.
- Two stale podcast feed URLs were normalized in code:
  - `https://rss.art19.com/hard-fork` -> `https://feeds.simplecast.com/l2i9YnTd`
  - `https://rss.art19.com/all-in` -> `https://rss.libsyn.com/shows/254861/destinations/1928300.xml`
- The provided `https://latent.space/rss.xml` endpoint also appeared stale during ingestion and is now normalized to `https://www.latent.space/feed`.

## What was fixed

- `outreach_app` config now accepts comma-separated `.env` values for `RSS_FEEDS` and `APPROVED_PROOF_SNIPPETS` instead of failing during settings load.
- `GET /crm/gtm/replies` now exists and returns recorded reply events.
- `GET /agent/crm/replies` now exists so agent consumers can inspect replies without scraping metrics alone.

## Highest-priority operational gaps

1. Host routing is inconsistent with how callers are using the system.
   - `sales-outreach.glassbox-bio.com` is serving the outreach app.
   - Radar endpoints exist in code, but only on `pr_monitor_app`.
   - Requests like `GET /radar/healthz` and `GET /agent/radar/opportunities` against the sales host will keep returning `404` unless a reverse proxy or unified gateway routes them to `pr_monitor_app`.

2. The PR and radar planes are technically up but effectively empty.
   - `data/radar.db` has `0` companies, programs, opportunities, signals, and pipeline runs.
   - `data/pr_monitor.db` has `0` clients, subscriptions, events, alerts, briefs, and outputs.
   - Agents can query these services, but there is almost nothing useful to return yet.

3. Radar is still pointed at demo watchlist data.
   - `docker-compose.yml` uses `RADAR_WATCHLIST_PATH=/app/watchlists/sample_watchlist.yaml`.
   - The sample file contains fake `.example` companies and empty `rss_feeds`.
   - That means the radar pipeline is not monitoring real companies or real press surfaces.

4. Daily podcast automation is not reliable in the deployed runtime.
   - `daily_podcast_reports` already contains recorded failures.
   - One run failed with `No module named 'openai'`.
   - Another run completed without producing the expected digest markdown.
   - This needs image/runtime verification, not just code review.

5. PR ingestion and processing depend on real source and client configuration that is not present.
   - `sources` contains only `__subscription_ingestion__`.
   - There are no real subscriptions, clients, topics, or brand configs to drive alerting and briefs.
   - Without seeded customer context, the PR side cannot become an informational asset.

## Medium-priority code and architecture cleanup

1. The PR codebase still carries legacy `npe.*` imports in active modules.
   - Examples include `pr_monitor_app/ingestion/runner.py` and `pr_monitor_app/llm/openai_compat.py`.
   - A local `npe/` package exists, so imports may work today, but this is fragile and increases deployment drift risk.

2. The PR stack has two scheduler patterns that need clearer ownership.
   - APScheduler drives subscription ingestion when `INGEST_ENABLE_SCHEDULER=true`.
   - Celery beat drives `npe.ingest_sources` and `npe.process_pipeline`.
   - The system should document which scheduler is authoritative for which workload, otherwise operators will misconfigure cadence and duplicate work.

3. Local defaults and deployment defaults are misaligned.
   - Outreach defaults to `sqlite+aiosqlite:///./glassbox_gtm.db`.
   - Compose overrides that to `/app/data/gtm.db`.
   - This makes local smoke tests and manual runs confusing unless the env is explicit.

4. Documentation is stale in places.
   - The README still includes older run instructions and mixed architecture messaging.
   - It should clearly describe:
     - which host serves which app,
     - which endpoints live on each app,
     - how to seed real watchlists and subscriptions,
     - how to run Celery worker and beat,
     - how to validate data freshness.

## Security and hygiene

1. `.env` currently contains live-looking credentials.
   - Rotate those secrets immediately.
   - Move deployment secrets to the platform secret manager or environment injection.
   - Keep only `.env.example` in the repo.

2. Default placeholder secrets still appear in compose.
   - `OPERATOR_SECRET=change-me`
   - `AGENT_API_KEYS=change-me-agent-key`
   - These should not survive into any shared environment.

## Concrete next steps

1. Put a gateway in front of both apps or separate the hostnames cleanly.
   - Option A: one domain with path routing.
   - Option B: one domain per service and fix all callers to use the correct host.

2. Replace the sample radar watchlist with real biotech targets.
   - Add real company domains.
   - Add real RSS feeds or other sources.
   - Run watchlist sync and then a full radar pipeline.

3. Seed the PR system with at least one real client profile, topic set, subscriptions, and sources.
   - Without this, briefs, alerts, and agent outputs will remain empty by design.

4. Verify the deployed PR image against the repo.
   - Confirm `openai` and podcast dependencies are installed.
   - Confirm the worker and beat commands use the current code.
   - Confirm Redis is reachable and task execution is not only being enqueued but also consumed.

5. Remove or migrate legacy `npe.*` imports.
   - Standardize on `pr_monitor_app.*` to reduce packaging ambiguity.

6. Add a basic readiness checklist.
   - `GET /healthz`
   - `GET /crm/gtm/health`
   - `GET /radar/healthz`
   - `GET /admin/scheduler`
   - `POST /admin/run/ingest?sync=true`
   - `POST /admin/run/process?sync=true`
   - `GET /agent/reports/radar/opportunities`
   - `GET /agent/crm/replies`
