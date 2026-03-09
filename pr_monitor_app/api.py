from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from pr_monitor_app.config import settings
from pr_monitor_app.db import ENGINE, SessionLocal
from pr_monitor_app.ingestion.runner import ingest_one_subscription, try_acquire_subscription_lock, release_subscription_lock
from pr_monitor_app.ingestion.webhook import webhook_payload_to_candidate
from pr_monitor_app.logging import configure_logging, get_logger
from pr_monitor_app.models import Client, Event, EventSubscription, Subscription, SubscriptionType, Topic
from pr_monitor_app.models_analytics import DailyTopicMetric, EventAnalysis, EventTopicScore
from pr_monitor_app.models_agent import AgentJob, AgentJobStatus, AgentOutput, ClientProfile, ClientSignalRoute, SignalRecipientType

from pr_monitor_app.schemas import (
    ClientCreate,
    ClientOut,
    EventOut,
    SubscriptionCreate,
    SubscriptionOut,
    TopicCreate,
    TopicOut,
    WebhookEventIn,
    EventAnalysisOut,
    EventTopicScoreOut,
    ClientEventFeedItem,
    DailyTopicMetricOut,
)
from pr_monitor_app.api_schemas import (
    AgentJobOut,
    AgentOutputOut,
    ClientProfileOut,
    ClientProfileUpsert,
    SignalRouteCreate,
    SignalRouteOut,
)
from pr_monitor_app.scheduler import start_scheduler
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.robots import RobotsCache

from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship




