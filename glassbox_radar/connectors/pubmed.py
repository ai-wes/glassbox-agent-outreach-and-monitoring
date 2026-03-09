from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import httpx

from glassbox_radar.connectors.base import Collector
from glassbox_radar.contracts import CollectedSignal, CollectionContext
from glassbox_radar.core.config import get_settings
from glassbox_radar.enums import SignalType, SourceType
from glassbox_radar.utils import compact_whitespace, utcnow


class PubMedCollector(Collector):
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esummary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _query(self, context: CollectionContext) -> str:
        terms = context.search_terms[:4]
        if not terms:
            return ""
        joined = " OR ".join(f'"{term}"' for term in terms)
        return f"({joined})"

    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        query = self._query(context)
        if not query:
            return []

        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": 10,
            "sort": "pub+date",
            "tool": self.settings.pubmed_tool,
            "email": self.settings.pubmed_email,
        }
        if self.settings.pubmed_api_key:
            params["api_key"] = self.settings.pubmed_api_key

        search_response = await client.get(self.esearch_url, params=params)
        search_response.raise_for_status()
        payload = search_response.json()
        id_list = payload.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []

        summary_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "json",
            "tool": self.settings.pubmed_tool,
            "email": self.settings.pubmed_email,
        }
        if self.settings.pubmed_api_key:
            summary_params["api_key"] = self.settings.pubmed_api_key

        summary_response = await client.get(self.esummary_url, params=summary_params)
        summary_response.raise_for_status()
        summary_payload = summary_response.json().get("result", {})

        cutoff = utcnow() - timedelta(days=self.settings.pubmed_days_lookback)
        signals: list[CollectedSignal] = []
        for pubmed_id in id_list:
            item = summary_payload.get(pubmed_id)
            if not item:
                continue
            title = compact_whitespace(item.get("title"))
            sortpubdate = item.get("sortpubdate") or item.get("pubdate")
            published_at = None
            if sortpubdate:
                try:
                    published_at = utcnow().fromisoformat(str(sortpubdate).replace("Z", "+00:00"))
                except ValueError:
                    published_at = None
            if published_at and published_at < cutoff:
                continue

            author_names = ", ".join(author.get("name", "") for author in item.get("authors", [])[:8] if author.get("name"))
            summary = compact_whitespace(
                " | ".join(
                    fragment
                    for fragment in [
                        f"Journal: {item.get('fulljournalname')}" if item.get("fulljournalname") else None,
                        f"Authors: {author_names}" if author_names else None,
                    ]
                    if fragment
                )
            )
            signals.append(
                CollectedSignal(
                    source_type=SourceType.PUBMED,
                    signal_type=SignalType.PUBLICATION,
                    title=title or f"PubMed article {pubmed_id}",
                    summary=summary or None,
                    content=title,
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/",
                    published_at=published_at,
                    confidence=0.72,
                    raw_payload=item,
                )
            )
        return signals
