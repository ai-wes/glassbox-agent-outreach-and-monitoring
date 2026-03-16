"""Database models for the outreach system.

This module defines the SQLAlchemy ORM models used throughout the
application.  Each model corresponds to a table in the database and
includes relationships where appropriate.  UUIDs are used as primary
keys for global uniqueness.  Timestamps are generated automatically
and track both creation and last update times.  Enumerations are
represented as strings for easier migration between dialects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base


class LeadStatus(str, Enum):
    """Enumeration of possible lead states.

    The state machine for a lead drives the outreach workflow.  New
    leads start in ``NEW`` and transition through various states
    depending on enrichment, scoring, human approval and sequencing.
    """

    NEW = "NEW"
    DISCOVERED = "DISCOVERED"
    ENRICHING = "ENRICHING"
    ENRICHED = "ENRICHED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    SCORING = "SCORING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    QUEUED_FOR_OUTREACH = "QUEUED_FOR_OUTREACH"
    ACTIVE_SEQUENCE = "ACTIVE_SEQUENCE"
    PAUSED = "PAUSED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class Company(Base):
    """Company record.

    Stores normalized company information including domain and
    descriptive attributes.  A company may have many contacts and
    leads.  The domain is used as a unique identifier when available.
    """

    __tablename__ = "companies"
    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: str = Column(String(255), nullable=False)
    domain: str | None = Column(String(255), unique=True, nullable=True)
    website: str | None = Column(String(1024), nullable=True)
    headcount: int | None = Column(Integer, nullable=True)
    funding_stage: str | None = Column(String(50), nullable=True)
    industry: str | None = Column(String(255), nullable=True)
    ai_bio_relevance: float | None = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # one-to-many relationships
    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="company", cascade="all, delete-orphan")


class Contact(Base):
    """Contact record associated with a company.

    Stores personal information such as name, title and email as well
    as meta-data around the inferred buying role.  Email addresses are
    unique across contacts.  A contact may belong to one company and
    appear in many leads over time.
    """

    __tablename__ = "contacts"
    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: uuid.UUID = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    first_name: str | None = Column(String(100), nullable=True)
    last_name: str | None = Column(String(100), nullable=True)
    full_name: str | None = Column(String(255), nullable=True)
    title: str | None = Column(String(255), nullable=True)
    linkedin_url: str | None = Column(String(1024), nullable=True)
    email: str | None = Column(String(255), unique=True, nullable=True)
    seniority: str | None = Column(String(50), nullable=True)
    function: str | None = Column(String(100), nullable=True)
    inferred_buying_role: str | None = Column(String(100), nullable=True)
    email_verified: bool = Column(Boolean, default=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # relationships
    company = relationship("Company", back_populates="contacts")
    leads = relationship("Lead", back_populates="contact")


class Lead(Base):
    """Lead record capturing the intersection of a company and an optional contact.

    Leads progress through states as they are enriched, verified, scored
    and eventually sequenced for outreach.  Additional attributes track
    recommendations from the scoring engine and research agent.
    """

    __tablename__ = "leads"
    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: uuid.UUID = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    contact_id: uuid.UUID | None = Column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True)
    status: LeadStatus = Column(SAEnum(LeadStatus), default=LeadStatus.NEW, nullable=False)
    fit_score: float | None = Column(Integer, nullable=True)
    email_confidence: float | None = Column(Integer, nullable=True)
    icp_class: str | None = Column(String(50), nullable=True)
    persona_class: str | None = Column(String(50), nullable=True)
    recommended_sequence: str | None = Column(String(100), nullable=True)
    recommended_offer: str | None = Column(String(100), nullable=True)
    why_now: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_scored_at: datetime | None = Column(DateTime, nullable=True)
    # relationships
    company = relationship("Company", back_populates="leads")
    contact = relationship("Contact", back_populates="leads")

    __table_args__ = (
        UniqueConstraint("company_id", "contact_id", name="uix_lead_company_contact"),
    )


class Evidence(Base):
    """Evidence linking a data point to its source.

    Each piece of evidence records where the information was scraped
    from, the selector used to extract it, the extracted text and
    optionally a path to a screenshot.  Evidence can be attached to
    companies, contacts or leads by storing the target entity ID and
    type.
    """

    __tablename__ = "evidence"
    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: str = Column(String(50), nullable=False)
    entity_id: uuid.UUID = Column(UUID(as_uuid=True), nullable=False)
    source_url: str = Column(String(1024), nullable=False)
    selector: str | None = Column(String(255), nullable=True)
    extracted_value: str | None = Column(Text, nullable=True)
    screenshot_path: str | None = Column(String(1024), nullable=True)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)


class JobType(str, Enum):
    """Enumeration of background job types."""

    DISCOVERY = "discovery"
    ENRICHMENT = "enrichment"
    VERIFICATION = "verification"
    SCORING = "scoring"


class JobStatus(str, Enum):
    """Enumeration of job states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    """Background job record.

    Tracks the lifecycle of asynchronous tasks such as discovery,
    enrichment or verification.  The job record stores counts of
    successes and failures for reporting and audit purposes.
    """

    __tablename__ = "jobs"
    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: JobType = Column(SAEnum(JobType), nullable=False)
    status: JobStatus = Column(SAEnum(JobStatus), default=JobStatus.PENDING, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    started_at: datetime | None = Column(DateTime, nullable=True)
    finished_at: datetime | None = Column(DateTime, nullable=True)
    row_count: int | None = Column(Integer, nullable=True)
    success_count: int | None = Column(Integer, nullable=True)
    failure_count: int | None = Column(Integer, nullable=True)
