from __future__ import annotations

from collections.abc import Sequence

import feedparser
import httpx

from glassbox_radar.connectors.base import Collector
from glassbox_radar.contracts import CollectedSignal, CollectionContext
from glassbox_radar.enums import SignalType, SourceType
from glassbox_radar.utils import compact_whitespace, contains_any, safe_parse_datetime


class FundingCollector(Collector):
    FEEDS: list[str] = [
        "https://feeds.feedburner.com/FierceBiotechFunding",
        "https://www.labiotech.eu/category/biotech-funding/feed/",
        "https://xtalks.com/feed/?post_type=insight&biotech-funding",
    ]

    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        terms = context.search_terms
        signals: list[CollectedSignal] = []
        for feed_url in self.FEEDS:
            try:
                response = await client.get(feed_url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue

            parsed = feedparser.parse(response.text)
            for entry in parsed.entries[:30]:
                title = (entry.get("title") or "").strip()
                summary = entry.get("summary") or entry.get("description") or ""
                link = entry.get("link") or feed_url
                published = entry.get("published") or entry.get("updated") or entry.get("pubDate")
                text = " ".join(filter(None, [title, summary]))
                if terms and not contains_any(text, terms):
                    continue
                signals.append(
                    CollectedSignal(
                        source_type=SourceType.RSS,
                        signal_type=SignalType.FINANCING_EVENT,
                        title=compact_whitespace(title) or "Funding event",
                        summary=compact_whitespace(summary) or None,
                        content=compact_whitespace(summary or title),
                        source_url=link,
                        published_at=safe_parse_datetime(published),
                        confidence=0.70,
                        raw_payload={"feed_url": feed_url},
                    )
                )
        return signals
