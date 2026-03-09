"""
AI Visibility Index computation.

Formula (from strategy doc):
  AI Visibility Index = weighted average of
    (0.25·Mention + 0.35·Citation + 0.15·Prominence_norm + 0.15·Accuracy + 0.10·Sentiment_norm)

Weighted by:
  (a) query business_value
  (b) query risk_level
  (c) platform audience share

All inputs must be real Observation records from the database.
If no successful observations exist, returns SKIPPED.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import PlatformWeights
from .models import Observation, Status, VisibilityIndexResult

logger = logging.getLogger(__name__)

# Index component weights (from strategy doc)
W_MENTION = 0.25
W_CITATION = 0.35
W_PROMINENCE = 0.15
W_ACCURACY = 0.15
W_SENTIMENT = 0.10


def _normalize_prominence(score: int) -> float:
    """Normalize 0-3 to 0-1."""
    return min(score / 3.0, 1.0)


def _normalize_sentiment(score: int) -> float:
    """Normalize -1..+1 to 0..1 for index computation."""
    return (score + 1.0) / 2.0


def _platform_weight(platform: str, weights: PlatformWeights) -> float:
    mapping = {
        "google": weights.google,
        "bing": weights.bing,
        "openai": weights.openai,
        "perplexity": weights.perplexity,
    }
    return mapping.get(platform.lower(), weights.other)


def compute_observation_score(obs: Observation, platform_weights: PlatformWeights) -> float:
    """Compute the raw index score for a single observation (before weighting)."""
    raw = (
        W_MENTION * obs.brand_mentioned
        + W_CITATION * obs.brand_cited
        + W_PROMINENCE * _normalize_prominence(obs.prominence_score)
        + W_ACCURACY * obs.accuracy_flag
        + W_SENTIMENT * _normalize_sentiment(obs.sentiment_score)
    )
    return raw


def compute_weighted_score(obs: Observation, platform_weights: PlatformWeights) -> float:
    """Compute the business-weighted index score for a single observation."""
    raw = compute_observation_score(obs, platform_weights)
    bv = obs.business_value
    risk = obs.risk_level
    pw = _platform_weight(obs.platform, platform_weights)
    # Combined weight: product of normalized factors
    combined = bv * (0.5 + 0.5 * risk) * pw  # risk adds 0-50% extra weight
    return raw * combined


def compute_visibility_index(
    observations: list[Observation],
    platform_weights: PlatformWeights,
    scope: str = "all",
) -> VisibilityIndexResult:
    """Compute the AI Visibility Index from a set of real observations."""
    # Filter to SUCCESS only
    valid = [o for o in observations if o.status == Status.SUCCESS]
    if not valid:
        return VisibilityIndexResult(
            scope=scope,
            status=Status.SKIPPED,
            reason="No successful observations to compute index from",
        )

    n = len(valid)
    sum_mention = sum(o.brand_mentioned for o in valid)
    sum_cited = sum(o.brand_cited for o in valid)
    sum_prominence = sum(_normalize_prominence(o.prominence_score) for o in valid)
    sum_accuracy = sum(o.accuracy_flag for o in valid)
    sum_sentiment = sum(_normalize_sentiment(o.sentiment_score) for o in valid)

    ai_answer_sov = sum_mention / n
    ai_citation_sov = sum_cited / n
    mean_prominence = sum_prominence / n
    mean_accuracy = sum_accuracy / n
    mean_sentiment = sum_sentiment / n

    # Unweighted index (simple average of component scores)
    raw_scores = [compute_observation_score(o, platform_weights) for o in valid]
    visibility_index = sum(raw_scores) / n

    # Weighted index (business-value × risk × platform weighted)
    weighted_scores = [compute_weighted_score(o, platform_weights) for o in valid]
    total_weight = sum(
        o.business_value * (0.5 + 0.5 * o.risk_level) * _platform_weight(o.platform, platform_weights)
        for o in valid
    )
    weighted_visibility_index = sum(weighted_scores) / total_weight if total_weight > 0 else 0.0

    return VisibilityIndexResult(
        scope=scope,
        total_observations=n,
        ai_answer_sov=round(ai_answer_sov, 4),
        ai_citation_sov=round(ai_citation_sov, 4),
        mean_prominence=round(mean_prominence, 4),
        mean_accuracy=round(mean_accuracy, 4),
        mean_sentiment=round(mean_sentiment, 4),
        visibility_index=round(visibility_index, 4),
        weighted_visibility_index=round(weighted_visibility_index, 4),
        status=Status.SUCCESS,
    )


def compute_index_by_scope(
    observations: list[Observation],
    platform_weights: PlatformWeights,
) -> list[VisibilityIndexResult]:
    """Compute the index for overall, per-platform, and per-query-group scopes."""
    results: list[VisibilityIndexResult] = []

    # Overall
    results.append(compute_visibility_index(observations, platform_weights, scope="all"))

    # Per platform
    platforms = set(o.platform for o in observations if o.status == Status.SUCCESS)
    for plat in sorted(platforms):
        plat_obs = [o for o in observations if o.platform == plat]
        results.append(compute_visibility_index(plat_obs, platform_weights, scope=f"platform:{plat}"))

    # Per query group
    groups = set(o.query_group for o in observations if o.status == Status.SUCCESS)
    for grp in sorted(groups):
        grp_obs = [o for o in observations if o.query_group == grp]
        results.append(compute_visibility_index(grp_obs, platform_weights, scope=f"group:{grp}"))

    return results
