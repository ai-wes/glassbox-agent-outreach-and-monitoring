from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import httpx

from glassbox_radar.connectors.base import Collector
from glassbox_radar.contracts import CollectedSignal, CollectionContext
from glassbox_radar.core.config import get_settings
from glassbox_radar.enums import SignalType, SourceType
from glassbox_radar.utils import compact_whitespace, contains_any, safe_parse_datetime, utcnow


class PreprintCollector(Collector):
    base_url = "https://api.biorxiv.org/details/{server}/{interval}/0/json"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._cache: dict[str, list[dict]] = {}

    async def _load_server_entries(self, server: str, client: httpx.AsyncClient) -> list[dict]:
        cache_key = f"{server}:{self.settings.preprint_days_lookback}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        url = self.base_url.format(server=server, interval=f"{self.settings.preprint_days_lookback}d")
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        collection = payload.get("collection", [])
        self._cache[cache_key] = collection
        return collection

    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        terms = context.search_terms
        if not terms:
            return []

        cutoff = utcnow() - timedelta(days=self.settings.preprint_days_lookback)
        signals: list[CollectedSignal] = []

        for server, source_type in [("biorxiv", SourceType.BIORXIV), ("medrxiv", SourceType.MEDRXIV)]:
            entries = await self._load_server_entries(server, client)
            for item in entries:
                title = compact_whitespace(item.get("title"))
                abstract = compact_whitespace(item.get("abstract"))
                text = " ".join(filter(None, [title, abstract, item.get("category")]))
                if not contains_any(text, terms):
                    continue
                published_at = safe_parse_datetime(item.get("date"))
                if published_at and published_at < cutoff:
                    continue
                signals.append(
                    CollectedSignal(
                        source_type=source_type,
                        signal_type=SignalType.PREPRINT,
                        title=title or "Preprint",
                        summary=compact_whitespace(
                            " | ".join(
                                fragment
                                for fragment in [
                                    item.get("category"),
                                    (item.get("authors") or "")[:400],
                                ]
                                if fragment
                            )
                        )
                        or None,
                        content=abstract or title,
                        source_url=f"https://doi.org/{item.get('doi')}" if item.get("doi") else f"https://api.biorxiv.org/details/{server}",
                        published_at=published_at,
                        confidence=0.62,
                        raw_payload=item,
                    )
                )
        return signals
