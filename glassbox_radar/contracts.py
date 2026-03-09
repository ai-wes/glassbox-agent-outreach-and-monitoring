from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from glassbox_radar.enums import MilestoneType, SignalType, SourceType


@dataclass(slots=True)
class ContactSnapshot:
    name: str
    title: str | None = None
    email: str | None = None
    role: str | None = None
    warm_intro_strength: float | None = None
    is_primary: bool = False


@dataclass(slots=True)
class CollectionContext:
    company_id: str
    program_id: str
    company_name: str
    company_aliases: list[str]
    domain: str | None
    warm_intro_paths: list[str]
    investors: list[str]
    board_members: list[str]
    company_stage: str | None
    asset_name: str | None
    target: str | None
    mechanism: str | None
    modality: str | None
    indication: str | None
    stage: str | None
    key_terms: list[str]
    rss_feeds: list[str]
    contacts: list[ContactSnapshot]

    @property
    def search_terms(self) -> list[str]:
        ordered: list[str] = []
        for candidate in [
            self.asset_name,
            self.target,
            self.mechanism,
            self.indication,
            self.company_name,
            *self.company_aliases,
            *self.key_terms,
        ]:
            if not candidate:
                continue
            normalized = candidate.strip()
            if len(normalized) < 3:
                continue
            if normalized.lower() not in {x.lower() for x in ordered}:
                ordered.append(normalized)
        return ordered


@dataclass(slots=True)
class CollectedSignal:
    source_type: SourceType
    signal_type: SignalType
    title: str
    summary: str | None
    content: str | None
    source_url: str
    published_at: datetime | None
    confidence: float
    raw_payload: dict[str, Any] = field(default_factory=dict)
    evidence_tags: list[str] = field(default_factory=list)
    milestone_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MilestoneInference:
    milestone_type: MilestoneType
    confidence: float
    window_start: date | None
    window_end: date | None
    rationale: list[str]


@dataclass(slots=True)
class OpportunityScore:
    milestone_score: float
    fragility_score: float
    capital_score: float
    reachability_score: float
    radar_score: float
    milestone_type: MilestoneType
    milestone_confidence: float
    milestone_window_start: date | None
    milestone_window_end: date | None
    primary_buyer_role: str
    outreach_angle: str
    risk_hypothesis: str
    capital_exposure_band: str
    tier: str