log = get_logger(component="api")


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
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

    app = FastAPI(title="PR Pulse", version="0.3.0")

    @app.on_event("startup")
    def _startup() -> None:
        if settings.db_auto_create:
            Base.metadata.create_all(bind=ENGINE)
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
        c = Client(name=payload.name)
        db.add(c)
        db.flush()
        return ClientOut(id=c.id, name=c.name, created_at=c.created_at)

    @app.get("/clients", response_model=list[ClientOut])
    def list_clients(db: Session = Depends(get_db)):
        rows = db.execute(select(Client).order_by(Client.created_at.desc())).scalars().all()
        return [ClientOut(id=r.id, name=r.name, created_at=r.created_at) for r in rows]

    # Topics
    @app.post("/clients/{client_id}/topics", response_model=TopicOut)
    def create_topic(client_id: uuid.UUID, payload: TopicCreate, db: Session = Depends(get_db)):
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")
        t = Topic(client_id=client_id, name=payload.name, query_json=payload.query_json)
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
            db.execute(select(Topic).where(Topic.client_id == client_id).order_by(Topic.created_at.desc()))
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
        if payload.type == SubscriptionType.webhook and payload.poll_interval_seconds != 300:
            # webhooks are push-based; interval ignored; we still store for uniformity
            pass
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

        cand = webhook_payload_to_candidate(payload)

        # store event and link
        from pr_monitor_app.ingestion.runner import store_event_and_link

        created = store_event_and_link(db, sub, cand)
        return {"status": "ok", "event_created": bool(created)}

    # Events
    @app.get("/events", response_model=list[EventOut])
    def list_events(
        limit: int = Query(default=50, ge=1, le=500),
        client_id: Optional[uuid.UUID] = None,
        subscription_id: Optional[uuid.UUID] = None,
        db: Session = Depends(get_db),
    ):
        q = select(Event).order_by(Event.fetched_at.desc()).limit(limit)

        if subscription_id:
            q = (
                select(Event)
                .join(EventSubscription, EventSubscription.event_id == Event.id)
                .where(EventSubscription.subscription_id == subscription_id)
                .order_by(Event.fetched_at.desc())
                .limit(limit)
            )
        elif client_id:
            q = (
                select(Event)
                .join(EventSubscription, EventSubscription.event_id == Event.id)
                .join(Subscription, Subscription.id == EventSubscription.subscription_id)
                .where(Subscription.client_id == client_id)
                .order_by(Event.fetched_at.desc())
                .limit(limit)
            )

        rows = db.execute(q).scalars().all()
        return [
            EventOut(
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

    @app.get("/events/{event_id}", response_model=EventOut)
    def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
        e = db.get(Event, event_id)
        if not e:
            raise HTTPException(status_code=404, detail="event not found")
        return EventOut(
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

        # Top events per client based on topic relevance score
        q = (
            select(Event, EventTopicScore.topic_id, EventTopicScore.relevance_score, EventAnalysis.sentiment_score, EventAnalysis.frames_json)
            .join(EventTopicScore, EventTopicScore.event_id == Event.id)
            .outerjoin(EventAnalysis, EventAnalysis.event_id == Event.id)
            .where(EventTopicScore.client_id == client_id)
            .where(EventTopicScore.relevance_score >= float(min_score))
            .where(Event.fetched_at >= since)
            .order_by(EventTopicScore.relevance_score.desc(), Event.fetched_at.desc())
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
                    event=EventOut(
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

    # =========================
    # Layer 3: Agent + profiles
    # =========================

    @app.get("/clients/{client_id}/profile", response_model=ClientProfileOut)
    def get_profile(client_id: uuid.UUID, db: Session = Depends(get_db)):
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")

        prof = db.get(ClientProfile, client_id)
        if prof is None:
            prof = ClientProfile(client_id=client_id)
            db.add(prof)
            db.flush()

        return ClientProfileOut(
            client_id=prof.client_id,
            voice_instructions=prof.voice_instructions,
            do_not_say=list(prof.do_not_say_json or []),
            default_hashtags=list(prof.default_hashtags_json or []),
            compliance_notes=prof.compliance_notes,
            meta=dict(prof.meta_json or {}),
            created_at=prof.created_at,
            updated_at=prof.updated_at,
        )

    @app.put("/clients/{client_id}/profile", response_model=ClientProfileOut)
    def upsert_profile(client_id: uuid.UUID, payload: ClientProfileUpsert, db: Session = Depends(get_db)):
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")

        prof = db.get(ClientProfile, client_id)
        if prof is None:
            prof = ClientProfile(client_id=client_id)
            db.add(prof)

        prof.voice_instructions = payload.voice_instructions
        prof.do_not_say_json = list(payload.do_not_say or [])
        prof.default_hashtags_json = list(payload.default_hashtags or [])
        prof.compliance_notes = payload.compliance_notes
        prof.meta_json = dict(payload.meta or {})
        prof.updated_at = datetime.utcnow()
        db.flush()

        return ClientProfileOut(
            client_id=prof.client_id,
            voice_instructions=prof.voice_instructions,
            do_not_say=list(prof.do_not_say_json or []),
            default_hashtags=list(prof.default_hashtags_json or []),
            compliance_notes=prof.compliance_notes,
            meta=dict(prof.meta_json or {}),
            created_at=prof.created_at,
            updated_at=prof.updated_at,
        )

    @app.post("/clients/{client_id}/signal-routes", response_model=SignalRouteOut)
    def create_signal_route(client_id: uuid.UUID, payload: SignalRouteCreate, db: Session = Depends(get_db)):
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")

        rt = (payload.recipient_type or "").strip().lower()
        if rt not in ("user", "group"):
            raise HTTPException(status_code=400, detail="recipient_type must be 'user' or 'group'")

        route = ClientSignalRoute(
            client_id=client_id,
            enabled=bool(payload.enabled),
            recipient_type=SignalRecipientType.user if rt == "user" else SignalRecipientType.group,
            recipient_id=payload.recipient_id,
            from_number=payload.from_number,
        )
        db.add(route)
        db.flush()

        return SignalRouteOut(
            id=route.id,
            client_id=route.client_id,
            enabled=route.enabled,
            recipient_type=route.recipient_type.value,
            recipient_id=route.recipient_id,
            from_number=route.from_number,
            created_at=route.created_at,
        )

    @app.get("/clients/{client_id}/signal-routes", response_model=list[SignalRouteOut])
    def list_signal_routes(client_id: uuid.UUID, db: Session = Depends(get_db)):
        rows = (
            db.execute(
                select(ClientSignalRoute)
                .where(ClientSignalRoute.client_id == client_id)
                .order_by(ClientSignalRoute.created_at.asc())
            )
            .scalars()
            .all()
        )
        return [
            SignalRouteOut(
                id=r.id,
                client_id=r.client_id,
                enabled=r.enabled,
                recipient_type=r.recipient_type.value,
                recipient_id=r.recipient_id,
                from_number=r.from_number,
                created_at=r.created_at,
            )
            for r in rows
        ]

    @app.get("/agent/jobs", response_model=list[AgentJobOut])
    def list_agent_jobs(
        client_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        db: Session = Depends(get_db),
    ):
        q = select(AgentJob).order_by(AgentJob.created_at.desc())
        if client_id:
            q = q.where(AgentJob.client_id == client_id)
        if status:
            st = status.strip().lower()
            try:
                q = q.where(AgentJob.status == AgentJobStatus(st))
            except Exception:
                raise HTTPException(status_code=400, detail="invalid status")
        rows = db.execute(q.limit(int(limit))).scalars().all()
        return [
            AgentJobOut(
                id=r.id,
                event_id=r.event_id,
                client_id=r.client_id,
                topic_ids=list(r.topic_ids_json or []),
                top_relevance_score=float(r.top_relevance_score or 0.0),
                priority=r.priority,
                status=r.status.value,
                agent_version=r.agent_version,
                created_at=r.created_at,
                started_at=r.started_at,
                finished_at=r.finished_at,
                output_id=r.output_id,
                error_message=r.error_message,
            )
            for r in rows
        ]

    @app.get("/agent/jobs/{job_id}", response_model=AgentJobOut)
    def get_agent_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
        r = db.get(AgentJob, job_id)
        if not r:
            raise HTTPException(status_code=404, detail="job not found")
        return AgentJobOut(
            id=r.id,
            event_id=r.event_id,
            client_id=r.client_id,
            topic_ids=list(r.topic_ids_json or []),
            top_relevance_score=float(r.top_relevance_score or 0.0),
            priority=r.priority,
            status=r.status.value,
            agent_version=r.agent_version,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
            output_id=r.output_id,
            error_message=r.error_message,
        )

    @app.get("/agent/outputs/{output_id}", response_model=AgentOutputOut)
    def get_agent_output(output_id: uuid.UUID, db: Session = Depends(get_db)):
        r = db.get(AgentOutput, output_id)
        if not r:
            raise HTTPException(status_code=404, detail="output not found")
        return AgentOutputOut(
            id=r.id,
            event_id=r.event_id,
            client_id=r.client_id,
            agent_version=r.agent_version,
            model=r.model,
            generated_at=r.generated_at,
            output=dict(r.output_json or {}),
            summary_text=r.summary_text,
            prompt_tokens=r.prompt_tokens,
            output_tokens=r.output_tokens,
            meta=dict(r.meta_json or {}),
        )

    @app.get("/agent/outputs", response_model=list[AgentOutputOut])
    def list_agent_outputs(
        client_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        db: Session = Depends(get_db),
    ):
        q = select(AgentOutput).order_by(AgentOutput.generated_at.desc())
        if client_id:
            q = q.where(AgentOutput.client_id == client_id)
        if event_id:
            q = q.where(AgentOutput.event_id == event_id)
        rows = db.execute(q.limit(int(limit))).scalars().all()
        return [
            AgentOutputOut(
                id=r.id,
                event_id=r.event_id,
                client_id=r.client_id,
                agent_version=r.agent_version,
                model=r.model,
                generated_at=r.generated_at,
                output=dict(r.output_json or {}),
                summary_text=r.summary_text,
                prompt_tokens=r.prompt_tokens,
                output_tokens=r.output_tokens,
                meta=dict(r.meta_json or {}),
            )
            for r in rows
        ]



    return app


def _sub_out(s: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        client_id=s.client_id,
        topic_id=s.topic_id,
        type=s.type,
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
