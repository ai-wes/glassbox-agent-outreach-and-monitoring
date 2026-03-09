"""Layer 1 webhook payload to EventCandidate."""

from __future__ import annotations

from datetime import datetime, timezone

from pr_monitor_app.ingestion.types import EventCandidate
from pr_monitor_app.models import EventSourceType
from pr_monitor_app.utils.urls import canonicalize_url


def webhook_payload_to_candidate(payload: dict) -> EventCandidate:
    """Convert webhook payload to EventCandidate.

    Expected payload keys: url (required), title, summary, content_text,
    published_at (ISO string), author, raw (extra JSON).
    """
    url = (payload.get("url") or "").strip()
    if not url:
        raise ValueError("webhook payload must include 'url'")

    canonical = canonicalize_url(url)
    title = (payload.get("title") or "").strip() or "(no title)"
    summary = (payload.get("summary") or "").strip() or None
    content_text = (payload.get("content_text") or "").strip() or None

    published_at = None
    if payload.get("published_at"):
        try:
            published_at = datetime.fromisoformat(
                payload["published_at"].replace("Z", "+00:00")
            )
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    if published_at is None:
        published_at = datetime.now(timezone.utc)

    raw = dict(payload)
    raw.pop("url", None)
    raw.pop("title", None)
    raw.pop("summary", None)
    raw.pop("content_text", None)
    raw.pop("published_at", None)

    return EventCandidate(
        canonical_url=canonical,
        title=title,
        summary=summary,
        content_text=content_text,
        published_at=published_at,
        fetched_at=datetime.now(timezone.utc),
        source_type=EventSourceType.webhook,
        raw_json=raw,
    )
