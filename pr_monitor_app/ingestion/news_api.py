"""News API (newsapi.org) connector for article search."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class NewsAPIConnector(Connector):
    """
    News API (newsapi.org) connector.

    Uses /v2/everything endpoint for keyword search.
    Config: api_key (required), query (required), from_days (default 7), page_size (default 50), sort_by
    """

    BASE = "https://newsapi.org/v2"

    def __init__(
        self,
        *,
        api_key: str,
        query: str,
        from_days: int = 7,
        page_size: int = 50,
        sort_by: str = "publishedAt",
        language: str | None = None,
        timeout_seconds: int = 20,
        user_agent: str = "NPE/1.0 (+https://example.com)",
    ) -> None:
        self.api_key = api_key
        self.query = (query or "").strip()
        self.from_days = max(1, min(30, from_days))
        self.page_size = min(100, max(1, page_size))
        self.sort_by = sort_by if sort_by in ("relevancy", "popularity", "publishedAt") else "publishedAt"
        self.language = (language or "en").strip() or None
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

        if not self.query:
            raise ValueError("News API connector requires query")

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
        params["apiKey"] = self.api_key
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def fetch(self) -> list[IngestedItem]:
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=self.from_days)
        params: dict[str, Any] = {
            "q": self.query,
            "from": from_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": to_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pageSize": self.page_size,
            "sortBy": self.sort_by,
        }
        if self.language:
            params["language"] = self.language

        data = await self._get_json(f"{self.BASE}/everything", params)
        if data.get("status") != "ok":
            return []
        articles = data.get("articles") or []
        items: list[IngestedItem] = []
        for a in articles:
            if not isinstance(a, dict):
                continue
            url = (a.get("url") or "").strip()
            if not url:
                continue
            title = normalize_text(a.get("title") or "")
            desc = normalize_text(a.get("content") or a.get("description") or "")
            raw_text = f"{title}\n\n{desc}".strip() or title
            author = normalize_text(a.get("author") or a.get("source", {}).get("name", "") if isinstance(a.get("source"), dict) else "")
            published = self._parse_dt(a.get("publishedAt"))
            ext_id = a.get("url") or a.get("title") or str(hash(url))
            engagement_stats = {
                "source": a.get("source", {}).get("name", "") if isinstance(a.get("source"), dict) else "",
            }
            items.append(
                IngestedItem(
                    external_id=ext_id,
                    source_type=SourceType.news_api,
                    title=title[:200] or "(no title)",
                    url=url,
                    author=author,
                    published_at=published,
                    raw_text=raw_text[:50000],
                    engagement_stats=engagement_stats,
                )
            )
        return items
