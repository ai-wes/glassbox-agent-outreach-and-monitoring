from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pr_monitor_app.models import Base
from pr_monitor_app.sqltypes import JSONB, UUID


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OnboardingStatus(str, enum.Enum):
    draft = "draft"
    resolving_company = "resolving_company"
    awaiting_company_confirmation = "awaiting_company_confirmation"
    enriching_company = "enriching_company"
    generating_blueprint = "generating_blueprint"
    awaiting_user_review = "awaiting_user_review"
    approved = "approved"
    materialized = "materialized"
    rejected = "rejected"
    error = "error"


class CategoryProposalStatus(str, enum.Enum):
    proposed = "proposed"
    approved = "approved"
    removed = "removed"
    rejected = "rejected"


class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"
    __table_args__ = (
        Index("ix_onboarding_sessions_status", "status"),
        Index("ix_onboarding_sessions_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name_input: Mapped[str] = mapped_column(String(200), nullable=False)
    website_input: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    linkedin_url_input: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    short_description_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[OnboardingStatus] = mapped_column(
        String(64),
        default=OnboardingStatus.draft.value,
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    final_client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_intake_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class CompanyResolutionCandidate(Base):
    __tablename__ = "company_resolution_candidates"
    __table_args__ = (
        Index("ix_resolution_candidates_session", "onboarding_session_id"),
        Index("ix_resolution_candidates_selected", "onboarding_session_id", "is_selected"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)


class ResolvedCompanyProfile(Base):
    __tablename__ = "resolved_company_profiles"
    __table_args__ = (
        UniqueConstraint("onboarding_session_id", name="uq_resolved_company_profiles_session"),
        Index("ix_resolved_company_profiles_name", "canonical_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    subindustry: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    products_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    executives_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    competitors_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    channels_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    themes_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_themes_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    opportunity_themes_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    source_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class MonitoringBlueprintProposal(Base):
    __tablename__ = "monitoring_blueprint_proposals"
    __table_args__ = (
        Index("ix_monitoring_blueprints_session", "onboarding_session_id"),
        UniqueConstraint("onboarding_session_id", "proposal_version", name="uq_blueprint_session_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    onboarding_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolved_company_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    proposal_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class MonitoringCategoryProposal(Base):
    __tablename__ = "monitoring_category_proposals"
    __table_args__ = (
        Index("ix_monitoring_category_blueprint", "blueprint_id"),
        Index("ix_monitoring_category_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_blueprint_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    recommended_sources_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    entities_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    keywords_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    negative_keywords_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    sample_queries_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=CategoryProposalStatus.proposed.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class BlueprintReviewDecision(Base):
    __tablename__ = "blueprint_review_decisions"
    __table_args__ = (
        Index("ix_blueprint_review_blueprint", "blueprint_id"),
        Index("ix_blueprint_review_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_blueprint_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
