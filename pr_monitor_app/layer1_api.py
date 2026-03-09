from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from pr_monitor_app.config import settings
from pr_monitor_app.db_sync import SessionLocalSync
from pr_monitor_app.ingestion.layer1_runner import (
    ingest_one_subscription,
    release_subscription_lock,
    store_event_and_link,
    try_acquire_subscription_lock,
)
from pr_monitor_app.ingestion.webhook import webhook_payload_to_candidate
from pr_monitor_app.logging import configure_logging, get_logger
from pr_monitor_app.models import (
    Client,
    EventSubscription,
    IngestionEvent,
    Subscription,
    SubscriptionType,
    TopicLens,
)
from pr_monitor_app.models_analytics import DailyTopicMetric, EventAnalysis, EventTopicScore
from pr_monitor_app.schemas import (
    ClientCreate,
    ClientOut,
    EventAnalysisOut,
    EventTopicScoreOut,
    ClientEventFeedItem,
    DailyTopicMetricOut,
    IngestionEventOut,
    SubscriptionCreate,
    SubscriptionOut,
    TopicCreate,
    TopicOut,
    WebhookEventIn,
)
from pr_monitor_app.scheduler import start_scheduler
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.robots import RobotsCache

log = get_logger(component="api")


def get_db() -> Iterator[Session]:
    db = SessionLocalSync()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    app = FastAPI(title="NPE Layer 1+2", version="0.1.0")

    @app.on_event("startup")
    def _startup() -> None:
        if settings.db_auto_create:
            from pr_monitor_app.models import Base
            from pr_monitor_app.db_sync import ENGINE_SYNC
            Base.metadata.create_all(bind=ENGINE_SYNC)
            log.info("db_auto_create_done")

        if settings.ingest_enable_scheduler:
            start_scheduler()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # Clients
    @app.post("/clients", response_model=ClientOut)
    def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
        existing = db.execute(select(Client).where(Client.name == payload.name)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="client already exists")
        c = Client(
            name=payload.name,
            messaging_pillars=payload.messaging_pillars,
            risk_keywords=payload.risk_keywords,
            audience_profile=payload.audience_profile,
            brand_voice_profile=payload.brand_voice_profile,
            competitors=payload.competitors,
            signal_recipient=payload.signal_recipient,
            telegram_recipient=payload.telegram_recipient,
            whatsapp_recipient=payload.whatsapp_recipient,
        )
        db.add(c)
        db.flush()
        return ClientOut.model_validate(c)

    @app.get("/clients", response_model=list[ClientOut])
    def list_clients(db: Session = Depends(get_db)):
        rows = db.execute(select(Client).order_by(Client.created_at.desc())).scalars().all()
        return [ClientOut.model_validate(r) for r in rows]

    # Topics (TopicLens)
    @app.post("/clients/{client_id}/topics", response_model=TopicOut)
    def create_topic(client_id: uuid.UUID, payload: TopicCreate, db: Session = Depends(get_db)):
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")
        qj = payload.query_json or {}
        t = TopicLens(
            client_id=client_id,
            name=payload.name,
            description=str(qj.get("description", "")),
            keywords=list(qj.get("keywords", []) or qj.get("phrases", [])),
        )
        db.add(t)
        db.flush()
        return TopicOut(
            id=t.id,
            client_id=t.client_id,
            name=t.name,
            query_json=t.query_json,
            created_at=t.created_at,
        )

    @app.get("/clients/{client_id}/topics", response_model=list[TopicOut])
    def list_topics(client_id: uuid.UUID, db: Session = Depends(get_db)):
        rows = (
            db.execute(select(TopicLens).where(TopicLens.client_id == client_id).order_by(TopicLens.created_at.desc()))
            .scalars()
            .all()
        )
        return [
            TopicOut(id=r.id, client_id=r.client_id, name=r.name, query_json=r.query_json, created_at=r.created_at)
            for r in rows
        ]

    # Subscriptions
    @app.post("/subscriptions", response_model=SubscriptionOut)
    def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
        s = Subscription(
            type=payload.type,
            name=payload.name,
            url=payload.url,
            client_id=payload.client_id,
            topic_id=payload.topic_id,
            enabled=payload.enabled,
            poll_interval_seconds=payload.poll_interval_seconds,
            fetch_full_content=payload.fetch_full_content,
            meta_json=payload.meta_json,
        )
        db.add(s)
        db.flush()
        return _sub_out(s)

    @app.get("/subscriptions", response_model=list[SubscriptionOut])
    def list_subscriptions(
        client_id: Optional[uuid.UUID] = None,
        type: Optional[SubscriptionType] = None,
        db: Session = Depends(get_db),
    ):
        q = select(Subscription).order_by(Subscription.created_at.desc())
        if client_id:
            q = q.where(Subscription.client_id == client_id)
        if type:
            q = q.where(Subscription.type == type)
        rows = db.execute(q).scalars().all()
        return [_sub_out(r) for r in rows]

    @app.post("/subscriptions/{subscription_id}/poll")
    def poll_subscription(subscription_id: uuid.UUID, db: Session = Depends(get_db)):
        sub = db.get(Subscription, subscription_id)
        if not sub:
            raise HTTPException(status_code=404, detail="subscription not found")

        if not try_acquire_subscription_lock(db, sub.id):
            raise HTTPException(status_code=409, detail="subscription locked by another worker")

        try:
            fetcher = HttpFetcher()
            robots = RobotsCache(fetcher)
            try:
                ingest_one_subscription(db, fetcher, robots, sub)
            finally:
                fetcher.close()
        finally:
            release_subscription_lock(db, sub.id)

        return {"status": "ok"}

    # Webhook ingestion
    @app.post("/ingest/webhook/{subscription_id}")
    def ingest_webhook(subscription_id: uuid.UUID, payload: WebhookEventIn, db: Session = Depends(get_db)):
        sub = db.get(Subscription, subscription_id)
        if not sub:
            raise HTTPException(status_code=404, detail="subscription not found")
        if sub.type != SubscriptionType.webhook:
            raise HTTPException(status_code=400, detail="subscription type is not webhook")

        cand = webhook_payload_to_candidate(payload.model_dump())
        created = store_event_and_link(db, sub, cand)
        return {"status": "ok", "event_created": bool(created)}

    # Events (IngestionEvent)
    @app.get("/events", response_model=list[IngestionEventOut])
    def list_events(
        limit: int = Query(default=50, ge=1, le=500),
        client_id: Optional[uuid.UUID] = None,
        subscription_id: Optional[uuid.UUID] = None,
        db: Session = Depends(get_db),
    ):
        q = select(IngestionEvent).order_by(IngestionEvent.fetched_at.desc()).limit(limit)

        if subscription_id:
            q = (
                select(IngestionEvent)
                .join(EventSubscription, EventSubscription.event_id == IngestionEvent.id)
                .where(EventSubscription.subscription_id == subscription_id)
                .order_by(IngestionEvent.fetched_at.desc())
                .limit(limit)
            )
        elif client_id:
            q = (
                select(IngestionEvent)
                .join(EventSubscription, EventSubscription.event_id == IngestionEvent.id)
                .join(Subscription, Subscription.id == EventSubscription.subscription_id)
                .where(Subscription.client_id == client_id)
                .order_by(IngestionEvent.fetched_at.desc())
                .limit(limit)
            )

        rows = db.execute(q).scalars().all()
        return [
            IngestionEventOut(
                id=r.id,
                canonical_url=r.canonical_url,
                title=r.title,
                summary=r.summary,
                published_at=r.published_at,
                fetched_at=r.fetched_at,
                source_type=r.source_type.value,
            )
            for r in rows
        ]

    @app.get("/events/{event_id}", response_model=IngestionEventOut)
    def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
        e = db.get(IngestionEvent, event_id)
        if not e:
            raise HTTPException(status_code=404, detail="event not found")
        return IngestionEventOut(
            id=e.id,
            canonical_url=e.canonical_url,
            title=e.title,
            summary=e.summary,
            published_at=e.published_at,
            fetched_at=e.fetched_at,
            source_type=e.source_type.value,
        )

    # ------------------------
    # Layer 2 Analytics APIs
    # ------------------------

    @app.get("/analytics/events/{event_id}/analysis", response_model=EventAnalysisOut)
    def get_event_analysis(event_id: uuid.UUID, db: Session = Depends(get_db)):
        row = db.execute(select(EventAnalysis).where(EventAnalysis.event_id == event_id)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="event analysis not found")

        frames = []
        for f in row.frames_json or []:
            if isinstance(f, dict) and "frame" in f:
                frames.append(
                    {
                        "frame": str(f.get("frame")),
                        "score": float(f.get("score") or 0.0),
                        "matches": int(f.get("matches") or 0),
                        "matched_terms": list(f.get("matched_terms") or []),
                    }
                )

        return EventAnalysisOut(
            event_id=row.event_id,
            analysis_version=row.analysis_version,
            analyzed_at=row.analyzed_at,
            text_hash=row.text_hash,
            sentiment_score=row.sentiment_score,
            sentiment_label=row.sentiment_label,
            frames=frames,
            status=row.status.value if hasattr(row.status, "value") else str(row.status),
            error_message=row.error_message,
            meta_json=row.meta_json or {},
        )

    @app.get("/analytics/events/{event_id}/topic-scores", response_model=list[EventTopicScoreOut])
    def get_event_topic_scores(
        event_id: uuid.UUID,
        include_reasons: bool = Query(default=False),
        db: Session = Depends(get_db),
    ):
        rows = (
            db.execute(
                select(EventTopicScore)
                .where(EventTopicScore.event_id == event_id)
                .order_by(EventTopicScore.relevance_score.desc())
            )
            .scalars()
            .all()
        )
        out: list[EventTopicScoreOut] = []
        for r in rows:
            out.append(
                EventTopicScoreOut(
                    event_id=r.event_id,
                    client_id=r.client_id,
                    topic_id=r.topic_id,
                    relevance_score=r.relevance_score,
                    keyword_score=r.keyword_score,
                    embedding_score=r.embedding_score,
                    computed_at=r.computed_at,
                    reasons_json=r.reasons_json if include_reasons else {},
                )
            )
        return out

    @app.get("/analytics/clients/{client_id}/feed", response_model=list[ClientEventFeedItem])
    def client_event_feed(
        client_id: uuid.UUID,
        min_score: float = Query(default=0.45, ge=0.0, le=1.0),
        limit: int = Query(default=50, ge=1, le=500),
        days: int = Query(default=7, ge=1, le=90),
        db: Session = Depends(get_db),
    ):
        since = datetime.utcnow() - timedelta(days=int(days))

        q = (
            select(IngestionEvent, EventTopicScore.topic_id, EventTopicScore.relevance_score, EventAnalysis.sentiment_score, EventAnalysis.frames_json)
            .join(EventTopicScore, EventTopicScore.event_id == IngestionEvent.id)
            .outerjoin(EventAnalysis, EventAnalysis.event_id == IngestionEvent.id)
            .where(EventTopicScore.client_id == client_id)
            .where(EventTopicScore.relevance_score >= float(min_score))
            .where(IngestionEvent.fetched_at >= since)
            .order_by(EventTopicScore.relevance_score.desc(), IngestionEvent.fetched_at.desc())
            .limit(limit)
        )
        rows = db.execute(q).all()

        items: list[ClientEventFeedItem] = []
        for ev, topic_id, score, sent_score, frames_json in rows:
            top_frame = None
            if isinstance(frames_json, list) and frames_json:
                f0 = frames_json[0]
                if isinstance(f0, dict):
                    top_frame = f0.get("frame")
            items.append(
                ClientEventFeedItem(
                    event=IngestionEventOut(
                        id=ev.id,
                        canonical_url=ev.canonical_url,
                        title=ev.title,
                        summary=ev.summary,
                        published_at=ev.published_at,
                        fetched_at=ev.fetched_at,
                        source_type=ev.source_type.value,
                    ),
                    topic_id=topic_id,
                    relevance_score=float(score),
                    sentiment_score=sent_score,
                    top_frame=str(top_frame) if top_frame else None,
                )
            )
        return items

    @app.get("/analytics/clients/{client_id}/daily-metrics", response_model=list[DailyTopicMetricOut])
    def client_daily_metrics(
        client_id: uuid.UUID,
        days: int = Query(default=14, ge=1, le=180),
        db: Session = Depends(get_db),
    ):
        since_day = (datetime.utcnow() - timedelta(days=int(days))).date()
        rows = (
            db.execute(
                select(DailyTopicMetric)
                .where(DailyTopicMetric.client_id == client_id)
                .where(DailyTopicMetric.day >= since_day)
                .order_by(DailyTopicMetric.day.desc(), DailyTopicMetric.topic_id.asc())
            )
            .scalars()
            .all()
        )
        return [
            DailyTopicMetricOut(
                client_id=r.client_id,
                topic_id=r.topic_id,
                day=r.day,
                event_count=r.event_count,
                avg_relevance=r.avg_relevance,
                avg_sentiment=r.avg_sentiment,
                top_frames_json=r.top_frames_json or [],
                computed_at=r.computed_at,
            )
            for r in rows
        ]

    return app


def _sub_out(s: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        client_id=s.client_id,
        topic_id=s.topic_id,
        type=s.type.value,
        name=s.name,
        url=s.url,
        enabled=s.enabled,
        poll_interval_seconds=s.poll_interval_seconds,
        fetch_full_content=s.fetch_full_content,
        last_polled_at=s.last_polled_at,
        last_success_at=s.last_success_at,
        last_error=s.last_error,
        consecutive_failures=s.consecutive_failures,
        created_at=s.created_at,
        meta_json=s.meta_json or {},
    )
