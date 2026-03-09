from __future__ import annotations

import collections
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pr_monitor_app.logging import get_logger
from pr_monitor_app.models import IngestionEvent
from pr_monitor_app.models_analytics import DailyTopicMetric, EventAnalysis, EventTopicScore

log = get_logger(component="analytics.metrics")


def _event_day(e: IngestionEvent) -> date:
    dt = e.published_at or e.fetched_at
    return dt.date()


def compute_daily_topic_metrics(session: Session, *, lookback_days: int) -> int:
    """Compute daily topic metrics for the recent lookback window.

    This is intentionally simple: it recomputes metrics for the window and upserts results.
    For 10 clients / 60 topics this is inexpensive and robust.
    """
    lookback_days = max(1, int(lookback_days))
    since = datetime.utcnow() - timedelta(days=lookback_days)

    # Join event_topic_scores -> ingestion_events -> analyses
    rows = session.execute(
        select(
            EventTopicScore.client_id,
            EventTopicScore.topic_id,
            EventTopicScore.relevance_score,
            IngestionEvent.id,
            IngestionEvent.published_at,
            IngestionEvent.fetched_at,
            EventAnalysis.sentiment_score,
            EventAnalysis.frames_json,
        )
        .join(IngestionEvent, IngestionEvent.id == EventTopicScore.event_id)
        .outerjoin(EventAnalysis, EventAnalysis.event_id == IngestionEvent.id)
        .where(IngestionEvent.fetched_at >= since)
    ).all()

    # Accumulate per (client, topic, day)
    buckets: dict[tuple[Any, Any, date], dict[str, Any]] = {}

    for client_id, topic_id, rel, event_id, published_at, fetched_at, sent, frames_json in rows:
        day = (published_at or fetched_at).date()
        key = (client_id, topic_id, day)
        b = buckets.get(key)
        if b is None:
            b = {
                "count": 0,
                "relevance_sum": 0.0,
                "sent_sum": 0.0,
                "sent_count": 0,
                "frames": collections.Counter(),
            }
            buckets[key] = b
        b["count"] += 1
        b["relevance_sum"] += float(rel)
        if sent is not None:
            b["sent_sum"] += float(sent)
            b["sent_count"] += 1
        if isinstance(frames_json, list) and frames_json:
            # Consider only the top frame per event (most confident) for aggregation.
            top = frames_json[0]
            frame_name = top.get("frame") if isinstance(top, dict) else None
            if frame_name:
                b["frames"][str(frame_name)] += 1

    now = datetime.utcnow()
    upserts = 0

    for (client_id, topic_id, day), b in buckets.items():
        count = int(b["count"])
        avg_rel = float(b["relevance_sum"] / max(1, count))
        avg_sent = None
        if b["sent_count"]:
            avg_sent = float(b["sent_sum"] / max(1, b["sent_count"]))

        frames_counter: collections.Counter[str] = b["frames"]
        top_frames = [{"frame": k, "count": int(v)} for k, v in frames_counter.most_common(4)]

        stmt = (
            insert(DailyTopicMetric)
            .values(
                client_id=client_id,
                topic_id=topic_id,
                day=day,
                event_count=count,
                avg_relevance=avg_rel,
                avg_sentiment=avg_sent,
                top_frames_json=top_frames,
                computed_at=now,
            )
            .on_conflict_do_update(
                index_elements=[DailyTopicMetric.client_id, DailyTopicMetric.topic_id, DailyTopicMetric.day],
                set_={
                    "event_count": count,
                    "avg_relevance": avg_rel,
                    "avg_sentiment": avg_sent,
                    "top_frames_json": top_frames,
                    "computed_at": now,
                },
            )
        )
        session.execute(stmt)
        upserts += 1

    log.info("daily_topic_metrics_upserted", rows=len(rows), metrics=upserts, lookback_days=lookback_days)
    return upserts
