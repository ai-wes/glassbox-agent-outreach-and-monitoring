from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.analytics.ai_pr_measurement import run_ai_pr_measurement_from_settings
from pr_monitor_app.ingestion.runner import ingest_sources
from pr_monitor_app.pipeline.clustering import cluster_new_events
from pr_monitor_app.pipeline.creativity import generate_briefs_and_drafts
from pr_monitor_app.pipeline.sync_subscription_events import sync_subscription_events_to_raw
from pr_monitor_app.pipeline.normalization import normalize_new_raw_events
from pr_monitor_app.pipeline.scoring import score_new_events
from pr_monitor_app.pipeline.topic_index import ensure_topic_embeddings

log = structlog.get_logger(__name__)


async def run_ingestion(session: AsyncSession) -> dict[str, Any]:
    return await ingest_sources(session)


async def run_processing(session: AsyncSession) -> dict[str, Any]:
    """
    End-to-end pipeline:
      - sync subscription ingestion events to RawEvent
      - embed topics
      - normalize raw events
      - cluster events
      - score into client-topic relevance
      - generate briefs + drafts (optional LLM)
      - send alerts
    """
    out: dict[str, Any] = {}
    out["sync_subscription"] = await sync_subscription_events_to_raw(session)
    out["topic_embeddings"] = await ensure_topic_embeddings(session)
    out["normalize"] = await normalize_new_raw_events(session)
    out["cluster"] = await cluster_new_events(session)
    out["score"] = await score_new_events(session)
    out["briefs"] = await generate_briefs_and_drafts(session)
    try:
      from pr_monitor_app.pipeline.alerting import send_alerts

      out["alerts"] = await send_alerts(session)
    except Exception as exc:
      log.warning("pipeline_alerting_unavailable", error=str(exc))
      out["alerts"] = {"skipped": True, "reason": str(exc)}
    out["ai_pr_measurement"] = await asyncio.to_thread(run_ai_pr_measurement_from_settings)

    log.info("pipeline_run_complete", **out)
    return out
