"""
Real text-analysis utilities used across monitors.

All brand detection is based on pattern matching against
the actual brand names supplied in BrandConfig.
Sentiment and accuracy analysis delegates to real OpenAI API calls.
If the API key is unavailable the caller gets Status.SKIPPED.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Optional

from .config import BrandConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Brand mention detection — deterministic string matching
# ---------------------------------------------------------------------------

def find_brand_mentions(text: str, brand: BrandConfig) -> list[dict]:
    """Return list of {name, start, end} for each brand name match in text."""
    if not text:
        return []
    mentions: list[dict] = []
    for name in brand.all_names:
        try:
            pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        except re.error:
            continue
        for m in pattern.finditer(text):
            mentions.append({"name": name, "start": m.start(), "end": m.end()})
    return mentions


def brand_mentioned(text: str, brand: BrandConfig) -> bool:
    return len(find_brand_mentions(text, brand)) > 0


def domain_in_citations(citation_urls: list[str], brand: BrandConfig) -> bool:
    for url in citation_urls:
        url_lower = url.lower()
        for domain in brand.brand_domains:
            if domain.lower() in url_lower:
                return True
    return False


# ---------------------------------------------------------------------------
# Prominence scoring (0–3) based on position within the text
# ---------------------------------------------------------------------------

def compute_prominence(text: str, brand: BrandConfig) -> int:
    mentions = find_brand_mentions(text, brand)
    if not mentions:
        return 0
    earliest = min(m["start"] for m in mentions)
    length = len(text)
    if length == 0:
        return 0
    ratio = earliest / length
    if ratio < 0.10:
        return 3
    elif ratio < 0.30:
        return 2
    else:
        return 1


# ---------------------------------------------------------------------------
# Extract domains from a list of citation URLs
# ---------------------------------------------------------------------------

def extract_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    for url in urls:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host.startswith("www."):
                host = host[4:]
            if host:
                domains.append(host)
        except Exception:
            continue
    return domains


# ---------------------------------------------------------------------------
# Sentiment analysis via OpenAI (real API call)
# Returns -1 / 0 / +1 or None if SKIPPED
# ---------------------------------------------------------------------------

def analyze_sentiment_via_openai(
    text: str,
    brand_name: str,
    openai_api_key: str,
    model: str = "gpt-4o-mini",
) -> Optional[int]:
    """Call OpenAI to classify brand sentiment. Returns -1/0/+1 or None on failure."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        prompt = (
            f'The following text is an AI-generated answer. '
            f'Classify the overall sentiment toward the brand "{brand_name}" '
            f'as exactly one of: POSITIVE, NEUTRAL, NEGATIVE.\n\n'
            f'Text:\n"""\n{text[:4000]}\n"""\n\n'
            f'Return ONLY one word: POSITIVE, NEUTRAL, or NEGATIVE.'
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        answer = resp.choices[0].message.content.strip().upper() if resp.choices else ""
        mapping = {"POSITIVE": 1, "NEUTRAL": 0, "NEGATIVE": -1}
        return mapping.get(answer, 0)
    except Exception as exc:
        logger.warning("Sentiment analysis failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Accuracy checking via OpenAI (real API call)
# Returns 1 (accurate) / 0 (inaccurate) or None if SKIPPED
# ---------------------------------------------------------------------------

def check_accuracy_via_openai(
    ai_response_text: str,
    brand_name: str,
    ground_truth_claims: dict[str, str],
    openai_api_key: str,
    model: str = "gpt-4o-mini",
) -> Optional[int]:
    """Compare AI response against ground-truth claims. Returns 1 (accurate) or 0."""
    if not ground_truth_claims:
        return 1  # Nothing to contradict — assume accurate
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        claims_text = "\n".join(f"- {k}: {v}" for k, v in ground_truth_claims.items())
        prompt = (
            f'Given these verified facts about "{brand_name}":\n'
            f"{claims_text}\n\n"
            f'Analyze the following AI-generated text for factual accuracy '
            f'about "{brand_name}":\n'
            f'"""\n{ai_response_text[:4000]}\n"""\n\n'
            f'Does the text contradict any of the verified facts above? '
            f'Answer ONLY with a JSON object: '
            f'{{"accurate": true, "issues": []}} '
            f'or {{"accurate": false, "issues": ["description of each contradiction"]}}'
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip() if resp.choices else "{}"
        # Try to parse JSON from the response
        raw_clean = raw
        if raw_clean.startswith("```"):
            lines = raw_clean.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw_clean = "\n".join(lines)
        parsed = json.loads(raw_clean)
        return 1 if parsed.get("accurate", True) else 0
    except Exception as exc:
        logger.warning("Accuracy check failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def hash_response(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
