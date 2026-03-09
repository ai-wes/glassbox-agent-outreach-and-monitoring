from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from glassbox_radar.enums import MilestoneType, OpportunityStatus, SignalType, SourceType


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    domain: str | None
    stage: str | None
    therapeutic_areas: list[str]
    warm_intro_paths: list[str]


class ProgramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    asset_name: str | None
    target: str | None
    mechanism: str | None
    modality: str | None
    indication: str | None
    stage: str | None
    estimated_next_milestone: MilestoneType | None
    estimated_milestone_date: date | None
    milestone_confidence: float | None
    latest_radar_score: float | None


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    program_id: str | None
    source_type: SourceType
    signal_type: SignalType
    title: str
    summary: str | None
    source_url: str
    published_at: datetime | None
    confidence: float
    evidence_tags: list[str]
    milestone_tags: list[str]


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    program_id: str
    radar_score: float
    milestone_score: float
    fragility_score: float
    capital_score: float
    reachability_score: float
    milestone_type: MilestoneType
    milestone_confidence: float
    milestone_window_start: date | None
    milestone_window_end: date | None
    primary_buyer_role: str | None
    outreach_angle: str | None
    risk_hypothesis: str | None
    capital_exposure_band: str | None
    tier: str | None
    status: OpportunityStatus
    owner: str | None
    dossier_path: str | None
    sheet_row_reference: str | None
    last_exported_to_sheet_at: datetime | None
    last_evaluated_at: datetime | None


class PipelineRunSummary(BaseModel):
    pipeline_run_id: str
    started_at: datetime
    ended_at: datetime | None
    stats: dict[str, Any] = Field(default_factory=dict)
    status: str
    error_message: str | None = None
