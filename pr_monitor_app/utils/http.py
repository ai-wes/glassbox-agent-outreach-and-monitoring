"""Sync HTTP fetcher for Layer 1 ingestion."""

from __future__ import annotations

from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pr_monitor_app.config import settings


class HttpFetcher:
    """Sync HTTP client with retries for ingestion."""

    def __init__(
        self,
        timeout: float | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout = timeout or settings.http_timeout_seconds
        self.user_agent = user_agent or settings.http_user_agent
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=6))
    def get(self, url: str) -> httpx.Response:
        return self._get_client().get(url)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
