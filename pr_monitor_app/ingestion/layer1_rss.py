"""Layer 1 RSS/Atom polling with conditional fetch (etag, last-modified)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import feedparser
from dateutil import parser as dateparser

from pr_monitor_app.config import settings
from pr_monitor_app.ingestion.types import EventCandidate
from pr_monitor_app.models import EventSourceType, Subscription
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.text import normalize_text
from pr_monitor_app.utils.urls import canonicalize_url


def _parse_dt(entry: dict[str, Any]) -> datetime:
    for key in ("published", "updated"):
        if key in entry and entry.get(key):
            try:
                dt = dateparser.parse(str(entry.get(key)))
                if dt and dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                if dt:
                    return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def _extract_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in ("title", "summary", "description"):
        v = entry.get(k)
        if v:
            parts.append(str(v))
    content = entry.get("content")
    if isinstance(content, list):
        for c in content:
            v = c.get("value") if isinstance(c, dict) else None
            if v:
                parts.append(str(v))
    return normalize_text("\n\n".join(parts))[: settings.max_summary_chars]


def poll_rss(
    fetcher: HttpFetcher, sub: Subscription
) -> tuple[list[EventCandidate], dict[str, str], Optional[int]]:
    """Poll RSS/Atom feed, return (candidates, state_updates, http_status)."""
    headers: dict[str, str] = {}
    if sub.etag:
        headers["If-None-Match"] = sub.etag
    if sub.last_modified:
        headers["If-Modified-Since"] = sub.last_modified

    client = fetcher._get_client()
    resp = client.get(sub.url, headers=headers if headers else None)
    http_status = resp.status_code

    state_updates: dict[str, str] = {}
    if "etag" in resp.headers:
        state_updates["etag"] = resp.headers["etag"]
    if "last-modified" in resp.headers:
        state_updates["last_modified"] = resp.headers["last-modified"]

    if resp.status_code == 304:
        return [], state_updates, http_status

    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    candidates: list[EventCandidate] = []
    for entry in (parsed.entries or [])[:50]:
        url = (entry.get("link") or "").strip()
        if not url:
            continue

        canonical = canonicalize_url(url)
        ext_id = (entry.get("id") or url).strip()
        title = normalize_text(entry.get("title") or "")[:500]
        published_at = _parse_dt(entry)
        raw_text = _extract_text(entry)

        if len(raw_text) < settings.ingest_min_text_length and not title:
            continue

        candidates.append(
            EventCandidate(
                canonical_url=canonical,
                title=title or "(no title)",
                summary=raw_text[: settings.max_summary_chars] if raw_text else None,
                content_text=raw_text[: settings.max_content_chars] if sub.fetch_full_content else None,
                published_at=published_at,
                fetched_at=datetime.now(timezone.utc),
                source_type=EventSourceType.rss,
                raw_json={
                    "id": ext_id,
                    "link": url,
                    "author": entry.get("author", ""),
                },
            )
        )

    return candidates, state_updates, http_status
