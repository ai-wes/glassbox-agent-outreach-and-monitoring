from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClientProfileUpsert(BaseModel):
    voice_instructions: Optional[str] = None
    do_not_say: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    compliance_notes: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ClientProfileOut(BaseModel):
    client_id: uuid.UUID
    voice_instructions: Optional[str]
    do_not_say: list[str]
    default_hashtags: list[str]
    compliance_notes: Optional[str]
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SignalRouteCreate(BaseModel):
    enabled: bool = True
    recipient_type: str  # user | group
    recipient_id: str
    from_number: Optional[str] = None


class SignalRouteOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    enabled: bool
    recipient_type: str
    recipient_id: str
    from_number: Optional[str]
    created_at: datetime


class AgentJobOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    client_id: uuid.UUID
    topic_ids: list[str]
    top_relevance_score: float
    priority: str
    status: str
    agent_version: int
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    output_id: Optional[uuid.UUID]
    error_message: Optional[str]


class AgentOutputOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    client_id: uuid.UUID
    agent_version: int
    model: str
    generated_at: datetime
    output: dict[str, Any]
    summary_text: Optional[str]
    prompt_tokens: Optional[int]
    output_tokens: Optional[int]
    meta: dict[str, Any]


class OpenClawJobRef(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    client_id: uuid.UUID
    priority: str
    top_relevance_score: float
    agent_version: int


class OpenClawClientContext(BaseModel):
    id: uuid.UUID
    name: str
    voice_instructions: Optional[str] = None
    do_not_say: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    compliance_notes: Optional[str] = None


class OpenClawEventContext(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    fetched_at: Optional[str] = None
    excerpt: str


class OpenClawTopTopic(BaseModel):
    id: uuid.UUID
    name: str
    relevance_score: float
    keywords: list[str] = Field(default_factory=list)


class OpenClawRiskContext(BaseModel):
    level: str
    notes: list[str] = Field(default_factory=list)


class OpenClawAnalysisContext(BaseModel):
    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None
    frames: list[dict[str, Any]] = Field(default_factory=list)
    top_topics: list[OpenClawTopTopic] = Field(default_factory=list)
    risk: OpenClawRiskContext


class OpenClawBrandConfig(BaseModel):
    id: uuid.UUID
    brand_name: str
    brand_domains: list[str] = Field(default_factory=list)
    brand_aliases: list[str] = Field(default_factory=list)
    key_claims: dict[str, str] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    executive_names: list[str] = Field(default_factory=list)
    official_website: Optional[str] = None
    social_profiles: list[str] = Field(default_factory=list)
    updated_at: Optional[str] = None


class OpenClawBrandCatalogItem(BaseModel):
    id: uuid.UUID
    brand_name: str
    official_website: Optional[str] = None
    updated_at: Optional[str] = None


class OpenClawBrandResolution(BaseModel):
    source: str
    available_count: int


class OpenClawInstructions(BaseModel):
    output_contract: str
    brand_config_usage: str


class OpenClawDailyPodcastReport(BaseModel):
    id: uuid.UUID
    report_date: Optional[str] = None
    title: str
    created_at: Optional[str] = None
    summary_excerpt: str
    report_md: str
    source_path: Optional[str] = None
    status: str


class OpenClawJobContext(BaseModel):
    job: OpenClawJobRef
    client: OpenClawClientContext
    event: OpenClawEventContext
    analysis: OpenClawAnalysisContext
    brand_config: Optional[OpenClawBrandConfig] = None
    brand_config_resolution: OpenClawBrandResolution
    brand_config_catalog: list[OpenClawBrandCatalogItem] = Field(default_factory=list)
    daily_podcast_report: Optional[OpenClawDailyPodcastReport] = None
    instructions: OpenClawInstructions


class OpenClawClaimResponse(BaseModel):
    jobs: list[OpenClawJobContext]


class OpenClawCompleteIn(BaseModel):
    output: dict[str, Any]
    model: str = "openclaw"
    summary_text: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class OpenClawFailIn(BaseModel):
    error_message: str
