from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence

import httpx

from glassbox_radar.connectors.base import Collector
from glassbox_radar.contracts import CollectedSignal, CollectionContext
from glassbox_radar.enums import SignalType, SourceType
from glassbox_radar.utils import compact_whitespace, contains_any, safe_parse_datetime


class RSSCollector(Collector):
    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        if not context.rss_feeds:
            return []

        terms = context.search_terms
        signals: list[CollectedSignal] = []
        for feed_url in context.rss_feeds:
            response = await client.get(feed_url)
            response.raise_for_status()
            root = ET.fromstring(response.text.encode("utf-8"))

            items = root.findall(".//item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:30]:
                title = self._find_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
                summary = self._find_text(
                    item,
                    [
                        "description",
                        "summary",
                        "{http://www.w3.org/2005/Atom}summary",
                        "{http://www.w3.org/2005/Atom}content",
                    ],
                )
                url = self._find_link(item) or feed_url
                published = self._find_text(
                    item,
                    [
                        "pubDate",
                        "published",
                        "updated",
                        "{http://www.w3.org/2005/Atom}published",
                        "{http://www.w3.org/2005/Atom}updated",
                    ],
                )
                text = " ".join(filter(None, [title, summary]))
                if terms and not contains_any(text, terms):
                    continue
                signals.append(
                    CollectedSignal(
                        source_type=SourceType.RSS,
                        signal_type=SignalType.PRESS_RELEASE,
                        title=compact_whitespace(title) or "RSS item",
                        summary=compact_whitespace(summary) or None,
                        content=compact_whitespace(summary or title),
                        source_url=url,
                        published_at=safe_parse_datetime(published),
                        confidence=0.66,
                        raw_payload={"feed_url": feed_url},
                    )
                )
        return signals

    @staticmethod
    def _find_text(item: ET.Element, tags: list[str]) -> str | None:
        for tag in tags:
            node = item.find(tag)
            if node is not None and node.text:
                return node.text
        return None

    @staticmethod
    def _find_link(item: ET.Element) -> str | None:
        link_node = item.find("link")
        if link_node is not None:
            if link_node.text:
                return link_node.text
            href = link_node.attrib.get("href")
            if href:
                return href
        atom_link = item.find("{http://www.w3.org/2005/Atom}link")
        if atom_link is not None:
            return atom_link.attrib.get("href")
        return None
