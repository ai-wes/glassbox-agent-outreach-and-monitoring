from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from outreach_app.gtm_service.schemas.common import ORMModel
from outreach_app.gtm_service.schemas.lead import ReplyEventRead


class DeliveryEventCreate(BaseModel):
    event_type: str
    occurred_at: datetime | None = None
    provider_event_id: str | None = None
    reason: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DeliveryEventRead(ORMModel):
    id: str
    outreach_message_id: str
    lead_id: str | None = None
    event_type: str
    provider_event_id: str | None = None
    reason: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    created_at: datetime


class ConversionEventCreate(BaseModel):
    event_type: str
    occurred_at: datetime | None = None
    sequence_id: str | None = None
    reply_event_id: str | None = None
    value: float | None = None
    external_ref: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ConversionEventRead(ORMModel):
    id: str
    lead_id: str
    sequence_id: str | None = None
    reply_event_id: str | None = None
    event_type: str
    occurred_at: datetime
    value: float | None = None
    external_ref: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SequencePerformanceRead(BaseModel):
    sequence_key: str
    sequences_total: int
    leads_total: int
    sent_leads: int
    messages_total: int
    sent_messages: int
    delivered_messages: int
    bounced_messages: int
    blocked_messages: int
    failed_messages: int
    replies_total: int
    replying_leads: int
    positive_replies: int
    positive_replying_leads: int
    meetings_booked: int
    opportunities_created: int
    send_rate_pct: float
    reply_rate_pct: float
    positive_reply_rate_pct: float
    meeting_rate_pct: float
    opportunity_rate_pct: float
    avg_time_to_first_reply_hours: float | None = None


class StepPerformanceRead(BaseModel):
    step_number: int
    messages_total: int
    sent_messages: int
    delivered_messages: int
    bounced_messages: int
    blocked_messages: int
    failed_messages: int
    replies_total: int
    positive_replies: int
    reply_rate_pct: float
    positive_reply_rate_pct: float
    avg_time_to_reply_hours: float | None = None
    dropoff_from_previous_step_pct: float | None = None


class AttributionPerformanceRead(BaseModel):
    attribution_type: str
    attribution_value: str
    leads_total: int
    sent_leads: int
    replying_leads: int
    positive_replying_leads: int
    meetings_booked: int
    opportunities_created: int
    reply_rate_pct: float
    positive_reply_rate_pct: float
    meeting_rate_pct: float
    opportunity_rate_pct: float


class FunnelMetricsRead(BaseModel):
    leads_total: int
    qualified_leads: int
    queued_leads: int
    sent_leads: int
    replied_leads: int
    positive_replied_leads: int
    meetings_booked: int
    opportunities_created: int


class MessageTelemetryRead(BaseModel):
    message_id: str
    sequence_id: str
    sequence_key: str
    step_number: int
    channel: str
    subject: str | None = None
    status: str
    scheduled_for: datetime
    sent_at: datetime | None = None
    latest_delivery_status: str | None = None
    latest_delivery_reason: str | None = None
    delivery_events: list[DeliveryEventRead] = Field(default_factory=list)
    reply_count: int = 0
    reply_intents: list[str] = Field(default_factory=list)


class LeadTelemetryRead(BaseModel):
    lead_id: str
    lead_status: str
    company_name: str | None = None
    contact_name: str | None = None
    recommended_sequence: str | None = None
    recommended_offer: str | None = None
    persona_class: str | None = None
    icp_class: str | None = None
    attribution_sources: list[str] = Field(default_factory=list)
    sent_messages: int
    delivered_messages: int
    bounced_messages: int
    blocked_messages: int
    failed_messages: int
    replies_total: int
    positive_replies: int
    meetings_booked: int
    opportunities_created: int
    messages: list[MessageTelemetryRead] = Field(default_factory=list)
    reply_events: list[ReplyEventRead] = Field(default_factory=list)
    conversion_events: list[ConversionEventRead] = Field(default_factory=list)


class MetricsDashboardRead(BaseModel):
    summary: dict[str, Any]
    funnel: FunnelMetricsRead
    sequences: list[SequencePerformanceRead] = Field(default_factory=list)
    steps: list[StepPerformanceRead] = Field(default_factory=list)
    attribution: list[AttributionPerformanceRead] = Field(default_factory=list)
    recent_replies: list[ReplyEventRead] = Field(default_factory=list)
    recent_delivery_issues: list[DeliveryEventRead] = Field(default_factory=list)
    recent_conversions: list[ConversionEventRead] = Field(default_factory=list)
