from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.embedding import cosine_sim
from pr_monitor_app.models import ClientEvent, Event
from pr_monitor_app.config import settings


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


async def narrative_shift_score(
    session: AsyncSession,
    *,
    client_id,
    topic_id,
    event_embedding: list[float] | None,
    event_sentiment: float,
    competitor_hit: bool,
) -> tuple[float, dict[str, Any]]:
    """
    Narrative shift signals:
      - Novelty vs recent history (1 - max similarity).
      - Sentiment shift (abs current - mean recent).
      - Competitor mention boost.
    """
    if not event_embedding:
        return 0.3, {"reason": "missing_embedding"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.recent_history_days)

    rows = (
        await session.execute(
            select(Event.embedding, Event.sentiment)
            .join(ClientEvent, ClientEvent.event_id == Event.id)
            .where(
                ClientEvent.client_id == client_id,
                ClientEvent.topic_id == topic_id,
                Event.published_at >= cutoff,
            )
            .limit(200)
        )
    ).all()

    embeddings: list[list[float]] = []
    sentiments: list[float] = []
    for emb, sent in rows:
        if emb:
            embeddings.append(emb)
        sentiments.append(float(sent or 0.0))

    if embeddings:
        max_sim = max(cosine_sim(event_embedding, e) for e in embeddings)
        novelty = _clamp01(1.0 - max_sim)
    else:
        max_sim = None
        novelty = 0.5  # cold start

    if sentiments:
        mean_sent = float(np.mean(np.asarray(sentiments, dtype=np.float32)))
        sent_shift = _clamp01(abs(float(event_sentiment) - mean_sent) / 0.8)
    else:
        mean_sent = None
        sent_shift = 0.25

    comp = 1.0 if competitor_hit else 0.0

    score = _clamp01(0.6 * novelty + 0.3 * sent_shift + 0.1 * comp)
    diag = {"max_sim": max_sim, "novelty": novelty, "mean_sent": mean_sent, "sent_shift": sent_shift, "competitor_hit": competitor_hit}
    return score, diag
