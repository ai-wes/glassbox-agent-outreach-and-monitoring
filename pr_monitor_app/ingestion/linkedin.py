from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.utils.text import normalize_text


class LinkedInUGCPostsConnector(Connector):
    """
    LinkedIn ingestion via official UGC Posts API (v2).

    Fetches posts by author (person or organization URN):
      GET https://api.linkedin.com/v2/ugcPosts?q=authors&authors=List({encoded authorUrn})&sortBy=LAST_MODIFIED&count=N

    Optionally fetches engagement counts via Social Metadata API (REST):
      GET https://api.linkedin.com/rest/socialMetadata?ids=List({encoded postUrn},{encoded postUrn})

    References:
    - UGC Post API: Microsoft Learn (Find UGC Posts by Authors).
    - Social Metadata API: Microsoft Learn.
    """
    def __init__(
        self,
        *,
        access_token: str,
        author_urn: str,
        count: int = 20,
        sort_by: str = "LAST_MODIFIED",
        timeout_seconds: int = 20,
        linkedin_version: str = "202602",
        fetch_social_metadata: bool = True,
        user_agent: str = "NPE/1.0 (+https://example.com)",
    ) -> None:
        self.access_token = access_token
        self.author_urn = author_urn
        self.count = max(1, min(int(count), 100))
        self.sort_by = sort_by
        self.timeout_seconds = timeout_seconds
        self.linkedin_version = linkedin_version
        self.fetch_social_metadata = fetch_social_metadata
        self.user_agent = user_agent

    def _headers_v2(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "User-Agent": self.user_agent,
        }

    def _headers_rest(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": self.linkedin_version,
            "User-Agent": self.user_agent,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()

    def _ms_to_dt(self, ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def _extract_text(self, el: dict[str, Any]) -> str:
        sc = el.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        commentary = sc.get("shareCommentary", {}) or {}
        text = commentary.get("text") or ""
        return normalize_text(text)

    def _extract_created_ms(self, el: dict[str, Any]) -> int:
        # Prefer 'created.time' (ms), then 'firstPublishedAt' if present, else 'lastModified.time'
        created = el.get("created") or {}
        if isinstance(created, dict) and isinstance(created.get("time"), int):
            return int(created["time"])
        if isinstance(el.get("firstPublishedAt"), int):
            return int(el["firstPublishedAt"])
        last_mod = el.get("lastModified") or {}
        if isinstance(last_mod, dict) and isinstance(last_mod.get("time"), int):
            return int(last_mod["time"])
        # fallback now
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    async def _fetch_posts(self) -> list[dict[str, Any]]:
        base = "https://api.linkedin.com/v2/ugcPosts"
        # URN must be URL encoded inside List(...)
        encoded_author = quote(self.author_urn, safe="")
        url = f"{base}?q=authors&authors=List({encoded_author})&sortBy={self.sort_by}&count={self.count}"
        data = await self._get_json(url, headers=self._headers_v2())
        elements = data.get("elements") or []
        if not isinstance(elements, list):
            return []
        return [e for e in elements if isinstance(e, dict)]

    async def _fetch_social_metadata_batch(self, post_urns: list[str]) -> dict[str, dict[str, Any]]:
        if not post_urns:
            return {}
        # LinkedIn REST supports up to a reasonable list size; keep batches small.
        out: dict[str, dict[str, Any]] = {}
        batch_size = 20
        for i in range(0, len(post_urns), batch_size):
            batch = post_urns[i : i + batch_size]
            # Each URN should be URL encoded in List(...)
            encoded = ",".join(quote(u, safe="") for u in batch)
            url = f"https://api.linkedin.com/rest/socialMetadata?ids=List({encoded})"
            data = await self._get_json(url, headers=self._headers_rest())
            results = data.get("results") or {}
            if isinstance(results, dict):
                for k, v in results.items():
                    if isinstance(v, dict):
                        out[str(k)] = v
        return out

    def _reaction_count(self, social_meta: dict[str, Any]) -> int:
        rs = social_meta.get("reactionSummaries") or {}
        total = 0
        if isinstance(rs, dict):
            for _, entry in rs.items():
                if isinstance(entry, dict) and isinstance(entry.get("count"), int):
                    total += int(entry["count"])
        return total

    async def fetch(self) -> list[IngestedItem]:
        posts = await self._fetch_posts()
        urns = [str(p.get("id")) for p in posts if p.get("id")]
        meta: dict[str, dict[str, Any]] = {}
        if self.fetch_social_metadata:
            # Social metadata endpoint accepts shareUrn/ugcPostUrn as key; use post URN.
            meta = await self._fetch_social_metadata_batch(urns)

        items: list[IngestedItem] = []
        for el in posts:
            post_urn = str(el.get("id") or "").strip()
            if not post_urn:
                continue
            text = self._extract_text(el)
            created_ms = self._extract_created_ms(el)
            published_at = self._ms_to_dt(created_ms)
            author = normalize_text(str(el.get("author") or ""))
            title = normalize_text(text[:120])

            sm = meta.get(post_urn) or {}
            engagement_stats = {
                "reaction_count": self._reaction_count(sm),
                "comment_count": int((sm.get("commentSummary") or {}).get("count") or 0),
                "comments_state": sm.get("commentsState") or None,
                "social_entity": sm.get("entity") or None,
                "linkedin_post_urn": post_urn,
            }

            items.append(
                IngestedItem(
                    external_id=post_urn,
                    source_type=SourceType.linkedin,
                    title=title,
                    url=post_urn,  # store URN; use brief URL for click-through in notifications
                    author=author,
                    published_at=published_at,
                    raw_text=text,
                    engagement_stats=engagement_stats,
                )
            )
        return items
