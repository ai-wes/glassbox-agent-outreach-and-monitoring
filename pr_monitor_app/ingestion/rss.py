from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import feedparser
import httpx
from dateutil import parser as dateparser
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class RSSConnector(Connector):
    def __init__(
        self,
        rss_url: str,
        source_type: SourceType,
        *,
        default_author: str = "",
        user_agent: str = "NPE/1.0 (+https://example.com)",
        timeout_seconds: int = 20,
        max_items: int = 50,
    ) -> None:
        self.rss_url = rss_url
        self.source_type = source_type
        self.default_author = default_author
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_items = max_items

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _download(self) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}) as client:
            resp = await client.get(self.rss_url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content

    def _parse_dt(self, entry: Any) -> datetime:
        # Try published_parsed, updated_parsed, then parse date strings.
        for key in ("published", "updated"):
            if key in entry and entry.get(key):
                try:
                    dt = dateparser.parse(entry.get(key))
                    if dt.tzinfo is None:
                        return dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(timezone.utc)
                except Exception:
                    pass
        # fall back to now
        return datetime.now(timezone.utc)

    def _extract_text(self, entry: Any) -> str:
        parts: list[str] = []
        for k in ("title", "summary", "description"):
            v = entry.get(k)
            if v:
                parts.append(str(v))
        # content may be list
        content = entry.get("content")
        if isinstance(content, list):
            for c in content:
                v = c.get("value")
                if v:
                    parts.append(str(v))
        return normalize_text("\n\n".join(parts))

    async def fetch(self) -> list[IngestedItem]:
        raw = await self._download()
        parsed = feedparser.parse(raw)
        items: list[IngestedItem] = []
        for entry in (parsed.entries or [])[: self.max_items]:
            url = (entry.get("link") or "").strip()
            if not url:
                continue
            ext_id = (entry.get("id") or url).strip()
            title = normalize_text(entry.get("title") or "")
            author = normalize_text(entry.get("author") or self.default_author)
            published_at = self._parse_dt(entry)
            raw_text = self._extract_text(entry)
            items.append(
                IngestedItem(
                    external_id=ext_id,
                    source_type=self.source_type,
                    title=title,
                    url=url,
                    author=author,
                    published_at=published_at,
                    raw_text=raw_text,
                    engagement_stats={},  # RSS rarely includes; extend if available
                )
            )
        return items
