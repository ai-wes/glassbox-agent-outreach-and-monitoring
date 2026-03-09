from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pr_monitor_app.analytics.embeddings import EmbeddingProvider
from pr_monitor_app.logging import get_logger
from pr_monitor_app.models_analytics import EventEmbedding

log = get_logger(component="analytics.event_embeddings")


class EventEmbeddingStore:
    def __init__(self, provider: EmbeddingProvider):
        self._provider = provider

    @property
    def embedding_model(self) -> str:
        return self._provider.model_name

    def get(self, session: Session, event_id: uuid.UUID) -> list[float] | None:
        row = session.execute(
            select(EventEmbedding).where(
                EventEmbedding.event_id == event_id,
                EventEmbedding.embedding_model == self.embedding_model,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return list(row.vector)

    def upsert(self, session: Session, event_id: uuid.UUID, vector: list[float]) -> None:
        now = datetime.utcnow()
        stmt = (
            insert(EventEmbedding)
            .values(
                event_id=event_id,
                embedding_model=self.embedding_model,
                dim=len(vector),
                vector=vector,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=[EventEmbedding.event_id],
                set_={
                    "embedding_model": self.embedding_model,
                    "dim": len(vector),
                    "vector": vector,
                    "created_at": now,
                },
            )
        )
        session.execute(stmt)

    def get_or_create(self, session: Session, event_id: uuid.UUID, *, text: str) -> list[float]:
        existing = self.get(session, event_id)
        if existing is not None:
            return existing

        vectors = self._provider.embed_texts([text])
        vec = vectors[0]
        self.upsert(session, event_id, vec)
        log.info("event_embedding_created", event_id=str(event_id), model=self.embedding_model, dim=len(vec))
        return vec
