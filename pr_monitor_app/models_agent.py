from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pr_monitor_app.models import Base
from pr_monitor_app.sqltypes import JSONB, UUID


def utcnow() -> datetime:
    return datetime.utcnow()


class AgentJobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    skipped = "skipped"
    error = "error"


class SignalRecipientType(str, enum.Enum):
    user = "user"   # phone number
    group = "group" # group id


class SignalDeliveryStatus(str, enum.Enum):
    success = "success"
    error = "error"


class ClientProfile(Base):
    """Layer 3 client profile pack.

    Kept in a separate table to avoid schema migrations for the base Client table.

    voice_instructions: free-form style + tone + POV guidance
    do_not_say_json: list of phrases or claims to avoid
    default_hashtags_json: list of hashtags to append to posts (optional)
    meta_json: arbitrary additional configuration
    """

    __tablename__ = "client_profiles"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )

    voice_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    do_not_say_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    default_hashtags_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    compliance_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class ClientSignalRoute(Base):
    """Where to send Signal notifications for a given client."""

    __tablename__ = "client_signal_routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    recipient_type: Mapped[SignalRecipientType] = mapped_column(
        Enum(SignalRecipientType), nullable=False
    )
    recipient_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional override for sender account.
    from_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "recipient_type",
            "recipient_id",
            name="uq_client_signal_route_unique",
        ),
        Index("ix_client_signal_routes_client", "client_id"),
    )


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    # Topics giving context for the agent (typically top 1-2 topic ids)
    topic_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list)

    top_relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[str] = mapped_column(String(2), default="P2")

    status: Mapped[AgentJobStatus] = mapped_column(Enum(AgentJobStatus), default=AgentJobStatus.pending)
    agent_version: Mapped[int] = mapped_column(Integer, default=1)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    output_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    __table_args__ = (
        UniqueConstraint("event_id", "client_id", "agent_version", name="uq_agent_job_unique"),
        Index("ix_agent_jobs_status", "status"),
        Index("ix_agent_jobs_priority", "priority"),
        Index("ix_agent_jobs_created", "created_at"),
    )


class AgentOutput(Base):
    __tablename__ = "agent_outputs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    agent_version: Mapped[int] = mapped_column(Integer, default=1)

    model: Mapped[str] = mapped_column(String(120), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    # The main structured output JSON
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # A short digest for notifications
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("event_id", "client_id", "agent_version", name="uq_agent_output_unique"),
        Index("ix_agent_outputs_generated", "generated_at"),
    )


class SignalDelivery(Base):
    __tablename__ = "signal_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False
    )

    output_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_outputs.id", ondelete="CASCADE"), nullable=False
    )

    route_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_signal_routes.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[SignalDeliveryStatus] = mapped_column(Enum(SignalDeliveryStatus), nullable=False)

    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_signal_deliveries_client", "client_id"),
        Index("ix_signal_deliveries_attempted", "attempted_at"),
    )
