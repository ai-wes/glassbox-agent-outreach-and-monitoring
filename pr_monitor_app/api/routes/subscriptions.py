"""Layer 1 subscription ingestion API routes."""

from __future__ import annotations

import uuid
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from pr_monitor_app.api.deps import get_sync_session
from pr_monitor_app.ingestion.layer1_runner import (
    ingest_one_subscription,
    release_subscription_lock,
    store_event_and_link,
    try_acquire_subscription_lock,
)
from pr_monitor_app.ingestion.webhook import webhook_payload_to_candidate
from pr_monitor_app.models import EventSubscription, IngestionEvent, Subscription, SubscriptionType
from pr_monitor_app.schemas import IngestionEventOut, SubscriptionCreate, SubscriptionOut, WebhookEventIn
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.robots import RobotsCache

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


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


@router.post("", response_model=SubscriptionOut)
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_sync_session),
) -> SubscriptionOut:
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


@router.get("/events", response_model=list[IngestionEventOut])
def list_ingestion_events(
    limit: int = Query(default=50, ge=1, le=500),
    client_id: Optional[uuid.UUID] = None,
    subscription_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_sync_session),
) -> list[IngestionEventOut]:
    """List ingestion events (Layer 1), optionally filtered by client or subscription."""
    if subscription_id is not None:
        q = (
            select(IngestionEvent)
            .join(EventSubscription, EventSubscription.event_id == IngestionEvent.id)
            .where(EventSubscription.subscription_id == subscription_id)
            .order_by(IngestionEvent.fetched_at.desc())
            .limit(limit)
        )
    elif client_id is not None:
        q = (
            select(IngestionEvent)
            .join(EventSubscription, EventSubscription.event_id == IngestionEvent.id)
            .join(Subscription, Subscription.id == EventSubscription.subscription_id)
            .where(Subscription.client_id == client_id)
            .order_by(IngestionEvent.fetched_at.desc())
            .limit(limit)
        )
    else:
        q = (
            select(IngestionEvent)
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


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    client_id: Optional[uuid.UUID] = None,
    type: Optional[SubscriptionType] = None,
    db: Session = Depends(get_sync_session),
) -> list[SubscriptionOut]:
    q = select(Subscription).order_by(Subscription.created_at.desc())
    if client_id is not None:
        q = q.where(Subscription.client_id == client_id)
    if type is not None:
        q = q.where(Subscription.type == type)
    rows = db.execute(q).scalars().all()
    return [_sub_out(r) for r in rows]


@router.post("/{subscription_id}/poll")
def poll_subscription(
    subscription_id: uuid.UUID,
    db: Session = Depends(get_sync_session),
) -> dict[str, str]:
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


@router.post("/{subscription_id}/ingest/webhook")
def ingest_webhook(
    subscription_id: uuid.UUID,
    payload: WebhookEventIn,
    db: Session = Depends(get_sync_session),
) -> dict[str, object]:
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    if sub.type != SubscriptionType.webhook:
        raise HTTPException(status_code=400, detail="subscription type is not webhook")

    cand = webhook_payload_to_candidate(payload.model_dump())
    created = store_event_and_link(db, sub, cand)
    return {"status": "ok", "event_created": bool(created)}
