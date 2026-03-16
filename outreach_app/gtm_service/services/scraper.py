from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.services.html_utils import HTMLDocument, meta_content, parse_html_document
from outreach_app.gtm_service.services.text_utils import normalize_domain, normalize_url

EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
CONTACT_PATH_HINTS = ("contact", "about", "team", "people", "company")


class CompanySnapshot(BaseModel):
    domain: str
    website: str
    title: str | None = None
    description: str | None = None


class ContactCandidate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str


class ProspectingScraper:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "GlassboxOutreachBot/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def scrape_company(self, domain: str) -> CompanySnapshot:
        normalized_domain = normalize_domain(domain)
        if not normalized_domain:
            raise ValueError("Domain is required")
        homepage_url = normalize_url(normalized_domain)
        html, resolved_url = await self._fetch_html(homepage_url)
        document = parse_html_document(html)
        description = self._meta_content(
            document,
            selectors=[
                {"name": re.compile(r"description", re.IGNORECASE)},
                {"property": "og:description"},
            ],
        )
        og_title = self._meta_content(document, selectors=[{"property": "og:title"}])
        return CompanySnapshot(
            domain=normalized_domain,
            website=str(resolved_url),
            title=og_title or document.title,
            description=description,
        )

    async def discover_contacts(self, domain: str) -> list[ContactCandidate]:
        normalized_domain = normalize_domain(domain)
        if not normalized_domain:
            return []
        homepage_url = normalize_url(normalized_domain)
        html, resolved_url = await self._fetch_html(homepage_url)
        candidate_urls = self._candidate_contact_urls(html=html, base_url=str(resolved_url))
        texts = [html]
        for url in candidate_urls[:3]:
            try:
                extra_html, _ = await self._fetch_html(url)
            except httpx.HTTPError:
                continue
            texts.append(extra_html)

        contacts: list[ContactCandidate] = []
        seen: set[str] = set()
        for text in texts:
            for email in self._extract_domain_emails(text, normalized_domain):
                if email in seen:
                    continue
                seen.add(email)
                contacts.append(self._contact_from_email(email))
        return contacts

    def verify_email(self, email: str | None, *, company_domain: str | None = None) -> bool:
        if not email:
            return False
        lowered = email.strip().lower()
        if not EMAIL_PATTERN.fullmatch(lowered):
            return False
        if company_domain:
            return lowered.endswith(f"@{normalize_domain(company_domain)}")
        return True

    async def _fetch_html(self, url: str) -> tuple[str, httpx.URL]:
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text, response.url

    def _candidate_contact_urls(self, *, html: str, base_url: str) -> list[str]:
        urls: list[str] = []
        document = parse_html_document(html, base_url=base_url)
        for full_url in document.links:
            href = full_url.strip()
            if not href or href.startswith("#") or href.startswith("mailto:"):
                continue
            lowered = full_url.lower()
            if any(f"/{hint}" in lowered for hint in CONTACT_PATH_HINTS):
                urls.append(full_url)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    def _extract_domain_emails(self, text: str, domain: str) -> list[str]:
        emails = {
            match.group(0).lower()
            for match in EMAIL_PATTERN.finditer(text or "")
            if match.group(0).lower().endswith(f"@{domain}")
        }
        return sorted(emails)

    def _contact_from_email(self, email: str) -> ContactCandidate:
        local_part = email.split("@", 1)[0]
        parts = [part for part in re.split(r"[._-]+", local_part) if part]
        first_name = parts[0].capitalize() if parts else None
        last_name = parts[1].capitalize() if len(parts) > 1 else None
        if first_name and last_name:
            full_name = f"{first_name} {last_name}"
        else:
            full_name = first_name
        return ContactCandidate(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            email=email,
        )

    def _meta_content(self, document: HTMLDocument, *, selectors: list[dict[str, Any]]) -> str | None:
        return meta_content(document, selectors=selectors)
