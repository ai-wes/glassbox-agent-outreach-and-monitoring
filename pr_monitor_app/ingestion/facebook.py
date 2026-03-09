"""Facebook/Meta Graph API connector for page posts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class FacebookConnector(Connector):
    """
    Facebook Graph API connector for page published posts.

    GET /{page-id}/published_posts with access_token.
    Config: access_token (required), page_id (required), limit (default 50)
    """

    BASE = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        *,
        access_token: str,
        page_id: str,
        limit: int = 50,
        timeout_seconds: int = 20,
        user_agent: str = "NPE/1.0 (+https://example.com)",
    ) -> None:
        self.access_token = access_token
        self.page_id = (page_id or "").strip()
        self.limit = min(100, max(1, limit))
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

        if not self.page_id:
            raise ValueError("Facebook connector requires page_id")

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
    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        params["access_token"] = self.access_token
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def _post_to_item(self, post: dict[str, Any], post_id: str) -> IngestedItem | None:
        message = normalize_text(post.get("message") or post.get("story") or "")
        if not message:
            return None
        created = self._parse_dt(post.get("created_time"))
        url = post.get("permalink_url") or f"https://www.facebook.com/{post_id}"
        likes = post.get("likes") or {}
        comments = post.get("comments") or {}
        shares = post.get("shares") or {}
        engagement_stats: dict[str, Any] = {
            "likes": int(likes.get("summary", {}).get("total_count", 0)) if isinstance(likes, dict) else 0,
            "comments": int(comments.get("summary", {}).get("total_count", 0)) if isinstance(comments, dict) else 0,
            "shares": int(shares.get("count", 0)) if isinstance(shares, dict) else 0,
        }
        return IngestedItem(
            external_id=post_id,
            source_type=SourceType.facebook,
            title=message[:120] + ("..." if len(message) > 120 else ""),
            url=url,
            author=self.page_id,
            published_at=created,
            raw_text=message[:50000],
            engagement_stats=engagement_stats,
        )

    async def fetch(self) -> list[IngestedItem]:
        url = f"{self.BASE}/{self.page_id}/published_posts"
        params = {
            "fields": "id,message,story,created_time,permalink_url,likes.summary(true),comments.summary(true),shares",
            "limit": self.limit,
        }
        data = await self._get_json(url, params)
        posts = data.get("data") or []
        items: list[IngestedItem] = []
        for p in posts:
            if not isinstance(p, dict):
                continue
            post_id = p.get("id")
            if not post_id:
                continue
            item = self._post_to_item(p, str(post_id))
            if item:
                items.append(item)
        return items
