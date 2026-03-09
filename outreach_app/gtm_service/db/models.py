from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from outreach_app.gtm_service.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LeadStatus(str, Enum):
    NEW = "new"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    QUEUED = "queued"
    RESPONDED_POSITIVE = "responded_positive"
    RESPONDED_NEGATIVE = "responded_negative"
    NURTURE = "nurture"
    DISQUALIFIED = "disqualified"


class SequenceStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class MessageStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_MANUAL = "awaiting_manual"


class OutreachChannel(str, Enum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    WEBHOOK = "webhook"


class ReplyType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    WRONG_PERSON = "wrong_person"
    NOT_NOW = "not_now"
    OOO = "ooo"


class DeliveryEventType(str, Enum):
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    BLOCKED = "blocked"
    FAILED = "failed"


class ConversionEventType(str, Enum):
    MEETING_BOOKED = "meeting_booked"
    OPPORTUNITY_CREATED = "opportunity_created"


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(255), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funding_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_bio_relevance: Mapped[float] = mapped_column(Float, default=0.0)
    cloud_signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    signals: Mapped[list["Signal"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True, index=True)
    seniority: Mapped[str | None] = mapped_column(String(80), nullable=True)
    function: Mapped[str | None] = mapped_column(String(80), nullable=True)
    inferred_buying_role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    company: Mapped[Company | None] = relationship(back_populates="contacts")
    signals: Mapped[list["Signal"]] = relationship(back_populates="contact", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class Signal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "signals"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    type: Mapped[str] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    extracted_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    recency_score: Mapped[float] = mapped_column(Float, default=0.5)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    company: Mapped[Company | None] = relationship(back_populates="signals")
    contact: Mapped[Contact | None] = relationship(back_populates="signals")


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(SQLEnum(LeadStatus), default=LeadStatus.NEW, index=True)
    icp_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    persona_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    why_now: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_offer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recommended_sequence: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    last_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    company: Mapped[Company | None] = relationship(back_populates="leads")
    contact: Mapped[Contact | None] = relationship(back_populates="leads")
    scores: Mapped[list["LeadScore"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    sequences: Mapped[list["OutreachSequence"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    replies: Mapped[list["ReplyEvent"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    conversion_events: Mapped[list["ConversionEvent"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadScore(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_scores"
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    company_fit: Mapped[int] = mapped_column(Integer)
    persona_fit: Mapped[int] = mapped_column(Integer)
    trigger_strength: Mapped[int] = mapped_column(Integer)
    pain_fit: Mapped[int] = mapped_column(Integer)
    reachability: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[int] = mapped_column(Integer, index=True)
    lead_grade: Mapped[str] = mapped_column(String(8), index=True)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    lead: Mapped[Lead] = relationship(back_populates="scores")


class OutreachSequence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outreach_sequences"
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    sequence_key: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[SequenceStatus] = mapped_column(SQLEnum(SequenceStatus), default=SequenceStatus.DRAFT)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lead: Mapped[Lead] = relationship(back_populates="sequences")
    messages: Mapped[list["OutreachMessage"]] = relationship(back_populates="sequence", cascade="all, delete-orphan", order_by="OutreachMessage.step_number")
    conversion_events: Mapped[list["ConversionEvent"]] = relationship(back_populates="sequence")


class OutreachMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outreach_messages"
    sequence_id: Mapped[str] = mapped_column(ForeignKey("outreach_sequences.id", ondelete="CASCADE"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    channel: Mapped[OutreachChannel] = mapped_column(SQLEnum(OutreachChannel), index=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[MessageStatus] = mapped_column(SQLEnum(MessageStatus), default=MessageStatus.QUEUED)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sequence: Mapped[OutreachSequence] = relationship(back_populates="messages")
    replies: Mapped[list["ReplyEvent"]] = relationship(back_populates="outreach_message")
    delivery_events: Mapped[list["DeliveryEvent"]] = relationship(
        back_populates="outreach_message",
        cascade="all, delete-orphan",
        order_by="DeliveryEvent.occurred_at",
    )


class ReplyEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reply_events"
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    outreach_message_id: Mapped[str | None] = mapped_column(ForeignKey("outreach_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    reply_type: Mapped[ReplyType] = mapped_column(SQLEnum(ReplyType), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    lead: Mapped[Lead] = relationship(back_populates="replies")
    outreach_message: Mapped[OutreachMessage | None] = relationship(back_populates="replies")


class DeliveryEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "delivery_events"
    outreach_message_id: Mapped[str] = mapped_column(ForeignKey("outreach_messages.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    outreach_message: Mapped[OutreachMessage] = relationship(back_populates="delivery_events")


class ConversionEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversion_events"
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    sequence_id: Mapped[str | None] = mapped_column(ForeignKey("outreach_sequences.id", ondelete="SET NULL"), nullable=True, index=True)
    reply_event_id: Mapped[str | None] = mapped_column(ForeignKey("reply_events.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    lead: Mapped[Lead] = relationship(back_populates="conversion_events")
    sequence: Mapped[OutreachSequence | None] = relationship(back_populates="conversion_events")
