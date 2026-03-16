"""Browser automation and data extraction utilities.

This module encapsulates all browser-based scraping logic for the
outreach system.  It uses Playwright with a headless Chromium
instance to fetch pages, capture HTML and optionally save
screenshots.  Extraction of structured data is delegated to helper
functions that operate on the returned HTML.  Email verification
helpers perform syntax and MX checks to reduce calls to paid
verification APIs.

The scraping functions are designed to be asynchronous and safe to
call from within a Celery task.  Each function will create its own
browser context and close it on completion to avoid leaks.
"""

from __future__ import annotations

import asyncio
import re
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from email_validator import EmailNotValidError, validate_email as _validate_email
import dns.resolver
from playwright.async_api import async_playwright


logger = logging.getLogger(__name__)


async def fetch_page_content(url: str, timeout: int = 15000) -> str:
    """Retrieve the fully rendered HTML of a page using Playwright.

    A new browser and context are created for each call.  If the page
    fails to load or returns a non-200 status, an empty string is
    returned.

    Args:
        url: The URL to fetch.
        timeout: Maximum time to wait for the page to load in
            milliseconds.

    Returns:
        The rendered HTML as a string.
    """
    logger.debug("Fetching page content from %s", url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            response = await page.goto(url, timeout=timeout, wait_until="load")
            if response is None or response.status != 200:
                logger.warning("Non-200 response for %s: %s", url, response.status if response else None)
                html = await page.content()
            else:
                html = await page.content()
        except Exception as exc:
            logger.exception("Error fetching %s: %s", url, exc)
            html = ""
        finally:
            await context.close()
            await browser.close()
        return html


def extract_company_info(html: str) -> Dict[str, Optional[str]]:
    """Parse HTML to extract basic company information.

    This helper attempts to extract the company name and description
    from common meta tags such as `<title>`, `<meta name="description">`
    and OpenGraph tags.  If the elements are absent the values will
    remain ``None``.

    Args:
        html: The HTML content of the page.

    Returns:
        A dictionary with keys ``name`` and ``description``.
    """
    soup = BeautifulSoup(html, "html.parser")
    name: Optional[str] = None
    description: Optional[str] = None
    # Title tag
    title_tag = soup.find("title")
    if title_tag and title_tag.text:
        name = title_tag.text.strip()
    # Meta description
    meta_desc = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()
    # OpenGraph title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        name = name or og_title["content"].strip()
    # OpenGraph description
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = description or og_desc["content"].strip()
    return {"name": name, "description": description}


async def scrape_company(domain: str) -> Dict[str, Optional[str]]:
    """Scrape the company's landing page for basic info.

    This function constructs an HTTPS URL from the domain, fetches the
    page content and then extracts the company name and description.

    Args:
        domain: Domain of the company (without protocol).

    Returns:
        Dictionary with ``name``, ``description`` and ``website`` keys.
    """
    url = f"https://{domain}"
    html = await fetch_page_content(url)
    info = extract_company_info(html)
    info["website"] = url
    return info


def extract_email_candidates(html: str, domain: str) -> List[str]:
    """Extract potential email addresses from HTML matching the given domain.

    Uses a simple regex to find strings that look like email addresses
    ending with the provided domain.  Duplicates are removed.
    """
    pattern = re.compile(r"[\w\.-]+@" + re.escape(domain) + r"\b", re.I)
    candidates = set(re.findall(pattern, html))
    return list(candidates)


async def discover_contacts(domain: str) -> List[Dict[str, Any]]:
    """Discover contact candidates for a company.

    The current implementation fetches the landing page and uses a
    heuristic to extract email addresses.  A more advanced version
    could crawl additional pages or integrate with LinkedIn.  This
    returns a list of dictionaries with at least an ``email`` key.
    """
    url = f"https://{domain}"
    html = await fetch_page_content(url)
    emails = extract_email_candidates(html, domain)
    contacts = []
    for email in emails:
        local_part = email.split("@")[0]
        # naive name extraction from local part (split on dots/underscores)
        parts = re.split(r"[._-]", local_part)
        first = parts[0].capitalize() if parts else None
        last = parts[-1].capitalize() if len(parts) > 1 else None
        contacts.append({
            "first_name": first,
            "last_name": last if last != first else None,
            "full_name": f"{first} {last}".strip() if first or last else None,
            "email": email.lower(),
        })
    return contacts


def validate_email_syntax(email: str) -> bool:
    """Check if an email address has valid syntax using email-validator.

    Returns ``True`` if the email has valid syntax, otherwise
    ``False``.  Any validation errors are logged.
    """
    try:
        _ = _validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError as exc:
        logger.debug("Email syntax invalid for %s: %s", email, exc)
        return False


def dns_mx_exists(domain: str) -> bool:
    """Check if a domain has at least one MX record via DNS.

    Uses dnspython to look up the MX record.  Returns ``True`` if at
    least one MX record is found, otherwise ``False``.
    """
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except Exception as exc:
        logger.debug("MX lookup failed for %s: %s", domain, exc)
        return False


def verify_email_locally(email: str) -> bool:
    """Perform syntax and MX verification for an email.

    This function first checks the local-part syntax using
    ``validate_email_syntax`` and then ensures that the domain has a
    valid MX record via ``dns_mx_exists``.
    """
    if not validate_email_syntax(email):
        return False
    domain = email.split("@")[-1]
    return dns_mx_exists(domain)
