from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class RunStart(BaseModel):
    requested_by: str = Field(default="user")
    force_agent: str | None = Field(default=None, description="Override router agent")
    dry_run: bool = Field(default=False, description="Execute but prevent external Tier2+ actions")


class RunOut(BaseModel):
    id: str
    task_id: str
    agent: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    max_risk_tier: int
    cost_estimate_usd: float | None
    plan_json: dict
    summary: str | None
    evidence_uri: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalRequestOut(BaseModel):
    run_id: str
    approval_id: str
    scope: str
    expires_at: datetime
    token: str = Field(description="One-time approval token. Store securely.")
    reason: str


class ApprovalSubmit(BaseModel):
    token: str
    approved_by: str = Field(default="user")
    notes: str | None = None


class EvidencePackOut(BaseModel):
    run_id: str
    evidence_uri: str
    artifacts: list[dict]
