"""Layer 1 web page diff and link discovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from pr_monitor_app.config import settings
from pr_monitor_app.ingestion.types import EventCandidate
from pr_monitor_app.models import EventSourceType, Subscription
from pr_monitor_app.utils.hashing import sha256_hex
from pr_monitor_app.utils.http import HttpFetcher
from pr_monitor_app.utils.text import normalize_text
from pr_monitor_app.utils.urls import canonicalize_url


def _extract_main_text(html: str, url: str) -> tuple[str, str]:
    """Extract title and main text from HTML."""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = normalize_text(soup.title.string)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = normalize_text(soup.get_text(" "))
    if len(text) > settings.max_content_chars:
        text = text[: settings.max_content_chars]
    return title or url, text


def poll_web_page_diff(
    fetcher: HttpFetcher, sub: Subscription
) -> tuple[list[EventCandidate], dict[str, str], Optional[int]]:
    """Poll single page, emit event when content hash changes."""
    resp = fetcher.get(sub.url)
    http_status = resp.status_code
    resp.raise_for_status()

    title, text = _extract_main_text(resp.text, sub.url)
    content_hash = sha256_hex(text)

    meta = sub.meta_json or {}
    last_hash = meta.get("content_hash")

    if last_hash == content_hash:
        return [], {}, http_status

    meta["content_hash"] = content_hash
    state_updates: dict[str, str] = {"meta_json": str(meta)}  # runner applies meta_json differently
    # Runner expects etag/last_modified; we store hash in meta
    # For web_page_diff we update meta_json on the subscription in the runner
    state_updates = {}  # meta is updated in runner via sub.meta_json

    now = datetime.now(timezone.utc)
    canonical = canonicalize_url(sub.url)
    candidates = [
        EventCandidate(
            canonical_url=canonical,
            title=title or "(no title)",
            summary=text[: settings.max_summary_chars] if text else None,
            content_text=text if sub.fetch_full_content else None,
            content_hash=content_hash,
            published_at=now,
            fetched_at=now,
            source_type=EventSourceType.web,
            raw_json={"url": sub.url},
            dedup_salt=content_hash,
        )
    ]
    return candidates, {"meta_content_hash": content_hash}, http_status


def discover_links_from_index_page(
    fetcher: HttpFetcher, sub: Subscription
) -> tuple[list[EventCandidate], dict[str, str], Optional[int]]:
    """Discover article links from index page, emit one candidate per new link."""
    resp = fetcher.get(sub.url)
    http_status = resp.status_code
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    base_url = sub.url
    if not base_url.endswith("/"):
        base_url = base_url.rsplit("/", 1)[0] + "/"

    seen: set[str] = set()
    candidates: list[EventCandidate] = []

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue

        if href.startswith("/"):
            full_url = urljoin(sub.url, href)
        else:
            full_url = href

        if not full_url.startswith("http"):
            continue

        canonical = canonicalize_url(full_url)
        if canonical in seen:
            continue
        seen.add(canonical)

        title = normalize_text(a.get_text() or "")[:300]
        if not title:
            title = canonical

        now = datetime.now(timezone.utc)
        candidates.append(
            EventCandidate(
                canonical_url=canonical,
                title=title or "(no title)",
                summary=None,
                content_text=None,
                published_at=now,
                fetched_at=now,
                source_type=EventSourceType.web,
                raw_json={"source_url": sub.url, "link": full_url},
            )
        )

    return candidates, {}, http_status
