from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from glassbox_radar.enums import (
    EvidenceType,
    MilestoneType,
    OpportunityStatus,
    PipelineRunStatus,
    PublicationStatus,
    SignalType,
    SourceType,
)


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    hq: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_raise_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_raise_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    runway_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_investors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    board_members: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    therapeutic_areas: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warm_intro_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rss_feeds: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    programs: Mapped[list["Program"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    signals: Mapped[list["Signal"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Program(TimestampMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("company_id", "asset_name", "target", name="uq_program_company_asset_target"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mechanism: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    indication: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    key_terms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    lead_program_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estimated_next_milestone: Mapped[MilestoneType | None] = mapped_column(Enum(MilestoneType), nullable=True)
    estimated_milestone_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    milestone_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_radar_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="programs")
    signals: Mapped[list["Signal"]] = relationship(back_populates="program", cascade="all, delete-orphan")
    evidence_nodes: Mapped[list["EvidenceNode"]] = relationship(back_populates="program", cascade="all, delete-orphan")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="program", cascade="all, delete-orphan")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("company_id", "email", name="uq_contact_company_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warm_intro_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="contacts")


class Signal(TimestampMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_signal_content_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id: Mapped[str | None] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), nullable=True, index=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    signal_type: Mapped[SignalType] = mapped_column(Enum(SignalType), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    milestone_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="signals")
    program: Mapped["Program | None"] = relationship(back_populates="signals")
    evidence_nodes: Mapped[list["EvidenceNode"]] = relationship(back_populates="source_signal", cascade="all, delete-orphan")


class EvidenceNode(TimestampMixin, Base):
    __tablename__ = "evidence_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    program_id: Mapped[str] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_signal_id: Mapped[str | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"), nullable=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), nullable=False)
    model_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    human_relevance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    orthogonality_tag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replication_signal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    publication_status: Mapped[PublicationStatus] = mapped_column(Enum(PublicationStatus), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    extracted_from: Mapped[str | None] = mapped_column(String(255), nullable=True)

    program: Mapped["Program"] = relationship(back_populates="evidence_nodes")
    source_signal: Mapped["Signal | None"] = relationship(back_populates="evidence_nodes")


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("program_id", name="uq_opportunity_program"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    radar_score: Mapped[float] = mapped_column(Float, nullable=False)
    milestone_score: Mapped[float] = mapped_column(Float, nullable=False)
    fragility_score: Mapped[float] = mapped_column(Float, nullable=False)
    capital_score: Mapped[float] = mapped_column(Float, nullable=False)
    reachability_score: Mapped[float] = mapped_column(Float, nullable=False)
    milestone_type: Mapped[MilestoneType] = mapped_column(Enum(MilestoneType), nullable=False, default=MilestoneType.UNKNOWN)
    milestone_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    milestone_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    milestone_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    primary_buyer_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outreach_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    capital_exposure_band: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus), default=OpportunityStatus.DETECTED, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dossier_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sheet_row_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_exported_to_sheet_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship(back_populates="opportunities")
    program: Mapped["Program"] = relationship(back_populates="opportunities")


class PipelineRun(TimestampMixin, Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[PipelineRunStatus] = mapped_column(Enum(PipelineRunStatus), nullable=False, default=PipelineRunStatus.STARTED)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
