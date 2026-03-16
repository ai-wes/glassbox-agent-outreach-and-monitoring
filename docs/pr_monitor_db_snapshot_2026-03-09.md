# PR Monitor DB Snapshot

Generated from `data/pr_monitor.db` on 2026-03-09.

## Executive Summary

- The active persistence path is `sources -> raw_events -> events -> event_clusters`.
- Core ingestion storage is populated:
  - `sources`: 24
  - `raw_events`: 454
  - `events`: 454
  - `event_clusters`: 446
  - `event_cluster_map`: 454
- Client strategy / downstream activation is inactive:
  - `clients`: 0
  - `topic_lenses`: 0
  - `subscriptions`: 0
  - `client_events`: 0
  - `strategic_briefs`: 0
  - `creative_draft_sets`: 0
  - `alerts`: 0
  - `brand_configs`: 0
- `GET /events` showing 100 rows is not a storage cap. The route defaults to `limit=100`, while the DB currently contains 454 rows.

## Table Counts

| Table | Rows |
|---|---:|
| sources | 24 |
| raw_events | 454 |
| events | 454 |
| event_clusters | 446 |
| event_cluster_map | 454 |
| daily_podcast_reports | 2 |
| clients | 0 |
| topic_lenses | 0 |
| subscriptions | 0 |
| client_events | 0 |
| strategic_briefs | 0 |
| creative_draft_sets | 0 |
| alerts | 0 |
| brand_configs | 0 |
| ingestion_events | 0 |
| event_analyses | 0 |
| event_embeddings | 0 |
| event_topic_scores | 0 |
| daily_topic_metrics | 0 |

## Event Storage Quality

- `events.total`: 454
- `events.with_raw_event_link`: 454
- `events.with_title`: 454
- `events.with_url`: 454
- `events.with_raw_text`: 454
- `events.with_author`: 270
- `events.with_entities`: 453
- `events.with_embedding`: 454
- `events.with_nonzero_sentiment`: 450
- `events.with_engagement_stats`: 0
- `events.raw_text_avg_len`: 7,615 chars
- `events.raw_text_min_len`: 175 chars
- `events.raw_text_max_len`: 123,583 chars
- `events.raw_text_ge_1k`: 342
- `events.raw_text_ge_10k`: 75

## Source Mix

- `blog`: 261 events
- `news`: 193 events

### Active Sources by Type

- `blog`: 15
- `news`: 9

### Top Sources by Event Count

| Source | Type | Events | Avg raw_text length |
|---|---|---:|---:|
| ScienceDaily | news | 66 | 1,030.5 |
| New Scientist | news | 52 | 496.8 |
| All-In Podcast | blog | 50 | 8,857.9 |
| Hard Fork | blog | 50 | 2,562.1 |
| Lex Fridman Podcast | blog | 50 | 8,652.3 |
| Practical AI | blog | 50 | 5,849.4 |
| TechCrunch | news | 27 | 422.0 |
| Ars Technica | news | 22 | 2,067.5 |
| Futurehouse Newsletter | blog | 21 | 32,508.1 |
| ByteByteGo | blog | 20 | 23,743.0 |
| Latent Space | blog | 20 | 39,724.4 |
| The Verge | news | 16 | 3,075.8 |
| BioPharma Dive | news | 10 | 918.8 |

## Freshness

Most recent event dates by source:

- TechCrunch: 2026-03-09 04:35:06 UTC
- New Scientist: 2026-03-09 04:00:03 UTC
- ScienceDaily: 2026-03-09 00:16:40 UTC
- The Verge: 2026-03-08 17:51:15 UTC
- Ars Technica: 2026-03-08 13:13:03 UTC
- Futurehouse Newsletter: 2026-03-08 10:00:00 UTC

Recent event volume by publish date:

- 2026-03-09: 3
- 2026-03-08: 28
- 2026-03-07: 33
- 2026-03-06: 63
- 2026-03-05: 21
- 2026-03-04: 25

## Richness Findings

### Good

- Every normalized `event` has a `raw_event_id`, title, URL, raw text, sentiment, and embedding.
- Every `raw_event` has a non-empty JSON payload.
- No broken `events -> raw_events` foreign links were found.
- No `raw_events` are waiting on normalization; all 454 have matching `events`.
- Clustering has executed successfully on the current corpus.

### Weak / Suspicious

- `engagement_stats` is empty for all 454 events in both `raw_events.payload` and normalized `events`.
- Author extraction is missing for 184 of 454 events, concentrated in feeds like ScienceDaily, New Scientist, and podcast/newsletter feeds.
- Entity extraction quality is poor. Top entities include noise such as:
  - `The`
  - `#8217`
  - `#8211`
  - `This`
  - `Website`
- Some normalized documents are extremely large, especially from newsletters/podcast transcripts:
  - Latent Space max observed: 123,583 chars
  - ByteByteGo max observed: 68,502 chars
- The strategic layer is completely idle because there are no clients or topics to score against.

## Example Stored Records

### Example News Event

- Source: The Verge
- Title: `Time’s running out to get a free gift card when you preorder a new MacBook`
- Author: `Cameron Faulkner`
- Published: `2026-03-07 17:00:00 UTC`
- Raw text length: `12,997`
- Stored entities:
  - `Time`
  - `This`
  - `The Verge`
  - `Barcelona`
  - `Apple`
  - `#8230`
  - `#038`
- Sentiment: `0.999`

### Example Blog Event

- Source: Latent Space
- Title: `Every Agent Needs a Box — Aaron Levie, Box`
- Author: empty
- Published: `2026-03-05 00:54:45 UTC`
- Raw text length: `123,583`
- Stored entities:
  - `Every Agent Needs`
  - `Box`
  - `Aaron Levie`
  - `Code Reviews`
  - `Silicon Valley`
  - `Wall Street`
  - `#8220`
  - `#8221`
  - `#8217`
- Sentiment: `1.0`

## Architecture Gap

The database contains two overlapping PR schemas:

1. Active schema:
   - `sources`
   - `raw_events`
   - `events`
   - `event_clusters`
   - `client_events` and downstream outputs

2. Inactive parallel schema:
   - `subscriptions`
   - `ingestion_events`
   - `event_analyses`
   - `event_embeddings`
   - `event_topic_scores`
   - `daily_topic_metrics`

Right now the first half is producing data, but the strategic second half is not producing any rows because there is no client/topic context in the DB.

## Code-Level Notes

- `pr_monitor_app/api/routes/events.py` defaults to `limit=100`, which explains the API count mismatch.
- `pr_monitor_app/pipeline/run.py` currently imports processing code that requires `vaderSentiment`; in this environment, importing that pipeline failed with `ModuleNotFoundError: No module named 'vaderSentiment'`.
- The repository still contains `npe.*` import paths in `pr_monitor_app/ingestion/runner.py` and `pr_monitor_app/llm/openai_compat.py`. Those imports resolve in this checkout because an `npe/` package exists, but the split naming increases drift risk.

## Recommended Next Checks

1. Seed at least one `client` and one `topic_lens`, then re-run processing to verify `client_events`, `strategic_briefs`, and `alerts` start filling.
2. Decide whether the app should keep both event schemas. If not, remove or migrate the unused `ingestion_events` / `event_analyses` path to reduce confusion.
3. Improve normalization/entity extraction:
   - strip HTML entities before phrase extraction
   - filter stopwords like `The`, `This`, `Website`
   - cap very large `raw_text` inputs before downstream analysis
4. Decide whether `engagement_stats` should be populated for RSS/blog sources or left intentionally empty.
