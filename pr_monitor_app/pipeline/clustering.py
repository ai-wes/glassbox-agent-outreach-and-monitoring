from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.embedding import cosine_sim
from pr_monitor_app.models import Event, EventCluster, EventClusterMap
from pr_monitor_app.config import settings

log = structlog.get_logger(__name__)


def _window_bounds(dt: datetime) -> tuple[datetime, datetime]:
    dt_utc = dt.astimezone(timezone.utc)
    ws = dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    we = ws + timedelta(hours=settings.cluster_window_hours)
    return ws, we


def _normalize(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    if n == 0:
        return vec
    return vec / n


async def cluster_new_events(session: AsyncSession, *, limit: int = 500) -> dict[str, Any]:
    """
    Assign recent events to clusters (daily bucket by UTC date), deduping by embedding similarity.
    """
    # Events not mapped to any cluster
    subq = select(EventClusterMap.event_id).subquery()
    events = (
        await session.execute(
            select(Event)
            .where(~Event.id.in_(select(subq.c.event_id)))
            .order_by(Event.published_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    if not events:
        return {"clustered": 0, "new_clusters": 0}

    clustered = 0
    new_clusters = 0

    for ev in events:
        if not ev.embedding:
            continue

        ws, we = _window_bounds(ev.published_at)
        clusters = (
            await session.execute(
                select(EventCluster).where(and_(EventCluster.window_start == ws, EventCluster.window_end == we))
            )
        ).scalars().all()

        # find best cluster
        best: Optional[EventCluster] = None
        best_sim = 0.0
        for c in clusters:
            if not c.centroid_embedding:
                continue
            s = cosine_sim(ev.embedding, c.centroid_embedding)
            if s > best_sim:
                best_sim = s
                best = c

        if best is None or best_sim < settings.cluster_similarity_threshold:
            # create a new cluster with this event as representative
            c = EventCluster(
                window_start=ws,
                window_end=we,
                centroid_embedding=ev.embedding,
                representative_event_id=ev.id,
                cluster_size=1,
            )
            session.add(c)
            await session.flush()  # get id
            session.add(EventClusterMap(event_id=ev.id, cluster_id=c.id))
            new_clusters += 1
            clustered += 1
            continue

        # attach to existing cluster
        session.add(EventClusterMap(event_id=ev.id, cluster_id=best.id))

        # update centroid incrementally
        try:
            old = np.asarray(best.centroid_embedding, dtype=np.float32)
            newv = np.asarray(ev.embedding, dtype=np.float32)
            # weighted mean by cluster_size
            k = max(1, int(best.cluster_size))
            centroid = _normalize((old * k + newv) / float(k + 1))
            best.centroid_embedding = centroid.astype(np.float32).tolist()
            best.cluster_size = k + 1
        except Exception:
            # fail safe: do not block clustering if centroid update fails
            pass

        clustered += 1

    log.info("clustering_done", clustered=clustered, new_clusters=new_clusters)
    return {"clustered": clustered, "new_clusters": new_clusters}
