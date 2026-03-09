from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pr_monitor_app.analytics.embeddings import NoopEmbeddingProvider, OpenAIEmbeddingProvider, make_embedding_provider
from pr_monitor_app.analytics.event_embeddings import EventEmbeddingStore
from pr_monitor_app.analytics.framing import FramingDetector
from pr_monitor_app.analytics.metrics import compute_daily_topic_metrics
from pr_monitor_app.analytics.relevance import relevance_for_topic
from pr_monitor_app.analytics.sentiment import SentimentAnalyzer
from pr_monitor_app.analytics.text_features import event_text_hash, select_event_text
from pr_monitor_app.analytics.topic_embeddings import TopicEmbeddingStore
from pr_monitor_app.config import settings
from pr_monitor_app.db_sync import sync_db_session
from pr_monitor_app.logging import get_logger
from pr_monitor_app.models import Client, IngestionEvent, EventSubscription, Subscription, TopicLens
from pr_monitor_app.models_analytics import AnalysisStatus, EventAnalysis, EventTopicScore

log = get_logger(component="analytics.runner")


@dataclass(frozen=True)
class ProcessResult:
    events_processed: int
    events_failed: int
    topic_scores_written: int
    daily_metrics_written: int


def _now() -> datetime:
    return datetime.utcnow()


def _topics_for_event(session: Session, event_id: uuid.UUID) -> list[TopicLens]:
    # 1) Explicit topics linked through subscriptions
    topics = (
        session.execute(
            select(TopicLens)
            .join(Subscription, Subscription.topic_id == TopicLens.id)
            .join(EventSubscription, EventSubscription.subscription_id == Subscription.id)
            .where(EventSubscription.event_id == event_id)
            .where(Subscription.topic_id.is_not(None))
            .distinct()
        )
        .scalars()
        .all()
    )
    if topics:
        return list(topics)

    # 2) Client-only subscriptions: score against all topics for those clients
    client_ids = (
        session.execute(
            select(Subscription.client_id)
            .join(EventSubscription, EventSubscription.subscription_id == Subscription.id)
            .where(EventSubscription.event_id == event_id)
            .where(Subscription.client_id.is_not(None))
            .distinct()
        )
        .scalars()
        .all()
    )
    client_ids = [cid for cid in client_ids if cid is not None]
    if client_ids:
        return list(
            session.execute(select(TopicLens).where(TopicLens.client_id.in_(client_ids)))
            .scalars()
            .all()
        )

    # 3) Fallback: all topics
    return list(session.execute(select(TopicLens)).scalars().all())


def _upsert_event_analysis(
    session: Session,
    *,
    event_id: uuid.UUID,
    text_hash: str,
    sentiment_score: float | None,
    sentiment_label: str | None,
    frames_json: list[dict[str, Any]],
    status: AnalysisStatus,
    error_message: str | None,
    meta_json: dict[str, Any],
) -> None:
    now = _now()
    stmt = (
        insert(EventAnalysis)
        .values(
            event_id=event_id,
            analysis_version=int(settings.analytics_analysis_version),
            analyzed_at=now,
            text_hash=text_hash,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            frames_json=frames_json,
            status=status,
            error_message=error_message,
            meta_json=meta_json,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[EventAnalysis.event_id],
            set_={
                "analysis_version": int(settings.analytics_analysis_version),
                "analyzed_at": now,
                "text_hash": text_hash,
                "sentiment_score": sentiment_score,
                "sentiment_label": sentiment_label,
                "frames_json": frames_json,
                "status": status,
                "error_message": error_message,
                "meta_json": meta_json,
            },
        )
    )
    session.execute(stmt)


def _upsert_topic_score(
    session: Session,
    *,
    event_id: uuid.UUID,
    topic_id: uuid.UUID,
    client_id: uuid.UUID,
    relevance_score: float,
    keyword_score: float,
    embedding_score: float | None,
    reasons_json: dict[str, Any],
) -> None:
    now = _now()
    stmt = (
        insert(EventTopicScore)
        .values(
            event_id=event_id,
            topic_id=topic_id,
            client_id=client_id,
            relevance_score=relevance_score,
            keyword_score=keyword_score,
            embedding_score=embedding_score,
            computed_at=now,
            reasons_json=reasons_json,
        )
        .on_conflict_do_update(
            index_elements=[EventTopicScore.event_id, EventTopicScore.topic_id],
            set_={
                "client_id": client_id,
                "relevance_score": relevance_score,
                "keyword_score": keyword_score,
                "embedding_score": embedding_score,
                "computed_at": now,
                "reasons_json": reasons_json,
            },
        )
    )
    session.execute(stmt)


