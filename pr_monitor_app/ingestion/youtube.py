"""YouTube Data API v3 connector for video search and channel videos."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class YouTubeConnector(Connector):
    """
    YouTube Data API v3 connector.

    Supports:
    - Search by query: search.list with q=
    - Channel videos: search.list with channelId=

    Config: api_key (required), query OR channel_id (required), max_results (default 50), order (date|relevance)
    """

    BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(
        self,
        *,
        api_key: str,
        query: str | None = None,
        channel_id: str | None = None,
        max_results: int = 50,
        order: str = "date",
        timeout_seconds: int = 20,
        user_agent: str = "NPE/1.0 (+https://example.com)",
    ) -> None:
        self.api_key = api_key
        self.query = (query or "").strip()
        self.channel_id = (channel_id or "").strip()
        self.max_results = min(50, max(1, max_results))
        self.order = order if order in ("date", "relevance", "viewCount", "rating") else "date"
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

        if not self.query and not self.channel_id:
            raise ValueError("YouTube connector requires query or channel_id")

    def _parse_dt(self, s: str | None) -> datetime:
        if not s:
            return datetime.now(timezone.utc)
        try:
            from dateutil import parser as dateparser

            dt = dateparser.parse(s)
            if dt and dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc) if dt else datetime.now(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        params["key"] = self.api_key
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def fetch(self) -> list[IngestedItem]:
        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "maxResults": self.max_results,
            "order": self.order,
        }
        if self.query:
            params["q"] = self.query
        if self.channel_id:
            params["channelId"] = self.channel_id

        data = await self._get_json(f"{self.BASE}/search", params)
        items_raw = data.get("items") or []
        items: list[IngestedItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            vid = it.get("id", {})
            video_id = vid.get("videoId") if isinstance(vid, dict) else None
            if not video_id:
                continue
            snip = it.get("snippet") or {}
            if not isinstance(snip, dict):
                continue
            title = normalize_text(snip.get("title") or "")
            desc = normalize_text(snip.get("description") or "")
            raw_text = f"{title}\n\n{desc}".strip() or title
            channel = normalize_text(snip.get("channelTitle") or "")
            published = self._parse_dt(snip.get("publishedAt"))
            url = f"https://www.youtube.com/watch?v={video_id}"
            engagement_stats = {
                "channel_id": snip.get("channelId", ""),
                "channel_title": channel,
            }
            items.append(
                IngestedItem(
                    external_id=video_id,
                    source_type=SourceType.youtube,
                    title=title[:200] or "(no title)",
                    url=url,
                    author=channel,
                    published_at=published,
                    raw_text=raw_text[:50000],
                    engagement_stats=engagement_stats,
                )
            )
        return items
