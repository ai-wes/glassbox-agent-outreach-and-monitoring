from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pr_monitor_app.config import settings


@dataclass(frozen=True)
class RelevanceResult:
    relevance_score: float
    keyword_score: float
    embedding_score: float | None
    reasons: dict[str, Any]


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("vector_dim_mismatch")
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _map_embedding_similarity(cos: float) -> float:
    """Map cosine similarity to 0..1 with conservative thresholds.

    Many embedding spaces yield cosine similarities clustered ~0.1-0.4 for weak matches.
    We map:
      cos <= 0.10  -> 0.0
      cos >= 0.80  -> 1.0
    linearly in between, then clamp.
    """
    return _clamp01((cos - 0.10) / 0.70)


def keyword_score_for_topic(*, text: str, title: str, topic_query: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    text_l = (text or "").lower()
    title_l = (title or "").lower()

    keywords = [str(x).strip() for x in (topic_query.get("keywords") or []) if str(x).strip()]
    phrases = [str(x).strip() for x in (topic_query.get("phrases") or []) if str(x).strip()]
    exclude = [str(x).strip() for x in (topic_query.get("exclude_keywords") or []) if str(x).strip()]

    matched_keywords: list[str] = []
    matched_phrases: list[str] = []
    matched_in_title: list[str] = []

    # Exclusions: if any exclude keyword appears, hard-zero the keyword score.
    for ex in exclude:
        if ex.lower() in text_l or ex.lower() in title_l:
            return 0.0, {"excluded_by": ex}

    kw_set = list(dict.fromkeys([k.lower() for k in keywords]))
    ph_set = list(dict.fromkeys([p.lower() for p in phrases]))

    for kw in kw_set:
        if kw and kw in text_l:
            matched_keywords.append(kw)
        if kw and kw in title_l:
            matched_in_title.append(kw)

    for ph in ph_set:
        if ph and ph in text_l:
            matched_phrases.append(ph)
        if ph and ph in title_l:
            matched_in_title.append(ph)

    # Base ratio
    denom = max(1.0, float(len(kw_set) + 1.8 * len(ph_set)))
    base = (len(matched_keywords) + 1.8 * len(matched_phrases)) / denom

    # Title bonus encourages reacting to explicitly topical headlines.
    title_bonus = min(0.25, 0.05 * len(set(matched_in_title)))
    score = _clamp01(float(base + title_bonus))

    reasons = {
        "matched_keywords": matched_keywords[:25],
        "matched_phrases": matched_phrases[:25],
        "matched_in_title": list(dict.fromkeys(matched_in_title))[:25],
        "exclude_keywords": exclude[:25],
    }
    return score, reasons


def relevance_for_topic(
    *,
    text: str,
    title: str,
    topic_query: dict[str, Any],
    event_embedding: list[float] | None,
    topic_embedding: list[float] | None,
) -> RelevanceResult:
    kw_score, kw_reasons = keyword_score_for_topic(text=text, title=title, topic_query=topic_query)

    emb_score_mapped: float | None = None
    emb_cos: float | None = None

    if event_embedding is not None and topic_embedding is not None:
        emb_cos = cosine_similarity(event_embedding, topic_embedding)
        emb_score_mapped = _map_embedding_similarity(emb_cos)

    # Weighting and normalization
    kw_w = float(settings.analytics_keyword_weight)
    emb_w = float(settings.analytics_embedding_weight)

    if emb_score_mapped is None:
        # keyword-only
        relevance = kw_score
        used_kw_w, used_emb_w = 1.0, 0.0
    else:
        total = max(1e-9, kw_w + emb_w)
        used_kw_w = kw_w / total
        used_emb_w = emb_w / total
        relevance = used_kw_w * kw_score + used_emb_w * emb_score_mapped

    reasons: dict[str, Any] = {
        "keyword": kw_reasons,
        "weights": {"keyword": used_kw_w, "embedding": used_emb_w},
    }
    if emb_cos is not None:
        reasons["embedding"] = {"cosine": emb_cos, "mapped": emb_score_mapped}

    return RelevanceResult(
        relevance_score=float(_clamp01(relevance)),
        keyword_score=float(_clamp01(kw_score)),
        embedding_score=float(emb_score_mapped) if emb_score_mapped is not None else None,
        reasons=reasons,
    )
