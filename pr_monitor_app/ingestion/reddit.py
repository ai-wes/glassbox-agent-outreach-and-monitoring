"""Reddit API connector for subreddit and user posts."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class RedditConnector(Connector):
    """
    Reddit API connector using OAuth2 application-only (client credentials).

    Supports:
    - Subreddit: /r/{subreddit}/hot, /new, /top
    - User: /user/{username}/submitted

    Config: client_id, client_secret, user_agent (required), subreddit OR username, sort (hot|new|top), limit
    """

    OAUTH_URL = "https://www.reddit.com/api/v1/access_token"
    API_BASE = "https://oauth.reddit.com"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddit: str | None = None,
        username: str | None = None,
        sort: str = "hot",
        limit: int = 50,
        timeout_seconds: int = 20,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = (user_agent or "NPE/1.0").strip()
        self.subreddit = (subreddit or "").strip().strip("/")
        self.username = (username or "").strip()
        self.sort = sort if sort in ("hot", "new", "top", "rising") else "hot"
        self.limit = min(100, max(1, limit))
        self.timeout_seconds = timeout_seconds

        if not self.subreddit and not self.username:
            raise ValueError("Reddit connector requires subreddit or username")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _get_token(self) -> str:
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                self.OAUTH_URL,
                headers={
                    "Authorization": f"Basic {auth}",
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("access_token", ""))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _get_json(self, url: str, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": self.user_agent,
                },
            )
            resp.raise_for_status()
            return resp.json()

    def _parse_utc(self, ts: float | None) -> datetime:
        if ts is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)

    def _post_to_item(self, d: dict[str, Any]) -> IngestedItem | None:
        post_id = d.get("id")
        if not post_id:
            return None
        title = normalize_text(d.get("title") or "")
        selftext = normalize_text(d.get("selftext") or "")
        raw_text = f"{title}\n\n{selftext}".strip() or title
        if not raw_text:
            return None
        url = d.get("url") or f"https://reddit.com{d.get('permalink', '')}"
        if not url.startswith("http"):
            url = f"https://reddit.com{url}" if url.startswith("/") else f"https://reddit.com/{url}"
        author = normalize_text(d.get("author") or "[deleted]")
        created = self._parse_utc(d.get("created_utc"))
        engagement_stats = {
            "score": int(d.get("score") or 0),
            "num_comments": int(d.get("num_comments") or 0),
            "upvote_ratio": float(d.get("upvote_ratio") or 0),
            "subreddit": d.get("subreddit", ""),
        }
        return IngestedItem(
            external_id=post_id,
            source_type=SourceType.reddit,
            title=title[:200] or "(no title)",
            url=url,
            author=author,
            published_at=created,
            raw_text=raw_text[:50000],
            engagement_stats=engagement_stats,
        )

    async def fetch(self) -> list[IngestedItem]:
        token = await self._get_token()
        if self.subreddit:
            url = f"{self.API_BASE}/r/{self.subreddit}/{self.sort}"
        else:
            url = f"{self.API_BASE}/user/{self.username}/submitted"
        params = {"limit": self.limit}
        data = await self._get_json(f"{url}.json", token)
        children = (data.get("data") or {}).get("children") or []
        items: list[IngestedItem] = []
        for c in children:
            d = c.get("data") if isinstance(c, dict) else None
            if not isinstance(d, dict):
                continue
            item = self._post_to_item(d)
            if item:
                items.append(item)
        return items
