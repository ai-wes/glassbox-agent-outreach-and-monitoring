"""Layer 1 ingestion runner: polling, dedup, advisory locks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pr_monitor_app.config import settings
from pr_monitor_app.ingestion.layer1_rss import poll_rss
from pr_monitor_app.ingestion.layer1_web import discover_links_from_index_page, poll_web_page_diff
from pr_monitor_app.ingestion.types import EventCandidate
from pr_monitor_app.ingestion.webhook import webhook_payload_to_candidate
from pr_monitor_app.models import (
    DiscoveredLink,
    IngestionAttempt,
    IngestionEvent,
    IngestionStatus,
    Subscription,
    SubscriptionType,
)
from pr_monitor_app.models import EventSubscription
from pr_monitor_app.utils.hashing import sha256_hex
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.robots import RobotsCache

log = structlog.get_logger(__name__)


def subscription_due(sub: Subscription, now: datetime) -> bool:
    if not sub.enabled:
        return False
    if sub.type == SubscriptionType.webhook:
        return False
    if sub.last_polled_at is None:
        return True
    return sub.last_polled_at + timedelta(seconds=sub.poll_interval_seconds) <= now


def advisory_lock_id(sub_id: uuid.UUID) -> int:
    v = int.from_bytes(sub_id.bytes[:8], "big", signed=False)
    return v & 0x7FFFFFFFFFFFFFFF


def try_acquire_subscription_lock(session: Session, sub_id: uuid.UUID) -> bool:
    lock_id = advisory_lock_id(sub_id)
    res = session.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}).scalar()
    return bool(res)


def release_subscription_lock(session: Session, sub_id: uuid.UUID) -> None:
    lock_id = advisory_lock_id(sub_id)
    session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})


def ingest_due_subscriptions(session: Session) -> int:
    now = datetime.utcnow()

    subs = (
        session.execute(
            select(Subscription)
            .where(Subscription.enabled.is_(True))
            .order_by(Subscription.last_polled_at.asc().nullsfirst())
            .limit(settings.ingest_max_subscriptions_per_tick)
        )
        .scalars()
        .all()
    )

    processed = 0
    fetcher = HttpFetcher()
    robots = RobotsCache(fetcher)

    try:
        for sub in subs:
            if not subscription_due(sub, now):
                continue
            if not try_acquire_subscription_lock(session, sub.id):
                continue

            try:
                processed += 1
                ingest_one_subscription(session, fetcher, robots, sub)
            finally:
                release_subscription_lock(session, sub.id)

        return processed
    finally:
        fetcher.close()


def ingest_one_subscription(
    session: Session, fetcher: HttpFetcher, robots: RobotsCache, sub: Subscription
) -> None:
    start = datetime.utcnow()
    sub.last_polled_at = start

    attempt = IngestionAttempt(
        subscription_id=sub.id,
        started_at=start,
        status=IngestionStatus.success,
        subscription_type=sub.type.value,
        subscription_url=sub.url,
    )
    session.add(attempt)
    session.flush()

    try:
        if not robots.allowed(sub.url):
            attempt.status = IngestionStatus.no_change
            attempt.http_status = 403
            attempt.error_message = "blocked_by_robots"
            sub.last_error = "blocked_by_robots"
            sub.consecutive_failures += 1
            attempt.finished_at = datetime.utcnow()
            session.flush()
            return

        candidates: list[EventCandidate] = []
        state_updates: dict[str, str] = {}
        http_status: Optional[int] = None

        if sub.type == SubscriptionType.rss:
            candidates, state_updates, http_status = poll_rss(fetcher, sub)
        elif sub.type == SubscriptionType.web_page_diff:
            candidates, state_updates, http_status = poll_web_page_diff(fetcher, sub)
            if "meta_content_hash" in state_updates:
                meta = dict(sub.meta_json or {})
                meta["content_hash"] = state_updates["meta_content_hash"]
                sub.meta_json = meta
                state_updates.pop("meta_content_hash", None)
        elif sub.type == SubscriptionType.web_link_discovery:
            candidates, state_updates, http_status = discover_links_from_index_page(fetcher, sub)
        else:
            candidates, state_updates, http_status = [], {}, 204

        attempt.http_status = http_status

        if "etag" in state_updates:
            sub.etag = state_updates["etag"]
        if "last_modified" in state_updates:
            sub.last_modified = state_updates["last_modified"]

        if sub.type == SubscriptionType.web_link_discovery and candidates:
            candidates = _filter_new_discovered_links(session, sub, candidates)

        created = 0
        for cand in candidates:
            created += store_event_and_link(session, sub, cand)

        attempt.events_created = created

        if created == 0:
            attempt.status = IngestionStatus.no_change
        else:
            attempt.status = IngestionStatus.success

        sub.last_success_at = datetime.utcnow()
        sub.last_error = None
        sub.consecutive_failures = 0

        attempt.finished_at = datetime.utcnow()
        session.flush()

        log.info(
            "ingested",
            subscription_id=str(sub.id),
            type=sub.type.value,
            url=sub.url,
            events_created=created,
            http_status=http_status,
        )

    except Exception as e:
        sub.last_error = str(e)
        sub.consecutive_failures += 1

        attempt.status = IngestionStatus.error
        attempt.error_message = str(e)
        attempt.finished_at = datetime.utcnow()

        session.flush()

        log.warning(
            "ingest_failed",
            subscription_id=str(sub.id),
            type=sub.type.value,
            url=sub.url,
            error=str(e),
        )


def store_event_and_link(session: Session, sub: Subscription, cand: EventCandidate) -> int:
    """Upsert IngestionEvent by dedup_key, link to subscription. Returns 1 if new, else 0."""
    dedup_material = cand.canonical_url
    if cand.dedup_salt:
        dedup_material = f"{dedup_material}|{cand.dedup_salt}"
    dedup_key = sha256_hex(dedup_material)

    insert_stmt = (
        insert(IngestionEvent)
        .values(
            canonical_url=cand.canonical_url,
            dedup_key=dedup_key,
            title=cand.title,
            summary=cand.summary,
            content_text=cand.content_text,
            content_hash=cand.content_hash,
            published_at=cand.published_at,
            fetched_at=cand.fetched_at or datetime.utcnow(),
            source_type=cand.source_type,
            raw_json=cand.raw_json or {},
        )
        .on_conflict_do_update(
            index_elements=[IngestionEvent.dedup_key],
            set_={
                "published_at": text("COALESCE(ingestion_events.published_at, EXCLUDED.published_at)"),
                "fetched_at": text("EXCLUDED.fetched_at"),
                "raw_json": text("EXCLUDED.raw_json"),
                "summary": text("COALESCE(EXCLUDED.summary, ingestion_events.summary)"),
                "content_text": text("COALESCE(EXCLUDED.content_text, ingestion_events.content_text)"),
                "content_hash": text("COALESCE(EXCLUDED.content_hash, ingestion_events.content_hash)"),
                "title": text("COALESCE(EXCLUDED.title, ingestion_events.title)"),
            },
        )
        .returning(IngestionEvent.id, text("xmax = 0"))
    )

    row = session.execute(insert_stmt).first()
    assert row is not None
    event_id = row[0]
    inserted = bool(row[1])

    link_stmt = (
        insert(EventSubscription)
        .values(event_id=event_id, subscription_id=sub.id)
        .on_conflict_do_nothing(index_elements=[EventSubscription.event_id, EventSubscription.subscription_id])
    )
    session.execute(link_stmt)

    return 1 if inserted else 0


def _filter_new_discovered_links(
    session: Session, sub: Subscription, candidates: list[EventCandidate]
) -> list[EventCandidate]:
    new_candidates: list[EventCandidate] = []

    for cand in candidates:
        url_hash = sha256_hex(cand.canonical_url)
        stmt = (
            insert(DiscoveredLink)
            .values(subscription_id=sub.id, canonical_url=cand.canonical_url, url_hash=url_hash)
            .on_conflict_do_nothing(index_elements=[DiscoveredLink.subscription_id, DiscoveredLink.url_hash])
            .returning(DiscoveredLink.id)
        )
        inserted = session.execute(stmt).scalar_one_or_none()
        if inserted is not None:
            new_candidates.append(cand)

    return new_candidates
