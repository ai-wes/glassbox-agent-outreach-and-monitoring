"""Sync IngestionEvents (Layer 1) to RawEvents for pipeline processing."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.models import IngestionEvent, RawEvent, Source, SourceType

log = structlog.get_logger(__name__)

SUBSCRIPTION_SOURCE_NAME = "__subscription_ingestion__"


async def get_or_create_subscription_source(session: AsyncSession) -> Any:
    """Get or create the system source for subscription ingestion."""
    row = (
        await session.execute(
            select(Source).where(Source.name == SUBSCRIPTION_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    if row:
        return row

    src = Source(
        source_type=SourceType.blog,
        name=SUBSCRIPTION_SOURCE_NAME,
        url="",
        config={"subscription_ingestion": True},
        active=True,
    )
    session.add(src)
    await session.flush()
    return src


async def sync_subscription_events_to_raw(session: AsyncSession, limit: int = 200) -> dict[str, Any]:
    """
    Copy new IngestionEvents to RawEvent so they flow through normalization.
    Uses dedup_key as external_id to avoid duplicates.
    """
    source = await get_or_create_subscription_source(session)
    source_id = source.id

    # Find IngestionEvents that don't yet have a RawEvent (by external_id = dedup_key)
    existing = (
        await session.execute(
            select(RawEvent.external_id).where(RawEvent.source_id == source_id)
        )
    ).scalars().all()
    existing_keys = {r[0] for r in existing}

    # Fetch IngestionEvents not yet synced
    all_ingestion = (
        await session.execute(
            select(IngestionEvent).order_by(IngestionEvent.fetched_at.asc()).limit(limit * 2)
        )
    ).scalars().all()

    to_sync = [ie for ie in all_ingestion if ie.dedup_key not in existing_keys][:limit]
    if not to_sync:
        return {"synced": 0}

    created = 0
    for ie in to_sync:
        payload = {
            "external_id": ie.dedup_key,
            "source_type": "news" if ie.source_type.value == "rss" else "blog",
            "title": ie.title,
            "url": ie.canonical_url,
            "author": "",
            "published_at": ie.published_at.isoformat() if ie.published_at else None,
            "raw_text": (ie.summary or ie.content_text or ""),
            "engagement_stats": {},
            "fetched_at": ie.fetched_at.isoformat(),
        }
        stmt = (
            insert(RawEvent)
            .values(
                source_id=source_id,
                external_id=ie.dedup_key,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
            .returning(RawEvent.id)
        )
        result = (await session.execute(stmt)).scalar_one_or_none()
        if result is not None:
            created += 1

    if created > 0:
        log.info("sync_subscription_events", synced=created)
    return {"synced": created}
