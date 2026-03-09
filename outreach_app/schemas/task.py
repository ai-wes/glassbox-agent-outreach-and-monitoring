from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=280)
    domain: str = Field(..., description="exec|gtm|narrative|ops")
    priority: int = Field(default=50, ge=0, le=100)
    owner_agent: str = Field(default="router")
    due_at: datetime | None = None
    payload_json: dict = Field(default_factory=dict)


class TaskOut(BaseModel):
    id: str
    title: str
    domain: str
    priority: int
    owner_agent: str
    status: str
    due_at: datetime | None
    payload_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
