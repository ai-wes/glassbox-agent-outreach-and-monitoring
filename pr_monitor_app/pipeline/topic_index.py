from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.embedding import embed_texts
from pr_monitor_app.models import TopicLens
from pr_monitor_app.utils.text import normalize_text

log = structlog.get_logger(__name__)


def _topic_text(t: TopicLens) -> str:
    parts = [t.name, t.description]
    if t.keywords:
        parts.append("Keywords: " + ", ".join(t.keywords))
    if t.opportunity_tags:
        parts.append("Opportunities: " + ", ".join(t.opportunity_tags))
    if t.risk_flags:
        parts.append("Risks: " + ", ".join(t.risk_flags))
    return normalize_text("\n".join([p for p in parts if p]))


async def ensure_topic_embeddings(session: AsyncSession, *, limit: int = 200) -> dict[str, Any]:
    topics = (await session.execute(select(TopicLens).where(TopicLens.embedding.is_(None)).limit(limit))).scalars().all()
    if not topics:
        return {"embedded": 0}

    texts = [_topic_text(t) for t in topics]
    embs = embed_texts(texts).vectors

    for t, emb in zip(topics, embs):
        t.embedding = emb

    log.info("topic_embeddings_updated", count=len(topics))
    return {"embedded": len(topics)}
