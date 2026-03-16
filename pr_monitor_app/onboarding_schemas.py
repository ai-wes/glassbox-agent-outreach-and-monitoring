from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class OnboardingIntakeIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    short_description: Optional[str] = None
    notes: Optional[str] = None
    competitors: list[str] = Field(default_factory=list)
    executives: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    industry: Optional[str] = None
    geographies: list[str] = Field(default_factory=list)
    monitoring_goals: list[str] = Field(default_factory=list)
    created_by: Optional[str] = None

    @field_validator("competitors", "executives", "products", "geographies", "monitoring_goals", mode="before")
    @classmethod
    def parse_csv_or_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]


class OnboardingSessionOut(BaseModel):
    id: uuid.UUID
    company_name_input: str
    website_input: Optional[str]
    linkedin_url_input: Optional[str]
    short_description_input: Optional[str]
    notes_input: Optional[str]
    status: str
    created_by: Optional[str]
    final_client_id: Optional[uuid.UUID]
    raw_intake_json: dict[str, Any]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyResolutionCandidateOut(BaseModel):
    id: uuid.UUID
    onboarding_session_id: uuid.UUID
    display_name: str
    canonical_name: str
    website: Optional[str]
    linkedin_url: Optional[str]
    summary: Optional[str]
    confidence_score: float
    source_evidence_json: dict[str, Any]
    is_selected: bool
    rationale: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ResolvedCompanyProfileOut(BaseModel):
    id: uuid.UUID
    onboarding_session_id: uuid.UUID
    canonical_name: str
    website: Optional[str]
    linkedin_url: Optional[str]
    summary: Optional[str]
    industry: Optional[str]
    subindustry: Optional[str]
    products_json: list[str]
    executives_json: list[str]
    competitors_json: list[str]
    channels_json: dict[str, Any]
    themes_json: list[str]
    risk_themes_json: list[str]
    opportunity_themes_json: list[str]
    source_evidence_json: dict[str, Any]
    confidence_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MonitoringCategoryProposalPatch(BaseModel):
    id: Optional[uuid.UUID] = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: str = "medium"
    rationale: str = ""
    sensitivity: str = "medium"
    recommended_sources_json: list[str] = Field(default_factory=list)
    entities_json: list[str] = Field(default_factory=list)
    keywords_json: list[str] = Field(default_factory=list)
    negative_keywords_json: list[str] = Field(default_factory=list)
    sample_queries_json: list[str] = Field(default_factory=list)
    status: str = "approved"


class MonitoringCategoryProposalOut(MonitoringCategoryProposalPatch):
    id: uuid.UUID
    blueprint_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MonitoringBlueprintProposalOut(BaseModel):
    id: uuid.UUID
    onboarding_session_id: uuid.UUID
    company_profile_id: uuid.UUID
    proposal_version: int
    summary: str
    overall_confidence: float
    rationale: str
    proposal_json: dict[str, Any]
    categories: list[MonitoringCategoryProposalOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BlueprintReviewDecisionIn(BaseModel):
    action_type: str = Field(min_length=1, max_length=64)
    target_type: str = Field(min_length=1, max_length=64)
    target_id: Optional[str] = None
    notes: Optional[str] = None
    diff_json: dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None


class BlueprintReviewDecisionOut(BaseModel):
    id: uuid.UUID
    blueprint_id: uuid.UUID
    action_type: str
    target_type: str
    target_id: Optional[str]
    notes: Optional[str]
    diff_json: dict[str, Any]
    created_at: datetime
    created_by: Optional[str]

    class Config:
        from_attributes = True


class ConfirmCandidateIn(BaseModel):
    candidate_id: Optional[uuid.UUID] = None
    display_name: Optional[str] = None
    canonical_name: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: Optional[str] = None


class MaterializeSignalRouteIn(BaseModel):
    enabled: bool = True
    recipient_type: str
    recipient_id: str
    from_number: Optional[str] = None


class MaterializeBlueprintIn(BaseModel):
    created_by: Optional[str] = None
    signal_routes: list[MaterializeSignalRouteIn] = Field(default_factory=list)


class MaterializationResultOut(BaseModel):
    client_id: uuid.UUID
    client_name: str
    created_or_updated: str
    topic_ids: list[uuid.UUID] = Field(default_factory=list)
    subscription_ids: list[uuid.UUID] = Field(default_factory=list)
    signal_route_ids: list[uuid.UUID] = Field(default_factory=list)
    brand_config_id: Optional[uuid.UUID] = None


class OnboardingSessionDetailOut(BaseModel):
    session: OnboardingSessionOut
    candidates: list[CompanyResolutionCandidateOut] = Field(default_factory=list)
    recommended_candidate: Optional[CompanyResolutionCandidateOut] = None
    selected_candidate: Optional[CompanyResolutionCandidateOut] = None
    company_profile: Optional[ResolvedCompanyProfileOut] = None
    blueprint: Optional[MonitoringBlueprintProposalOut] = None
    review_decisions: list[BlueprintReviewDecisionOut] = Field(default_factory=list)
    disambiguation_prompt: Optional[str] = None


class OnboardingAutoOut(BaseModel):
    session: OnboardingSessionDetailOut
    stopped_at: str
