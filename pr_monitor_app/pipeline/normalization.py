from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.embedding import embed_texts
from pr_monitor_app.models import Event, RawEvent, SourceType
from pr_monitor_app.utils.text import normalize_text, top_capitalized_phrases
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

log = structlog.get_logger(__name__)

_analyzer = SentimentIntensityAnalyzer()


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        try:
            # Python 3.11 supports fromisoformat for many cases; fallback as needed
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _extract_entities(text: str) -> list[str]:
    out: list[str] = []
    out.extend(top_capitalized_phrases(text, max_phrases=12))
    # hashtags
    import re

    for tag in re.findall(r"#([A-Za-z0-9_]{2,50})", text or ""):
        out.append(f"#{tag}")
    # @mentions (best-effort)
    for m in re.findall(r"@([A-Za-z0-9_]{2,50})", text or ""):
        out.append(f"@{m}")

    # dedupe
    seen = set()
    uniq: list[str] = []
    for e in out:
        e2 = normalize_text(e)
        if not e2:
            continue
        if e2.lower() in seen:
            continue
        seen.add(e2.lower())
        uniq.append(e2)
    return uniq


async def normalize_new_raw_events(session: AsyncSession, *, limit: int = 250) -> dict[str, Any]:
    """
    Convert RawEvents that do not yet have a normalized Event.
    """
    # RawEvents without corresponding Event.raw_event_id
    subq = select(Event.raw_event_id).where(Event.raw_event_id.is_not(None)).subquery()
    raws = (
        await session.execute(
            select(RawEvent).where(~RawEvent.id.in_(select(subq.c.raw_event_id))).order_by(RawEvent.fetched_at.asc()).limit(limit)
        )
    ).scalars().all()

    if not raws:
        return {"normalized": 0}

    texts = []
    for r in raws:
        p = r.payload or {}
        title = normalize_text(p.get("title") or "")
        raw_text = normalize_text(p.get("raw_text") or "")
        texts.append(normalize_text("\n\n".join([title, raw_text])))

    embeddings = embed_texts(texts).vectors

    created = 0
    for r, text, emb in zip(raws, texts, embeddings):
        p = r.payload or {}
        st = p.get("source_type") or ""
        try:
            source_type = SourceType(st)
        except Exception:
            source_type = SourceType.news

        title = normalize_text(p.get("title") or "")
        # Event.author is VARCHAR(250); clamp oversized bylines from feeds/APIs.
        author = normalize_text(p.get("author") or "")[:250]
        url = normalize_text(p.get("url") or "") or (p.get("external_id") or str(r.id))
        published_at = _parse_dt(p.get("published_at"))

        sentiment = float(_analyzer.polarity_scores(text).get("compound", 0.0))
        entities = _extract_entities(text)

        ev = Event(
            raw_event_id=r.id,
            source_type=source_type,
            title=title,
            author=author,
            url=url,
            published_at=published_at,
            raw_text=text,
            engagement_stats=p.get("engagement_stats") or {},
            detected_entities=entities,
            sentiment=sentiment,
            embedding=emb,
        )
        session.add(ev)
        created += 1

    log.info("normalize_raw_events_done", count=created)
    return {"normalized": created}
