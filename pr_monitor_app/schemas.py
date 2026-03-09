from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from pr_monitor_app.models import AlertTier, EmailDirection, EngagementMode, NotificationChannel, SourceType, SubscriptionType


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    messaging_pillars: list[str] = Field(default_factory=list)
    risk_keywords: list[str] = Field(default_factory=list)
    audience_profile: dict[str, Any] = Field(default_factory=dict)
    brand_voice_profile: dict[str, Any] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    signal_recipient: Optional[str] = None
    telegram_recipient: Optional[str] = None
    whatsapp_recipient: Optional[str] = None
    email_recipient: Optional[str] = None


class ClientOut(BaseModel):
    id: uuid.UUID
    name: str
    messaging_pillars: list[str]
    risk_keywords: list[str]
    audience_profile: dict[str, Any]
    brand_voice_profile: dict[str, Any]
    competitors: list[str]
    signal_recipient: Optional[str]
    telegram_recipient: Optional[str]
    whatsapp_recipient: Optional[str]
    email_recipient: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class TopicLensCreate(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    competitor_overrides: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    opportunity_tags: list[str] = Field(default_factory=list)


class TopicLensOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    description: str
    keywords: list[str]
    competitor_overrides: list[str]
    risk_flags: list[str]
    opportunity_tags: list[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SourceCreate(BaseModel):
    source_type: SourceType
    name: str
    url: str
    authority_score: float = Field(default=0.5, ge=0.0, le=1.0)
    config: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class SourceOut(BaseModel):
    id: uuid.UUID
    source_type: SourceType
    name: str
    url: str
    authority_score: float
    config: dict[str, Any]
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: uuid.UUID
    source_type: SourceType
    title: str
    author: str
    url: str
    published_at: datetime
    raw_text: str
    engagement_stats: dict[str, Any]
    detected_entities: list[str]
    sentiment: float
    created_at: datetime

    class Config:
        from_attributes = True


class ClientEventOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    event_id: uuid.UUID
    topic_id: uuid.UUID
    scores: dict[str, Any]
    composite_score: float
    tier: AlertTier
    rationale: str
    created_at: datetime

    class Config:
        from_attributes = True


class BriefOut(BaseModel):
    id: uuid.UUID
    client_event_id: uuid.UUID
    event_summary: str
    strategic_analysis: dict[str, Any]
    engagement_mode: EngagementMode
    confidence: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class DraftSetOut(BaseModel):
    id: uuid.UUID
    brief_id: uuid.UUID
    linkedin_comments: dict[str, Any]
    independent_posts: dict[str, Any]
    guardrail_report: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class AlertOut(BaseModel):
    id: uuid.UUID
    client_event_id: uuid.UUID
    tier: AlertTier
    message_text: str
    channel: NotificationChannel
    recipient: str
    signal_recipient: str
    status: str
    sent_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackCreate(BaseModel):
    client_id: uuid.UUID
    client_event_id: Optional[uuid.UUID] = None
    action_taken: str
    notes: str = ""


# Layer 1 subscription ingestion schemas
class SubscriptionCreate(BaseModel):
    type: SubscriptionType
    name: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1)
    client_id: Optional[uuid.UUID] = None
    topic_id: Optional[uuid.UUID] = None
    enabled: bool = True
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)
    fetch_full_content: bool = False
    meta_json: dict[str, Any] = Field(default_factory=dict)


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    client_id: Optional[uuid.UUID]
    topic_id: Optional[uuid.UUID]
    type: str
    name: str
    url: str
    enabled: bool
    poll_interval_seconds: int
    fetch_full_content: bool
    last_polled_at: Optional[datetime]
    last_success_at: Optional[datetime]
    last_error: Optional[str]
    consecutive_failures: int
    created_at: datetime
    meta_json: dict[str, Any]

    class Config:
        from_attributes = True


class IngestionEventOut(BaseModel):
    id: uuid.UUID
    canonical_url: str
    title: str
    summary: Optional[str]
    published_at: Optional[datetime]
    fetched_at: datetime
    source_type: str

    class Config:
        from_attributes = True


class WebhookEventIn(BaseModel):
    model_config = {"extra": "allow"}

    url: str = Field(min_length=1)
    title: Optional[str] = None
    summary: Optional[str] = None
    content_text: Optional[str] = None
    published_at: Optional[str] = None
    author: Optional[str] = None


# Layer 2 analytics schemas (Topic = TopicLens for analytics API)
class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query_json: dict[str, Any] = Field(default_factory=dict)


class TopicOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    query_json: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class EventAnalysisOut(BaseModel):
    event_id: uuid.UUID
    analysis_version: int
    analyzed_at: datetime
    text_hash: str
    sentiment_score: Optional[float]
    sentiment_label: Optional[str]
    frames: list[dict[str, Any]]
    status: str
    error_message: Optional[str]
    meta_json: dict[str, Any]


class EventTopicScoreOut(BaseModel):
    event_id: uuid.UUID
    client_id: uuid.UUID
    topic_id: uuid.UUID
    relevance_score: float
    keyword_score: float
    embedding_score: Optional[float]
    computed_at: datetime
    reasons_json: dict[str, Any]


class ClientEventFeedItem(BaseModel):
    event: IngestionEventOut
    topic_id: uuid.UUID
    relevance_score: float
    sentiment_score: Optional[float]
    top_frame: Optional[str]


class DailyTopicMetricOut(BaseModel):
    client_id: uuid.UUID
    topic_id: uuid.UUID
    day: date
    event_count: int
    avg_relevance: Optional[float]
    avg_sentiment: Optional[float]
    top_frames_json: list[dict[str, Any]]
    computed_at: datetime


# Brand config (AI PR measurement, agent CRUD)
class BrandConfigCreate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=200)
    brand_domains: list[str] = Field(default_factory=list)
    brand_aliases: list[str] = Field(default_factory=list)
    key_claims: dict[str, str] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    executive_names: list[str] = Field(default_factory=list)
    official_website: Optional[str] = None
    social_profiles: list[str] = Field(default_factory=list)


class BrandConfigUpdate(BaseModel):
    brand_domains: Optional[list[str]] = None
    brand_aliases: Optional[list[str]] = None
    key_claims: Optional[dict[str, str]] = None
    competitors: Optional[list[str]] = None
    executive_names: Optional[list[str]] = None
    official_website: Optional[str] = None
    social_profiles: Optional[list[str]] = None


class BrandConfigOut(BaseModel):
    id: uuid.UUID
    brand_name: str
    brand_domains: list[str]
    brand_aliases: list[str]
    key_claims: dict[str, str]
    competitors: list[str]
    executive_names: list[str]
    official_website: Optional[str]
    social_profiles: list[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmailMessageOut(BaseModel):
    id: uuid.UUID
    client_id: Optional[uuid.UUID]
    direction: EmailDirection
    provider: str
    message_id: Optional[str]
    thread_id: Optional[str]
    in_reply_to: Optional[str]
    from_email: str
    to_email: str
    subject: Optional[str]
    text_body: Optional[str]
    html_body: Optional[str]
    status: str
    error_message: Optional[str]
    meta_json: dict[str, Any]
    received_at: datetime
    sent_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class EmailReplyIn(BaseModel):
    to_email: Optional[str] = None
    subject: Optional[str] = None
    body_text: str = Field(min_length=1)
    body_html: Optional[str] = None


class EmailSendIn(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1)
    body_html: Optional[str] = None
    client_id: Optional[uuid.UUID] = None
