"""
AI answer-engine prompt monitoring.

Monitors ChatGPT (OpenAI) and Perplexity for:
  - Whether the brand is mentioned in the AI answer
  - Whether the brand's domain is cited (Perplexity returns citations)
  - Prominence, sentiment, accuracy of the answer

Requires OPENAI_API_KEY and/or PERPLEXITY_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import requests

from .config import BrandConfig, PromptEntry, Secrets
from .models import ModuleResult, Observation, Status
from .text_analysis import (
    analyze_sentiment_via_openai,
    brand_mentioned,
    check_accuracy_via_openai,
    compute_prominence,
    domain_in_citations,
    extract_domains,
    hash_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI chat completion
# ---------------------------------------------------------------------------

def _query_openai(
    query: str, api_key: str, model: str = "gpt-4o-mini"
) -> Optional[tuple[str, str]]:
    """Query OpenAI chat completions. Returns (answer_text, response_id) or None."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
            max_tokens=1500,
            temperature=0.0,
        )
        text = resp.choices[0].message.content if resp.choices else ""
        resp_id = resp.id or hash_response(text or "")
        return (text or "", resp_id)
    except Exception as exc:
        logger.error("OpenAI call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Perplexity API (OpenAI-compatible with citations)
# ---------------------------------------------------------------------------

def _query_perplexity(
    query: str, api_key: str, model: str = "sonar"
) -> Optional[tuple[str, list[str], str]]:
    """Query Perplexity API. Returns (answer_text, citation_urls, request_id) or None."""
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 1500,
                "temperature": 0.0,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = ""
        if data.get("choices"):
            msg = data["choices"][0].get("message", {})
            answer = msg.get("content", "")
        citations: list[str] = data.get("citations", [])
        req_id = data.get("id", hash_response(answer))
        return (answer, citations, str(req_id))
    except Exception as exc:
        logger.error("Perplexity call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

def monitor_prompts(
    prompts: list[PromptEntry],
    brand: BrandConfig,
    secrets: Secrets,
    delay_between_calls: float = 1.5,
) -> tuple[list[Observation], ModuleResult]:
    """Run prompt monitoring across OpenAI and Perplexity."""
    observations: list[Observation] = []
    errors = 0
    skipped_platforms: set[str] = set()

    for prompt in prompts:
        for plat in prompt.platforms:
            # ------ OpenAI ------
            if plat == "openai":
                if not secrets.openai_api_key:
                    if "openai" not in skipped_platforms:
                        skipped_platforms.add("openai")
                        logger.info("OPENAI_API_KEY not set — openai platform SKIPPED")
                    obs = Observation(
                        platform="openai",
                        query_group=prompt.group,
                        query=prompt.query,
                        business_value=prompt.business_value,
                        risk_level=prompt.risk_level,
                        source_api="openai",
                        status=Status.SKIPPED,
                        notes="OPENAI_API_KEY not configured",
                    )
                    observations.append(obs)
                    continue

                result = _query_openai(prompt.query, secrets.openai_api_key)
                if result is None:
                    obs = Observation(
                        platform="openai",
                        query_group=prompt.group,
                        query=prompt.query,
                        business_value=prompt.business_value,
                        risk_level=prompt.risk_level,
                        source_api="openai",
                        status=Status.FAILED,
                        notes="OpenAI API call failed",
                    )
                    observations.append(obs)
                    errors += 1
                    continue

                answer_text, resp_id = result
                mentioned = 1 if brand_mentioned(answer_text, brand) else 0
                prominence = compute_prominence(answer_text, brand) if mentioned else 0

                # Sentiment & accuracy via OpenAI (real API calls)
                sent = analyze_sentiment_via_openai(
                    answer_text, brand.brand_name, secrets.openai_api_key
                )
                acc = check_accuracy_via_openai(
                    answer_text, brand.brand_name, brand.key_claims,
                    secrets.openai_api_key,
                )

                obs = Observation(
                    platform="openai",
                    query_group=prompt.group,
                    query=prompt.query,
                    business_value=prompt.business_value,
                    risk_level=prompt.risk_level,
                    brand_mentioned=mentioned,
                    brand_cited=0,  # Standard ChatGPT has no citation links
                    own_domain_cited=0,
                    citation_domains="",
                    ai_answer_url_or_ref=resp_id,
                    prominence_score=prominence,
                    sentiment_score=sent if sent is not None else 0,
                    accuracy_flag=acc if acc is not None else 1,
                    actionability=0,
                    source_api="openai",
                    raw_response_ref=resp_id,
                    notes="" if sent is not None else "sentiment_analysis_skipped",
                    status=Status.SUCCESS,
                )
                observations.append(obs)

                if delay_between_calls > 0:
                    time.sleep(delay_between_calls)

            # ------ Perplexity ------
            elif plat == "perplexity":
                if not secrets.perplexity_api_key:
                    if "perplexity" not in skipped_platforms:
                        skipped_platforms.add("perplexity")
                        logger.info("PERPLEXITY_API_KEY not set — perplexity platform SKIPPED")
                    obs = Observation(
                        platform="perplexity",
                        query_group=prompt.group,
                        query=prompt.query,
                        business_value=prompt.business_value,
                        risk_level=prompt.risk_level,
                        source_api="perplexity",
                        status=Status.SKIPPED,
                        notes="PERPLEXITY_API_KEY not configured",
                    )
                    observations.append(obs)
                    continue

                result = _query_perplexity(prompt.query, secrets.perplexity_api_key)
                if result is None:
                    obs = Observation(
                        platform="perplexity",
                        query_group=prompt.group,
                        query=prompt.query,
                        business_value=prompt.business_value,
                        risk_level=prompt.risk_level,
                        source_api="perplexity",
                        status=Status.FAILED,
                        notes="Perplexity API call failed",
                    )
                    observations.append(obs)
                    errors += 1
                    continue

                answer_text, citations, req_id = result
                mentioned = 1 if brand_mentioned(answer_text, brand) else 0
                cited = 1 if domain_in_citations(citations, brand) else 0
                prominence = compute_prominence(answer_text, brand) if mentioned else 0
                domains = extract_domains(citations)

                # Sentiment & accuracy via OpenAI if available
                sent = None
                acc = None
                if secrets.openai_api_key:
                    sent = analyze_sentiment_via_openai(
                        answer_text, brand.brand_name, secrets.openai_api_key
                    )
                    acc = check_accuracy_via_openai(
                        answer_text, brand.brand_name, brand.key_claims,
                        secrets.openai_api_key,
                    )

                notes_parts = []
                if sent is None:
                    notes_parts.append("sentiment_analysis_skipped")
                if acc is None:
                    notes_parts.append("accuracy_check_skipped")

                obs = Observation(
                    platform="perplexity",
                    query_group=prompt.group,
                    query=prompt.query,
                    business_value=prompt.business_value,
                    risk_level=prompt.risk_level,
                    brand_mentioned=mentioned,
                    brand_cited=cited,
                    own_domain_cited=cited,
                    citation_domains=";".join(domains),
                    ai_answer_url_or_ref=req_id,
                    prominence_score=prominence,
                    sentiment_score=sent if sent is not None else 0,
                    accuracy_flag=acc if acc is not None else 1,
                    actionability=1 if cited else 0,
                    source_api="perplexity",
                    raw_response_ref=req_id,
                    notes=";".join(notes_parts),
                    status=Status.SUCCESS,
                )
                observations.append(obs)

                if delay_between_calls > 0:
                    time.sleep(delay_between_calls)

    # Determine overall module status
    success_count = sum(1 for o in observations if o.status == Status.SUCCESS)
    if success_count == 0 and len(observations) > 0:
        overall = Status.SKIPPED if errors == 0 else Status.FAILED
    else:
        overall = Status.SUCCESS

    return observations, ModuleResult(
        module="prompt_monitor",
        status=overall,
        reason=f"{errors} call(s) failed; skipped platforms: {skipped_platforms or 'none'}"
        if errors > 0 or skipped_platforms
        else None,
        records_produced=len(observations),
    )
