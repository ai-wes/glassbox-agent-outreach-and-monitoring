from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.embedding import cosine_sim
from pr_monitor_app.models import AlertTier, Client, ClientEvent, Event, RawEvent, Source, TopicLens
from pr_monitor_app.pipeline.narrative_shift import narrative_shift_score
from pr_monitor_app.utils.text import keyword_hits, normalize_text

log = structlog.get_logger(__name__)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _flatten_strings(obj: Any) -> list[str]:
    out: list[str] = []
    if obj is None:
        return out
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            out.append(s)
        return out
    if isinstance(obj, (int, float, bool)):
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten_strings(k))
            out.extend(_flatten_strings(v))
        return out
    if isinstance(obj, list) or isinstance(obj, tuple) or isinstance(obj, set):
        for v in obj:
            out.extend(_flatten_strings(v))
        return out
    return out


def _velocity(event: Event) -> float:
    now = datetime.now(timezone.utc)
    dt = event.published_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = max(0.1, (now - dt).total_seconds() / 3600.0)
    stats = event.engagement_stats or {}
    reactions = float(stats.get("reaction_count") or 0.0)
    comments = float(stats.get("comment_count") or 0.0)

    if reactions == 0.0 and comments == 0.0:
        # recency-only decay for sources without stats
        import math

        return float(math.exp(-age_hours / 12.0))

    raw = (reactions + 2.0 * comments) / age_hours
    import math

    return _clamp01(1.0 - math.exp(-raw / 10.0))


def _audience_impact(client: Client, event_text: str, topic_relevance: float) -> tuple[float, dict[str, Any]]:
    pillars = client.messaging_pillars or []
    pillar_hits = keyword_hits(event_text, pillars)
    pillar_score = 0.0 if not pillars else min(1.0, len(pillar_hits) / max(1, len(pillars)))

    audience_terms = _flatten_strings(client.audience_profile)
    # keep it sane; only treat longer phrases as terms
    audience_terms = [t for t in audience_terms if len(t) >= 4][:200]
    aud_hits = keyword_hits(event_text, audience_terms)
    audience_score = 0.0 if not audience_terms else min(1.0, len(aud_hits) / max(1, len(audience_terms)))

    score = _clamp01(0.6 * topic_relevance + 0.4 * max(pillar_score, audience_score))
    diag = {"pillar_hits": pillar_hits[:10], "audience_hits": aud_hits[:10], "pillar_score": pillar_score, "audience_score": audience_score}
    return score, diag


def _tier(
    *,
    composite: float,
    direct_mention: bool,
    risk_hit: bool,
    source_authority: float,
    velocity: float,
) -> AlertTier:
    if direct_mention or risk_hit:
        return AlertTier.P0
    if composite >= settings.p0_threshold and source_authority >= 0.8 and velocity >= 0.6:
        return AlertTier.P0
    if composite >= settings.p1_threshold and velocity >= 0.45:
        return AlertTier.P1
    if composite >= settings.p2_threshold:
        return AlertTier.P2
    return AlertTier.P3


