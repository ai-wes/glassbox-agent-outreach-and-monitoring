"""
SERP feature monitoring via DuckDuckGo search results.

Monitors search results for:
  - Brand mention in result snippets/titles
  - Brand-domain citation among top result links
  - Basic prominence scoring

No API key required.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from .config import BrandConfig, PromptEntry, Secrets
from .models import ModuleResult, Observation, Status
from .text_analysis import (
    brand_mentioned,
    compute_prominence,
    domain_in_citations,
    extract_domains,
    hash_response,
)

logger = logging.getLogger(__name__)

SUPPORTED_SEARCH_PLATFORMS = {
    "google": "google",
    "bing": "bing",
}


def _unwrap_ddg_redirect(url: str) -> str:
    """Unwrap DuckDuckGo redirect URL to target URL when possible."""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if parsed.path.startswith("/l/"):
            qs = parse_qs(parsed.query)
            uddg = qs.get("uddg")
            if uddg and isinstance(uddg, list) and uddg[0]:
                return unquote(uddg[0])
    except Exception:
        return url
    return url


def _call_duckduckgo(
    query: str,
    *,
    max_results: int = 10,
    timeout_seconds: float = 20.0,
) -> Optional[dict]:
    """Execute a DuckDuckGo HTML search and return normalized results."""
    try:
        import httpx
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("Required packages for DuckDuckGo search are not available")
        return None

    params: dict[str, Any] = {"q": query, "kl": "us-en"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }

    try:
        with httpx.Client(timeout=timeout_seconds, headers=headers, follow_redirects=True) as client:
            resp = client.get("https://duckduckgo.com/html/", params=params)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        results: list[dict[str, str]] = []

        for card in soup.select(".result"):
            if len(results) >= max_results:
                break

            link_el = card.select_one("a.result__a")
            if link_el is None:
                continue

            raw_href = str(link_el.get("href", "")).strip()
            url = _unwrap_ddg_redirect(raw_href)
            title = link_el.get_text(" ", strip=True)

            snippet_el = card.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

            if not url:
                continue

            results.append({"title": title, "url": url, "snippet": snippet})

        return {
            "query": query,
            "search_url": f"https://duckduckgo.com/?q={quote_plus(query)}",
            "results": results,
        }
    except Exception as exc:
        logger.error("DuckDuckGo call failed for query '%s': %s", query, exc)
        return None


def _extract_search_snippets(payload: dict) -> tuple[str, list[str]]:
    """Extract combined text and citation URLs from normalized DDG payload."""
    text_parts: list[str] = []
    citation_urls: list[str] = []

    rows = payload.get("results", [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            snippet = str(row.get("snippet") or "").strip()
            url = str(row.get("url") or "").strip()
            if title:
                text_parts.append(title)
            if snippet:
                text_parts.append(snippet)
            if url:
                citation_urls.append(url)

    return "\n".join(text_parts), citation_urls


def monitor_serp(
    prompts: list[PromptEntry],
    brand: BrandConfig,
    secrets: Secrets,
    delay_between_calls: float = 2.0,
) -> tuple[list[Observation], ModuleResult]:
    """Run search-result monitoring for prompts that target google/bing."""
    _ = secrets  # kept for signature compatibility; no key required for DDG mode.

    observations: list[Observation] = []
    errors = 0

    for prompt in prompts:
        for plat in prompt.platforms:
            if SUPPORTED_SEARCH_PLATFORMS.get(plat) is None:
                continue  # Not a SERP platform

            payload = _call_duckduckgo(prompt.query)
            if payload is None:
                obs = Observation(
                    platform=plat,
                    query_group=prompt.group,
                    query=prompt.query,
                    business_value=prompt.business_value,
                    risk_level=prompt.risk_level,
                    source_api="duckduckgo",
                    status=Status.FAILED,
                    notes="DuckDuckGo call returned None",
                )
                observations.append(obs)
                errors += 1
                continue

            raw_ref = hash_response(json.dumps(payload, default=str))

            combined_text, citations = _extract_search_snippets(payload)
            has_results = bool(citations)

            mentioned = 1 if brand_mentioned(combined_text, brand) else 0
            cited = 1 if domain_in_citations(citations, brand) else 0
            own_domain_cited = cited
            prominence = compute_prominence(combined_text, brand) if mentioned else 0
            domains = extract_domains(citations)
            search_ref = str(payload.get("search_url") or "")

            notes_parts = []
            if has_results:
                notes_parts.append(f"DDG_RESULTS:{len(citations)}")

            obs = Observation(
                platform=plat,
                query_group=prompt.group,
                query=prompt.query,
                business_value=prompt.business_value,
                risk_level=prompt.risk_level,
                brand_mentioned=mentioned,
                brand_cited=cited,
                own_domain_cited=own_domain_cited,
                citation_domains=";".join(domains),
                ai_answer_url_or_ref=search_ref,
                prominence_score=prominence,
                sentiment_score=0,  # Requires OpenAI — done in analysis pass
                accuracy_flag=1,     # Requires OpenAI — done in analysis pass
                actionability=1 if cited else 0,
                source_api="duckduckgo",
                raw_response_ref=raw_ref,
                notes=";".join(notes_parts),
                status=Status.SUCCESS,
            )
            observations.append(obs)

            if delay_between_calls > 0:
                time.sleep(delay_between_calls)

    return observations, ModuleResult(
        module="serp_monitor",
        status=Status.SUCCESS if errors == 0 else Status.FAILED,
        reason=f"{errors} API call(s) failed" if errors > 0 else None,
        records_produced=len(observations),
    )
