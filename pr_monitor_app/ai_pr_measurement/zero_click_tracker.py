"""
Zero-click influence measurement.

Aggregates observation data into zero-click–specific KPIs:
  - AI Answer SOV (% of queries with brand mention in AI answer)
  - AI Citation SOV (% of queries where brand domain is cited)
  - Zero-click visibility (mentions without own-domain citations)
  - Claim accuracy rate
  - Sentiment distribution

Also combines referral analytics and brand demand data for
"dark influence" estimation (brand lift not attributable to clicks).

All computations are from real stored observations.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import Observation, Status

logger = logging.getLogger(__name__)


def compute_zero_click_metrics(
    observations: list[Observation],
    referral_summary: dict | None = None,
    demand_summary: dict | None = None,
) -> dict[str, Any]:
    """Compute zero-click influence metrics from real observations."""
    valid = [o for o in observations if o.status == Status.SUCCESS]
    if not valid:
        return {"status": "SKIPPED", "reason": "No successful observations"}

    n = len(valid)

    # Core SOV metrics
    mentioned_count = sum(o.brand_mentioned for o in valid)
    cited_count = sum(o.brand_cited for o in valid)
    own_domain_cited_count = sum(o.own_domain_cited for o in valid)
    accurate_count = sum(o.accuracy_flag for o in valid)

    # Zero-click visibility: mentioned but NOT cited (influence without click opportunity)
    zero_click_mentions = sum(
        1 for o in valid if o.brand_mentioned == 1 and o.own_domain_cited == 0
    )

    # Sentiment distribution
    positive = sum(1 for o in valid if o.sentiment_score > 0)
    neutral = sum(1 for o in valid if o.sentiment_score == 0)
    negative = sum(1 for o in valid if o.sentiment_score < 0)

    # Per-platform breakdown
    platforms: dict[str, dict[str, Any]] = {}
    for o in valid:
        plat = o.platform
        if plat not in platforms:
            platforms[plat] = {
                "total": 0, "mentioned": 0, "cited": 0,
                "own_domain_cited": 0, "accurate": 0,
            }
        platforms[plat]["total"] += 1
        platforms[plat]["mentioned"] += o.brand_mentioned
        platforms[plat]["cited"] += o.brand_cited
        platforms[plat]["own_domain_cited"] += o.own_domain_cited
        platforms[plat]["accurate"] += o.accuracy_flag

    platform_metrics = {}
    for plat, counts in platforms.items():
        t = counts["total"]
        platform_metrics[plat] = {
            "total_queries": t,
            "ai_answer_sov": counts["mentioned"] / t if t > 0 else 0.0,
            "ai_citation_sov": counts["cited"] / t if t > 0 else 0.0,
            "own_domain_citation_rate": counts["own_domain_cited"] / t if t > 0 else 0.0,
            "accuracy_rate": counts["accurate"] / t if t > 0 else 0.0,
        }

    # Per-query-group breakdown
    groups: dict[str, dict[str, Any]] = {}
    for o in valid:
        g = o.query_group
        if g not in groups:
            groups[g] = {
                "total": 0, "mentioned": 0, "cited": 0,
                "own_domain_cited": 0,
            }
        groups[g]["total"] += 1
        groups[g]["mentioned"] += o.brand_mentioned
        groups[g]["cited"] += o.brand_cited
        groups[g]["own_domain_cited"] += o.own_domain_cited

    group_metrics = {}
    for g, counts in groups.items():
        t = counts["total"]
        group_metrics[g] = {
            "total_queries": t,
            "ai_answer_sov": counts["mentioned"] / t if t > 0 else 0.0,
            "ai_citation_sov": counts["cited"] / t if t > 0 else 0.0,
        }

    result: dict[str, Any] = {
        "status": "SUCCESS",
        "total_observations": n,
        "ai_answer_sov": round(mentioned_count / n, 4),
        "ai_citation_sov": round(cited_count / n, 4),
        "own_domain_citation_rate": round(own_domain_cited_count / n, 4),
        "zero_click_mention_rate": round(zero_click_mentions / n, 4),
        "claim_accuracy_rate": round(accurate_count / n, 4),
        "sentiment_distribution": {
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "positive_pct": round(positive / n, 4),
            "negative_pct": round(negative / n, 4),
        },
        "by_platform": platform_metrics,
        "by_query_group": group_metrics,
    }

    # Dark influence estimation
    # If we have both referral data and demand data, estimate the gap
    if referral_summary and referral_summary.get("status") == "SUCCESS":
        result["referral_context"] = {
            "ai_session_share": referral_summary.get("ai_session_share", 0),
            "ai_conversion_share": referral_summary.get("ai_conversion_share", 0),
            "ai_by_source": referral_summary.get("ai_by_source", {}),
        }

    if demand_summary and demand_summary.get("status") == "SUCCESS":
        brand_data = {}
        for kw, info in demand_summary.get("keywords", {}).items():
            if info.get("is_brand"):
                brand_data = info
                break
        if brand_data:
            result["brand_demand_context"] = {
                "brand_interest_trend_pct": brand_data.get("trend_pct_change", 0),
                "latest_brand_interest": brand_data.get("latest_interest", 0),
                "mean_brand_interest": brand_data.get("mean_interest", 0),
            }
            # Dark influence indicator: if AI SOV is high but click share is low,
            # the gap represents "dark influence" — brand awareness formed in
            # zero-click AI experiences
            ai_sov = result["ai_answer_sov"]
            ai_click_share = referral_summary.get("ai_session_share", 0) if referral_summary else 0
            result["dark_influence_gap"] = round(ai_sov - ai_click_share, 4)

    return result
