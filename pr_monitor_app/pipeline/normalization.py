from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.embedding import embed_texts
from pr_monitor_app.models import Event, RawEvent, SourceType
from pr_monitor_app.utils.text import (
    clean_source_text,
    is_noise_entity,
    normalize_text,
    strip_boilerplate_sections,
    strip_repeated_prefix,
    top_capitalized_phrases,
)

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except Exception:  # pragma: no cover - optional runtime dependency
    SentimentIntensityAnalyzer = None  # type: ignore[assignment]

log = structlog.get_logger(__name__)


class _NeutralSentimentAnalyzer:
    def polarity_scores(self, _text: str) -> dict[str, float]:
        return {"compound": 0.0}


_analyzer = SentimentIntensityAnalyzer() if SentimentIntensityAnalyzer is not None else _NeutralSentimentAnalyzer()


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

    for tag in re.findall(r"#([A-Za-z0-9_]{2,50})", text or ""):
        candidate = f"#{tag}"
        if not is_noise_entity(candidate):
            out.append(candidate)
    # @mentions (best-effort)
    for m in re.findall(r"@([A-Za-z0-9_]{2,50})", text or ""):
        candidate = f"@{m}"
        if not is_noise_entity(candidate):
            out.append(candidate)

    # dedupe
    seen = set()
    uniq: list[str] = []
    for e in out:
        e2 = normalize_text(e)
        if not e2:
            continue
        if is_noise_entity(e2):
            continue
        if e2.lower() in seen:
            continue
        seen.add(e2.lower())
        uniq.append(e2)
    return uniq


def _coerce_source_type(value: str) -> SourceType:
    try:
        return SourceType(value)
    except Exception:
        return SourceType.news


def _normalize_event_payload(payload: dict[str, Any], raw_event_id: str) -> dict[str, Any]:
    title = clean_source_text(payload.get("title") or "", max_chars=500)
    summary = clean_source_text(payload.get("summary") or "", max_chars=2_000)
    body = clean_source_text(
        payload.get("raw_text") or payload.get("content_text") or "",
        max_chars=settings.analytics_max_event_text_chars,
    )
    if title:
        body = strip_repeated_prefix(body, title)
    if summary:
        body = strip_repeated_prefix(body, summary)
    body = strip_boilerplate_sections(body)

    parts = [part for part in [title, summary, body] if part]
    text = normalize_text("\n\n".join(parts))
    if not text:
        text = title or summary or str(payload.get("external_id") or raw_event_id)

    author = clean_source_text(payload.get("author") or "", max_chars=250)
    url = clean_source_text(payload.get("url") or "") or str(payload.get("external_id") or raw_event_id)
    engagement_stats = payload.get("engagement_stats") if isinstance(payload.get("engagement_stats"), dict) else {}

    return {
        "source_type": _coerce_source_type(str(payload.get("source_type") or "")),
        "title": title or clean_source_text(str(payload.get("external_id") or raw_event_id), max_chars=500),
        "author": author[:250],
        "url": url,
        "published_at": _parse_dt(payload.get("published_at")),
        "raw_text": text,
        "entity_text": text[: min(len(text), 12_000)],
        "engagement_stats": engagement_stats,
    }


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

    normalized_rows = [_normalize_event_payload(r.payload or {}, str(r.id)) for r in raws]
    texts = [row["raw_text"] for row in normalized_rows]

    embeddings = embed_texts(texts).vectors

    created = 0
    for r, normalized, emb in zip(raws, normalized_rows, embeddings):
        sentiment = float(_analyzer.polarity_scores(normalized["raw_text"]).get("compound", 0.0))
        entities = _extract_entities(str(normalized["entity_text"]))

        ev = Event(
            raw_event_id=r.id,
            source_type=normalized["source_type"],
            title=str(normalized["title"]),
            author=str(normalized["author"]),
            url=str(normalized["url"]),
            published_at=normalized["published_at"],
            raw_text=str(normalized["raw_text"]),
            engagement_stats=normalized["engagement_stats"],
            detected_entities=entities,
            sentiment=sentiment,
            embedding=emb,
        )
        session.add(ev)
        created += 1

    log.info("normalize_raw_events_done", count=created)
    return {"normalized": created}


async def refresh_normalized_events(session: AsyncSession, *, limit: int = 500) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Event, RawEvent)
            .join(RawEvent, RawEvent.id == Event.raw_event_id)
            .order_by(Event.published_at.desc(), Event.created_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return {"scanned": 0, "refreshed": 0}

    normalized_rows = [_normalize_event_payload((raw.payload or {}), str(raw.id)) for event, raw in rows]
    embeddings = embed_texts([row["raw_text"] for row in normalized_rows]).vectors

    refreshed = 0
    for (event, _raw), normalized, emb in zip(rows, normalized_rows, embeddings):
        sentiment = float(_analyzer.polarity_scores(normalized["raw_text"]).get("compound", 0.0))
        entities = _extract_entities(str(normalized["entity_text"]))
        changed = False

        for field_name, value in {
            "source_type": normalized["source_type"],
            "title": str(normalized["title"]),
            "author": str(normalized["author"]),
            "url": str(normalized["url"]),
            "published_at": normalized["published_at"],
            "raw_text": str(normalized["raw_text"]),
            "engagement_stats": normalized["engagement_stats"],
            "detected_entities": entities,
            "sentiment": sentiment,
            "embedding": emb,
        }.items():
            if getattr(event, field_name) != value:
                setattr(event, field_name, value)
                changed = True

        if changed:
            refreshed += 1

    log.info("refresh_normalized_events_done", scanned=len(rows), refreshed=refreshed)
    return {"scanned": len(rows), "refreshed": refreshed}
