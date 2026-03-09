from __future__ import annotations

from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.ingestion.base import Connector, IngestedItem
from pr_monitor_app.models import SourceType
from pr_monitor_app.state import StateStore
from pr_monitor_app.utils.hashing import sha256_hex
from pr_monitor_app.utils.text import normalize_text


class HTMLDiffConnector(Connector):
    """
    Periodically fetches an HTML page and emits a new item when the extracted text changes.
    State is stored in Redis (last seen hash).
    """

    def __init__(
        self,
        page_url: str,
        *,
        source_type: SourceType = SourceType.blog,
        state: StateStore,
        state_key: str,
        user_agent: str = "NPE/1.0 (+https://example.com)",
        timeout_seconds: int = 20,
        max_text_chars: int = 20_000,
    ) -> None:
        self.page_url = page_url
        self.source_type = source_type
        self.state = state
        self.state_key = state_key
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_text_chars = max_text_chars

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    async def _download(self) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent}) as client:
            resp = await client.get(self.page_url, follow_redirects=True)
            resp.raise_for_status()
            return resp.text

    def _extract(self, html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html, "lxml")
        title = normalize_text((soup.title.string if soup.title and soup.title.string else "") or "")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = normalize_text(soup.get_text(" "))
        if len(text) > self.max_text_chars:
            text = text[: self.max_text_chars]
        return title, text

    async def fetch(self) -> list[IngestedItem]:
        html = await self._download()
        title, text = self._extract(html)
        content_hash = sha256_hex(text)
        last_hash = self.state.get_str(self.state_key)
        if last_hash == content_hash:
            return []

        # update state
        self.state.set_str(self.state_key, content_hash)

        now = datetime.now(timezone.utc)
        return [
            IngestedItem(
                external_id=content_hash,
                source_type=self.source_type,
                title=title,
                url=self.page_url,
                author="",
                published_at=now,
                raw_text=text,
                engagement_stats={},
            )
        ]
