"""Twitter/X API v2 connector for user timeline and search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class TwitterConnector(Connector):
    """
    Twitter/X API v2 connector.

    Supports:
    - User timeline: GET /2/users/:id/tweets (requires user_id or username)
    - Recent search: GET /2/tweets/search/recent?query=... (requires query)

    Config: bearer_token (required), user_id OR username OR query, max_results (default 50)
    """

    BASE = "https://api.twitter.com/2"

    def __init__(
        self,
        *,
        bearer_token: str,
        user_id: str | None = None,
        username: str | None = None,
        query: str | None = None,
        max_results: int = 50,
        timeout_seconds: int = 20,
        user_agent: str = "NPE/1.0 (+https://example.com)",
    ) -> None:
        self.bearer_token = bearer_token
        self.user_id = user_id
        self.username = (username or "").strip().lstrip("@")
        self.query = (query or "").strip()
        self.max_results = min(100, max(10, max_results))
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

        if not user_id and not self.username and not self.query:
            raise ValueError("Twitter connector requires user_id, username, or query")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": self.user_agent,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=self._headers()) as client:
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def _resolve_user_id(self) -> str | None:
        if self.user_id:
            return self.user_id
        if not self.username:
            return None
        url = f"{self.BASE}/users/by/username/{self.username}"
        data = await self._get_json(url)
        u = data.get("data", {})
        return str(u.get("id", "")) if isinstance(u, dict) else None

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

    def _tweet_to_item(self, t: dict[str, Any], author: str = "") -> IngestedItem | None:
        tid = t.get("id")
        if not tid:
            return None
        text = t.get("text", "")
        text = normalize_text(text)
        if not text:
            return None
        url = f"https://twitter.com/i/status/{tid}"
        created = self._parse_dt(t.get("created_at"))
        engagement = t.get("public_metrics") or {}
        engagement_stats = {
            "like_count": int(engagement.get("like_count") or 0),
            "retweet_count": int(engagement.get("retweet_count") or 0),
            "reply_count": int(engagement.get("reply_count") or 0),
            "quote_count": int(engagement.get("quote_count") or 0),
        }
        return IngestedItem(
            external_id=tid,
            source_type=SourceType.twitter,
            title=text[:120] + ("..." if len(text) > 120 else ""),
            url=url,
            author=author or "unknown",
            published_at=created,
            raw_text=text,
            engagement_stats=engagement_stats,
        )

    async def fetch(self) -> list[IngestedItem]:
        items: list[IngestedItem] = []

        if self.query:
            return await self._fetch_search()
        uid = await self._resolve_user_id()
        if uid:
            return await self._fetch_user_timeline(uid)
        return items

    async def _fetch_user_timeline(self, user_id: str) -> list[IngestedItem]:
        url = f"{self.BASE}/users/{user_id}/tweets"
        params: dict[str, Any] = {
            "max_results": self.max_results,
            "tweet.fields": "created_at,public_metrics",
            "expansions": "author_id",
            "user.fields": "username",
        }
        data = await self._get_json(url, params)
        tweets = data.get("data") or []
        users = {u["id"]: u.get("username", u.get("name", "")) for u in (data.get("includes", {}).get("users") or [])}

        items: list[IngestedItem] = []
        for t in tweets:
            author = users.get(t.get("author_id", ""), "")
            item = self._tweet_to_item(t, author=author)
            if item:
                items.append(item)

        return items

    async def _fetch_search(self) -> list[IngestedItem]:
        url = f"{self.BASE}/tweets/search/recent"
        params: dict[str, Any] = {
            "query": self.query,
            "max_results": min(100, self.max_results),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username",
        }
        data = await self._get_json(url, params)
        tweets = data.get("data") or []
        users = {u["id"]: u.get("username", u.get("name", "")) for u in (data.get("includes", {}).get("users") or [])}

        items: list[IngestedItem] = []
        for t in tweets:
            author = users.get(t.get("author_id", ""), "")
            item = self._tweet_to_item(t, author=author)
            if item:
                items.append(item)
        return items
