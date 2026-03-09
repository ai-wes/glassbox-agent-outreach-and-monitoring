from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from outreach_app.gtm_service.schemas.common import ORMModel


class RawSignalInput(BaseModel):
    type: str
    source: str
    raw_text: str
    occurred_at: datetime | None = None
    source_url: HttpUrl | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CandidateContactInput(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    title: str | None = None
    linkedin_url: HttpUrl | None = None
    email: str | None = None
    seniority: str | None = None
    function: str | None = None
    inferred_buying_role: str | None = None
    email_verified: bool = False


class CandidateCompanyInput(BaseModel):
    name: str
    domain: str | None = None
    website: HttpUrl | None = None
    headcount: int | None = None
    funding_stage: str | None = None
    industry: str | None = None
    ai_bio_relevance: float | None = None
    cloud_signals: dict[str, Any] = Field(default_factory=dict)
    source_urls: list[str] = Field(default_factory=list)


class CandidateIngestRequest(BaseModel):
    company: CandidateCompanyInput
    contact: CandidateContactInput | None = None
    signals: list[RawSignalInput] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    raw_page_urls: list[HttpUrl] = Field(default_factory=list)
    source: str = "manual"
    auto_queue: bool = False


class CSVImportResponse(BaseModel):
    imported: int
    lead_ids: list[str]


class SignalRead(ORMModel):
    id: str
    type: str
    source: str
    source_url: str | None
    occurred_at: datetime | None
    extracted_summary: str | None
    confidence: float
    recency_score: float
    metadata_json: dict[str, Any]


class CompanyRead(ORMModel):
    id: str
    name: str
    domain: str | None
    website: str | None
    headcount: int | None
    funding_stage: str | None
    industry: str | None
    ai_bio_relevance: float
    cloud_signals: dict[str, Any]
    source_urls: list[str]


class ContactRead(ORMModel):
    id: str
    company_id: str | None
    first_name: str | None
    last_name: str | None
    full_name: str | None
    title: str | None
    linkedin_url: str | None
    email: str | None
    seniority: str | None
    function: str | None
    inferred_buying_role: str | None
    email_verified: bool


class LeadScoreRead(BaseModel):
    company_fit: int
    persona_fit: int
    trigger_strength: int
    pain_fit: int
    reachability: int
    total_score: int
    lead_grade: str
    rationale: dict[str, Any]
    model_confidence: float


class LeadRead(ORMModel):
    id: str
    status: str
    icp_class: str | None
    persona_class: str | None
    why_now: list[str]
    recommended_offer: str | None
    recommended_sequence: str | None
    confidence: float
    company: CompanyRead | None
    contact: ContactRead | None
    scores: list[LeadScoreRead] = Field(default_factory=list)
    signals: list[SignalRead] = Field(default_factory=list)


class PipelineResult(BaseModel):
    lead_id: str
    company_id: str
    contact_id: str | None
    score_total: int
    lead_grade: str
    status: str
    recommended_sequence: str | None
    recommended_offer: str | None
    why_now: list[str]


class ReplyEventCreate(BaseModel):
    lead_id: str
    outreach_message_id: str | None = None
    raw_text: str
    reply_type: str
    sentiment: str | None = None
    intent_label: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ReplyEventRead(ORMModel):
    id: str
    lead_id: str
    outreach_message_id: str | None
    reply_type: str
    raw_text: str
    sentiment: str | None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    lead_status: str | None = None
    company_name: str | None = None
    contact_name: str | None = None
    intent_label: str | None = None
    sequence_id: str | None = None
    sequence_key: str | None = None
    step_number: int | None = None
    time_to_reply_hours: float | None = None
