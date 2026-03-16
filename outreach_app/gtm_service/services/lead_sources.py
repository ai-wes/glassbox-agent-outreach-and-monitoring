from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from pydantic import BaseModel

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput, CandidateIngestRequest, RawSignalInput
from outreach_app.gtm_service.services.html_utils import parse_html_document
from outreach_app.gtm_service.services.text_utils import compute_recency_score, csv_rows, normalize_domain, normalize_url, parse_datetime


class RSSImportResult(BaseModel):
    items: list[CandidateIngestRequest]


class WebsiteSnapshot(BaseModel):
    url: str
    title: str | None = None
    text: str
    links: list[str]


class SourceIngestionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.http_timeout_seconds, follow_redirects=True)

    async def close(self) -> None:
        await self.client.aclose()

    async def import_rss(self, feed_url: str) -> RSSImportResult:
        parsed = feedparser.parse(feed_url)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.settings.default_rss_lookback_hours)
        items: list[CandidateIngestRequest] = []
        for entry in parsed.entries:
            occurred_at = parse_datetime(entry.get("published") or entry.get("updated") or entry.get("created") or None)
            if occurred_at and occurred_at < cutoff:
                continue
            link = entry.get("link")
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            source_domain = normalize_domain(link)
            company_name = source_domain.split(".")[0].replace("-", " ").title() if source_domain else title[:50]
            items.append(
                CandidateIngestRequest(
                    company=CandidateCompanyInput(
                        name=company_name or "Unknown Company",
                        domain=source_domain,
                        website=normalize_url(link) if link else None,
                        source_urls=[link] if link else [],
                    ),
                    signals=[
                        RawSignalInput(
                            type="rss_news",
                            source="rss",
                            source_url=normalize_url(link) if link else None,
                            occurred_at=occurred_at,
                            raw_text=f"{title}\n\n{summary}",
                            metadata_json={"feed_title": parsed.feed.get("title", "")},
                        )
                    ],
                    snippets=[title, summary],
                    raw_page_urls=[normalize_url(link)] if link else [],
                    source="rss",
                )
            )
        return RSSImportResult(items=items)

    async def scrape_website(self, url: str) -> WebsiteSnapshot:
        response = await self.client.get(url)
        response.raise_for_status()
        document = parse_html_document(response.text)
        text = document.text[: self.settings.max_scrape_text_chars]
        links = [href for href in document.links if href.startswith("http://") or href.startswith("https://")][:50]
        return WebsiteSnapshot(
            url=url,
            title=document.title,
            text=text,
            links=links,
        )

    def import_csv(self, file_bytes: bytes) -> list[CandidateIngestRequest]:
        rows = csv_rows(file_bytes)
        results: list[CandidateIngestRequest] = []
        for row in rows:
            company = CandidateCompanyInput(
                name=row.get("company_name") or row.get("company") or row.get("name") or "Unknown Company",
                domain=normalize_domain(row.get("domain") or row.get("website")),
                website=normalize_url(row.get("website")) if row.get("website") else None,
                headcount=int(row["headcount"]) if row.get("headcount") else None,
                funding_stage=row.get("funding_stage") or None,
                industry=row.get("industry") or None,
                ai_bio_relevance=float(row["ai_bio_relevance"]) if row.get("ai_bio_relevance") else None,
                source_urls=[row["source_url"]] if row.get("source_url") else [],
            )
            contact = None
            if any(row.get(key) for key in ["email", "title", "full_name", "first_name", "last_name"]):
                contact = CandidateContactInput(
                    first_name=row.get("first_name") or None,
                    last_name=row.get("last_name") or None,
                    full_name=row.get("full_name") or None,
                    title=row.get("title") or None,
                    linkedin_url=normalize_url(row.get("linkedin_url")) if row.get("linkedin_url") else None,
                    email=row.get("email") or None,
                    seniority=row.get("seniority") or None,
                    function=row.get("function") or None,
                    inferred_buying_role=row.get("inferred_buying_role") or None,
                    email_verified=(row.get("email_verified") or "").lower() in {"1", "true", "yes"},
                )
            signals: list[RawSignalInput] = []
            if row.get("trigger_text"):
                occurred_at = parse_datetime(row.get("trigger_date"))
                signals.append(
                    RawSignalInput(
                        type=row.get("trigger_type") or "csv_trigger",
                        source=row.get("source") or "csv",
                        raw_text=row["trigger_text"],
                        occurred_at=occurred_at,
                        source_url=normalize_url(row.get("source_url")) if row.get("source_url") else None,
                        metadata_json={"recency_score": compute_recency_score(occurred_at)},
                    )
                )
            snippets = [snippet for snippet in [row.get("summary"), row.get("trigger_text")] if snippet]
            results.append(
                CandidateIngestRequest(
                    company=company,
                    contact=contact,
                    signals=signals,
                    snippets=snippets,
                    raw_page_urls=[normalize_url(row.get("website"))] if row.get("website") else [],
                    source="csv",
                    auto_queue=(row.get("auto_queue") or "").lower() in {"1", "true", "yes"},
                )
            )
        return results

    async def enrich_from_urls(self, urls: Sequence[str]) -> list[WebsiteSnapshot]:
        snapshots: list[WebsiteSnapshot] = []
        for raw_url in urls[:5]:
            url = normalize_url(str(raw_url))
            if not url:
                continue
            try:
                snapshots.append(await self.scrape_website(url))
            except httpx.HTTPError:
                continue
        return snapshots
