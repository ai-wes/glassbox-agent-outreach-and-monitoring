from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from outreach_app.gtm_service.schemas.common import ORMModel


class SequenceQueueRequest(BaseModel):
    force: bool = False
    start_immediately: bool = False


class GeneratedMessage(BaseModel):
    step_number: int
    channel: str
    delay_days: int
    subject: str | None = None
    body: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SequencePreview(BaseModel):
    sequence_key: str
    messages: list[GeneratedMessage]


class OutreachMessageRead(ORMModel):
    id: str
    step_number: int
    channel: str
    subject: str | None
    body: str
    status: str
    scheduled_for: datetime
    sent_at: datetime | None
    metadata_json: dict[str, Any]


class OutreachSequenceRead(ORMModel):
    id: str
    lead_id: str
    sequence_key: str
    status: str
    current_step: int
    started_at: datetime | None
    last_action_at: datetime | None
    metadata_json: dict[str, Any]
    messages: list[OutreachMessageRead] = Field(default_factory=list)


class RunDueResponse(BaseModel):
    sent: int
    queued_manual: int
    failed: int
    details: list[dict[str, Any]]
