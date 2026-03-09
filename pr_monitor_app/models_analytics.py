from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pr_monitor_app.models import Base
from pr_monitor_app.sqltypes import JSONB, UUID


def utcnow() -> datetime:
    return datetime.utcnow()


class AnalysisStatus(str, enum.Enum):
    success = "success"
    error = "error"


class EventAnalysis(Base):
    """One row per Event describing deterministic analytics outputs.

    This is not "agentic" content; it is structured data produced automatically.
    """

    __tablename__ = "event_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    # Hash of the text used to generate the analysis. When unchanged, we can skip recompute.
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Sentiment
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Framing taxonomy (list of {frame: str, score: float, matches: int})
    frames_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    status: Mapped[AnalysisStatus] = mapped_column(Enum(AnalysisStatus), nullable=False, default=AnalysisStatus.success)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        Index("ix_event_analyses_event_id", "event_id"),
        Index("ix_event_analyses_analyzed_at", "analyzed_at"),
    )


class EventEmbedding(Base):
    __tablename__ = "event_embeddings"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), primary_key=True
    )

    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        Index("ix_event_embeddings_model", "embedding_model"),
    )


class TopicEmbedding(Base):
    __tablename__ = "topic_embeddings"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_lenses.id", ondelete="CASCADE"), primary_key=True
    )

    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        Index("ix_topic_embeddings_model", "embedding_model"),
    )


class EventTopicScore(Base):
    """Per-event per-topic deterministic relevance score.

    A topic belongs to exactly one client in this data model; client_id is denormalized here for fast filtering.
    """

    __tablename__ = "event_topic_scores"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_lenses.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    keyword_score: Mapped[float] = mapped_column(Float, nullable=False)
    embedding_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    reasons_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_event_topic_scores_client", "client_id"),
        Index("ix_event_topic_scores_topic", "topic_id"),
        Index("ix_event_topic_scores_score", "relevance_score"),
    )


class DailyTopicMetric(Base):
    __tablename__ = "daily_topic_metrics"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_lenses.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_relevance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    top_frames_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        Index("ix_daily_topic_metrics_day", "day"),
        Index("ix_daily_topic_metrics_client_day", "client_id", "day"),
    )
