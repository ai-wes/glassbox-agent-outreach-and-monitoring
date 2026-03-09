from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pr_monitor_app.analytics.embeddings import EmbeddingProvider
from pr_monitor_app.config import settings
from pr_monitor_app.logging import get_logger
from pr_monitor_app.models import TopicLens
from pr_monitor_app.models_analytics import TopicEmbedding
from pr_monitor_app.utils.text import normalize_text

log = get_logger(component="analytics.topic_embeddings")


def topic_text_for_embedding(topic: TopicLens) -> str:
    """Build the text used to embed a Topic.

    We keep this deterministic and stable so embeddings don't churn.
    """
    q: dict[str, Any] = topic.query_json or {}
    parts: list[str] = [topic.name]

    desc = q.get("description")
    if isinstance(desc, str) and desc.strip():
        parts.append(desc.strip())

    keywords = q.get("keywords") or []
    phrases = q.get("phrases") or []
    if keywords:
        parts.append("Keywords: " + ", ".join(str(x) for x in keywords[:40]))
    if phrases:
        parts.append("Phrases: " + ", ".join(str(x) for x in phrases[:40]))

    return normalize_text(" | ".join([p for p in parts if p]))


@dataclass(frozen=True)
class TopicEmbeddingResult:
    topic_id: uuid.UUID
    vector: list[float]


class TopicEmbeddingStore:
    """Fetch and maintain topic embeddings in Postgres.

    We do NOT rely on pgvector to keep deployment simple; embeddings are stored as JSON arrays.
    """

    def __init__(self, provider: EmbeddingProvider):
        self._provider = provider

    @property
    def embedding_model(self) -> str:
        return self._provider.model_name

    def get_embeddings(self, session: Session, topic_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[float]]:
        if not topic_ids:
            return {}
        rows = (
            session.execute(
                select(TopicEmbedding).where(
                    TopicEmbedding.topic_id.in_(topic_ids),
                    TopicEmbedding.embedding_model == self.embedding_model,
                )
            )
            .scalars()
            .all()
        )
        return {r.topic_id: list(r.vector) for r in rows}

    def ensure_embeddings(self, session: Session, topics: list[TopicLens]) -> dict[uuid.UUID, list[float]]:
        """Ensure embeddings exist and are reasonably fresh, computing missing/stale ones.

        Returns dict topic_id -> vector.
        """
        if not topics:
            return {}

        topic_ids = [t.id for t in topics]
        existing = self.get_embeddings(session, topic_ids)

        ttl = timedelta(hours=int(settings.analytics_recompute_topic_embeddings_hours))
        now = datetime.utcnow()

        # Identify stale/missing
        to_compute: list[TopicLens] = []
        if ttl.total_seconds() <= 0:
            ttl = timedelta(days=3650)

        if existing:
            # Need updated_at to check staleness; fetch rows.
            rows = (
                session.execute(
                    select(TopicEmbedding).where(
                        TopicEmbedding.topic_id.in_(topic_ids),
                        TopicEmbedding.embedding_model == self.embedding_model,
                    )
                )
                .scalars()
                .all()
            )
            row_map = {r.topic_id: r for r in rows}
        else:
            row_map = {}

        for t in topics:
            row = row_map.get(t.id)
            if row is None:
                to_compute.append(t)
                continue
            if row.updated_at is None or (row.updated_at + ttl) < now:
                to_compute.append(t)

        if not to_compute:
            return existing

        texts = [topic_text_for_embedding(t) for t in to_compute]
        vectors = self._provider.embed_texts(texts)

        for t, vec in zip(to_compute, vectors):
            dim = len(vec)
            stmt = (
                insert(TopicEmbedding)
                .values(
                    topic_id=t.id,
                    embedding_model=self.embedding_model,
                    dim=dim,
                    vector=vec,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[TopicEmbedding.topic_id],
                    set_={
                        "embedding_model": self.embedding_model,
                        "dim": dim,
                        "vector": vec,
                        "updated_at": now,
                    },
                )
            )
            session.execute(stmt)

        # Re-fetch for return
        session.flush()
        merged = self.get_embeddings(session, topic_ids)
        log.info("topic_embeddings_updated", computed=len(to_compute), total=len(topics), model=self.embedding_model)
        return merged