async def score_new_events(session: AsyncSession, *, per_event_topic_limit: int = 2, min_relevance: float = 0.35) -> dict[str, Any]:
    """
    For each new Event (not yet mapped to any ClientEvent), compute per-client/topic scores and create ClientEvent rows.

    Strategy:
      - For each client: compute similarity against all topics.
      - Keep the top N topics with similarity >= min_relevance.
    """
    # select events with no client_events yet
    subq = select(ClientEvent.event_id).subquery()
    events = (await session.execute(select(Event).where(~Event.id.in_(select(subq.c.event_id))).order_by(Event.published_at.asc()).limit(500))).scalars().all()
    if not events:
        return {"scored_events": 0, "client_event_rows": 0}

    clients = (await session.execute(select(Client))).scalars().all()
    topics = (await session.execute(select(TopicLens))).scalars().all()

    # pre-index topics per client
    topics_by_client: dict[Any, list[TopicLens]] = {}
    for t in topics:
        topics_by_client.setdefault(t.client_id, []).append(t)

    # source authority needs join via RawEvent->Source; fetch in batch.
    # Map raw_event_id -> authority_score
    raw_ids = [e.raw_event_id for e in events if e.raw_event_id is not None]
    authority_by_raw: dict[Any, float] = {}
    if raw_ids:
        rows = (
            await session.execute(
                select(RawEvent.id, Source.authority_score)
                .join(Source, Source.id == RawEvent.source_id)
                .where(RawEvent.id.in_(raw_ids))
            )
        ).all()
        authority_by_raw = {rid: float(auth or 0.5) for rid, auth in rows}

    ce_rows = 0
    scored_events = 0

    for ev in events:
        if not ev.embedding:
            continue
        ev_text = ev.raw_text or ""
        scored_events += 1

        for client in clients:
            client_topics = topics_by_client.get(client.id, [])
            if not client_topics:
                continue

            # compute topic relevance using embedding similarity plus keyword boost
            sims: list[tuple[TopicLens, float]] = []
            for t in client_topics:
                emb_rel = 0.0
                if t.embedding:
                    sim = cosine_sim(ev.embedding, t.embedding)
                    emb_rel = _clamp01(max(0.0, sim))

                # Keyword relevance helps when embedding providers are unavailable/noisy.
                topic_terms = list(t.keywords or [])
                if t.name:
                    topic_terms.append(t.name)
                kw_hits = keyword_hits(ev_text, topic_terms)
                if kw_hits:
                    # One strong lexical hit is enough to consider a topic candidate.
                    # Additional hits increase confidence gradually.
                    kw_rel = _clamp01(0.35 + 0.15 * (len(kw_hits) - 1))
                else:
                    kw_rel = 0.0

                topic_rel = max(emb_rel, kw_rel)
                sims.append((t, topic_rel))

            sims.sort(key=lambda x: x[1], reverse=True)
            picked = [(t, s) for (t, s) in sims[: max(1, per_event_topic_limit)] if s >= min_relevance]
            if not picked:
                continue

            # common signals
            direct_mention = client.name.lower() in (ev_text or "").lower()
            competitor_list = (client.competitors or [])
            risk_list = (client.risk_keywords or [])

            for t, topic_rel in picked:
                competitors = list(set((t.competitor_overrides or []) + competitor_list))
                risks = list(set((t.risk_flags or []) + risk_list))

                competitor_hits = keyword_hits(ev_text, competitors)
                risk_hits = keyword_hits(ev_text, risks)
                competitor_hit = len(competitor_hits) > 0
                risk_hit = len(risk_hits) > 0

                audience, aud_diag = _audience_impact(client, ev_text, topic_rel)
                velocity = _velocity(ev)
                source_auth = float(authority_by_raw.get(ev.raw_event_id) or 0.5)

                narr, narr_diag = await narrative_shift_score(
                    session,
                    client_id=client.id,
                    topic_id=t.id,
                    event_embedding=ev.embedding,
                    event_sentiment=ev.sentiment,
                    competitor_hit=competitor_hit,
                )

                composite = _clamp01(
                    (topic_rel * 0.35)
                    + (audience * 0.20)
                    + (velocity * 0.15)
                    + (source_auth * 0.15)
                    + (narr * 0.15)
                )

                tier = _tier(
                    composite=composite,
                    direct_mention=direct_mention,
                    risk_hit=risk_hit,
                    source_authority=source_auth,
                    velocity=velocity,
                )

                scores = {
                    "TopicRelevance": topic_rel,
                    "AudienceImpact": audience,
                    "Velocity": velocity,
                    "SourceAuthority": source_auth,
                    "NarrativeShiftScore": narr,
                    "diagnostics": {
                        "direct_mention": direct_mention,
                        "competitor_hits": competitor_hits[:10],
                        "risk_hits": risk_hits[:10],
                        "audience": aud_diag,
                        "narrative": narr_diag,
                    },
                }

                rationale_bits = []
                if direct_mention:
                    rationale_bits.append("Direct client mention detected.")
                if competitor_hit:
                    rationale_bits.append(f"Competitor mentioned: {', '.join(competitor_hits[:3])}.")
                if risk_hit:
                    rationale_bits.append(f"Risk keyword hit: {', '.join(risk_hits[:3])}.")
                rationale_bits.append(f"Topic match '{t.name}' (sim={topic_rel:.2f}).")
                rationale_bits.append(f"Composite={composite:.2f}, Velocity={velocity:.2f}, Authority={source_auth:.2f}.")

                ce = ClientEvent(
                    client_id=client.id,
                    event_id=ev.id,
                    topic_id=t.id,
                    scores=scores,
                    composite_score=composite,
                    tier=tier,
                    rationale=" ".join(rationale_bits),
                )
                session.add(ce)
                ce_rows += 1

    log.info("scoring_done", events=scored_events, client_events=ce_rows)
    return {"scored_events": scored_events, "client_event_rows": ce_rows}
