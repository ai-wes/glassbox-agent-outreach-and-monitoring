# Platform Runtime Repair Snapshot

Date: 2026-03-09

## PR monitor

- Live database repaired and replaced at `data/pr_monitor.db`.
- Recovery source of truth: `sources` + `raw_events`.
- Old corrupt DB and hot journal were preserved under timestamped `.bak` files in `data/`.

Current counts:

- `sources`: 24
- `raw_events`: 454
- `events`: 454
- `event_clusters`: 446
- `event_cluster_map`: 454
- `daily_podcast_reports`: 2
- `clients`: 0
- `subscriptions`: 0
- `alerts`: 0

Quality checks:

- `detected_entities` valid JSON: 454 / 454
- `author` present: 270 / 454
- `engagement_stats` present: 0 / 454
- average normalized `raw_text` length: 2955.1 chars
- max normalized `raw_text` length: 49999 chars
- SQLite journal present on live DB: no

Example stored events:

1. `news` | Ring privacy / TechCrunch | Connie Loizos
2. `news` | Ancient reptile / New Scientist
3. `news` | Particles and Einstein paths / ScienceDaily
4. `news` | ModRetro funding / TechCrunch | Anthony Ha
5. `news` | Ketamine depression study / ScienceDaily

Operational warnings still true:

- No PR clients are configured.
- No PR subscriptions are configured.
- Client events, alerts, and briefs will stay empty until client/topic/subscription records are seeded.
- Latest stored daily podcast report is still in `error` state from prior runs.

## Radar

Current counts:

- `companies`: 0
- `programs`: 0
- `opportunities`: 0
- `signals`: 0
- `pipeline_runs`: 0

Operational warnings still true:

- `watchlists/watchlist.yaml` exists but is intentionally empty.
- Radar cannot produce useful outputs until real companies/programs are seeded from the watchlist.
- Sheets export is not active because there are no qualifying opportunities and no configured spreadsheet target.

## New status surfaces

Available on the outreach host after integration:

- `/admin/runtime-status`
- `/agent/radar/status`
- `/radar/api/status`

These endpoints expose the exact “healthy but empty” conditions instead of only returning a generic 200 status.
