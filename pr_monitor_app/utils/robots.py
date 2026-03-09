"""Robots.txt cache for Layer 1 ingestion."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from pr_monitor_app.config import settings
from pr_monitor_app.utils.http import HttpFetcher


class RobotsCache:
    """Simple robots.txt cache - allows all if respect_robots_txt is False."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher
        self._cache: dict[str, bool] = {}

    def allowed(self, url: str) -> bool:
        if not settings.respect_robots_txt:
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._cache:
            return self._cache[origin]

        robots_url = urljoin(origin + "/", "robots.txt")
        try:
            resp = self.fetcher.get(robots_url)
            if resp.status_code != 200:
                self._cache[origin] = True
                return True

            content = resp.text.lower()
            disallow_all = "disallow: /" in content or "disallow:/\n" in content
            self._cache[origin] = not disallow_all
            return self._cache[origin]
        except Exception:
            self._cache[origin] = True
            return True