class AnalyticsProcessor:
    """Layer 2 analytics processor.

    Responsibilities:
      - Claim un-analyzed events
      - Compute deterministic sentiment + framing
      - Compute per-topic relevance (keyword + optional embeddings)
      - Optionally compute daily roll-up metrics
    """

    def __init__(self) -> None:
        self._sentiment = SentimentAnalyzer()
        self._framing = FramingDetector()

        self._embedding_provider = make_embedding_provider()
        self._embeddings_enabled = self._embedding_provider.model_name != "none"

        self._event_embedding_store: EventEmbeddingStore | None = None
        self._topic_embedding_store: TopicEmbeddingStore | None = None

        if self._embeddings_enabled:
            self._event_embedding_store = EventEmbeddingStore(self._embedding_provider)
            self._topic_embedding_store = TopicEmbeddingStore(self._embedding_provider)

        self._last_metrics_run_at: datetime | None = None

    def close(self) -> None:
        # Only OpenAI provider currently uses a live HTTP client
        if hasattr(self._embedding_provider, "close"):
            try:
                self._embedding_provider.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    def run_once(self, *, batch_size: int | None = None) -> ProcessResult:
        batch_size = int(batch_size or settings.analytics_batch_size)
        batch_size = max(1, min(500, batch_size))

        processed = 0
        failed = 0
        scores_written = 0
        metrics_written = 0

        with sync_db_session() as session:
            events = self._claim_events(session, batch_size=batch_size)

            for event in events:
                try:
                    written = self._process_one_event(session, event)
                    scores_written += written
                    processed += 1
                except Exception as e:
                    failed += 1
                    log.warning("event_analysis_failed", event_id=str(event.id), error=str(e))

            # Optionally compute daily metrics periodically
            if settings.analytics_compute_daily_metrics:
                metrics_written = self._maybe_compute_metrics(session)

        return ProcessResult(
            events_processed=processed,
            events_failed=failed,
            topic_scores_written=scores_written,
            daily_metrics_written=metrics_written,
        )

    def worker_loop(self) -> None:
        tick = max(1, int(settings.analytics_tick_seconds))
        log.info("analytics_worker_started", tick_seconds=tick, batch_size=settings.analytics_batch_size)

        try:
            while True:
                res = self.run_once(batch_size=settings.analytics_batch_size)
                if res.events_processed or res.events_failed:
                    log.info(
                        "analytics_worker_tick",
                        processed=res.events_processed,
                        failed=res.events_failed,
                        topic_scores_written=res.topic_scores_written,
                        daily_metrics_written=res.daily_metrics_written,
                    )
                time.sleep(tick)
        finally:
            self.close()

    def _claim_events(self, session: Session, *, batch_size: int) -> list[IngestionEvent]:
        now = _now()
        since = now - timedelta(days=int(settings.analytics_max_event_age_days))

        # Events needing analysis: no row, or outdated version, or previous error.
        q = (
            select(IngestionEvent)
            .outerjoin(EventAnalysis, EventAnalysis.event_id == IngestionEvent.id)
            .where(IngestionEvent.fetched_at >= since)
            .where(
                (EventAnalysis.event_id.is_(None))
                | (EventAnalysis.analysis_version < int(settings.analytics_analysis_version))
                | (EventAnalysis.status == AnalysisStatus.error)
            )
            .order_by(IngestionEvent.fetched_at.desc())
            .limit(batch_size)
            .with_for_update(of=IngestionEvent, skip_locked=True)
        )
        events = session.execute(q).scalars().all()
        return list(events)

    def _process_one_event(self, session: Session, event: IngestionEvent) -> int:
        text = select_event_text(title=event.title, summary=event.summary, content_text=event.content_text)
        if len(text) < int(settings.analytics_min_event_text_chars):
            # still allow analysis; just note that we had limited material
            meta = {"note": "event_text_short", "length": len(text)}
        else:
            meta = {}

        t_hash = event_text_hash(text)

        # Sentiment + framing
        sent = self._sentiment.analyze(text)
        frames = self._framing.detect(text, title=event.title)
        frames_json = [
            {"frame": f.frame, "score": f.score, "matches": f.matches, "matched_terms": f.matched_terms}
            for f in frames
        ]

        # Embedding (optional)
        event_emb: list[float] | None = None
        if self._embeddings_enabled and self._event_embedding_store is not None:
            try:
                event_emb = self._event_embedding_store.get_or_create(session, event.id, text=text)
                meta["embedding_model"] = self._event_embedding_store.embedding_model
            except Exception as e:
                # If embeddings fail, continue keyword-only rather than failing analysis.
                meta["embedding_error"] = str(e)
                log.warning("event_embedding_failed", event_id=str(event.id), error=str(e))
                event_emb = None

        # Upsert event analysis row
        _upsert_event_analysis(
            session,
            event_id=event.id,
            text_hash=t_hash,
            sentiment_score=sent.score,
            sentiment_label=sent.label,
            frames_json=frames_json,
            status=AnalysisStatus.success,
            error_message=None,
            meta_json=meta,
        )

        # Determine topics for scoring
        topics = _topics_for_event(session, event.id)

        topic_embs: dict[uuid.UUID, list[float]] = {}
        if self._embeddings_enabled and self._topic_embedding_store is not None:
            try:
                topic_embs = self._topic_embedding_store.ensure_embeddings(session, topics)
            except Exception as e:
                log.warning("topic_embeddings_failed", error=str(e))
                topic_embs = {}

        # Score and upsert
        written = 0
        for topic in topics:
            topic_emb = topic_embs.get(topic.id)
            res = relevance_for_topic(
                text=text,
                title=event.title,
                topic_query=topic.query_json or {},
                event_embedding=event_emb,
                topic_embedding=topic_emb,
            )
            _upsert_topic_score(
                session,
                event_id=event.id,
                topic_id=topic.id,
                client_id=topic.client_id,
                relevance_score=res.relevance_score,
                keyword_score=res.keyword_score,
                embedding_score=res.embedding_score,
                reasons_json=res.reasons,
            )
            written += 1

        return written

    def _maybe_compute_metrics(self, session: Session) -> int:
        now = _now()
        last = self._last_metrics_run_at
        # Compute at most once per hour per worker.
        if last and (now - last) < timedelta(hours=1):
            return 0
        self._last_metrics_run_at = now
        return compute_daily_topic_metrics(
            session,
            lookback_days=int(settings.analytics_daily_metrics_lookback_days),
        )
