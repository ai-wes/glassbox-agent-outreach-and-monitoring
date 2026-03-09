"""
Core data models.

Every observation carries provenance (source, timestamp, raw_ref)
so results are auditable back to real inputs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ModuleResult(BaseModel):
    module: str
    status: Status
    reason: Optional[str] = None
    records_produced: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Prompt / SERP Observation
# ---------------------------------------------------------------------------

class Observation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    date: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    platform: str
    query_group: str
    query: str
    business_value: float = 0.5
    risk_level: float = 0.5

    # Core scoring fields
    brand_mentioned: int = 0          # 0 or 1
    brand_cited: int = 0              # 0 or 1 — domain appears in citation list
    own_domain_cited: int = 0         # 0 or 1
    citation_domains: str = ""        # semicolon-separated
    ai_answer_url_or_ref: str = ""
    prominence_score: int = 0         # 0-3
    sentiment_score: int = 0          # -1, 0, +1
    accuracy_flag: int = 1            # 0 or 1 (1 = accurate / not contradicted)
    actionability: int = 0            # 0 or 1 — answer contains actionable link/CTA for brand

    # Provenance
    source_api: str = ""              # e.g. "serpapi", "openai", "perplexity"
    raw_response_ref: str = ""        # ID or hash of the raw API response
    notes: str = ""
    status: Status = Status.SUCCESS


# ---------------------------------------------------------------------------
# Entity Authority
# ---------------------------------------------------------------------------

class EntityCheck(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    check_type: str                   # "knowledge_graph", "wikipedia", "wikidata", "structured_data"
    entity_name: str
    found: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    source_api: str = ""
    raw_response_ref: str = ""
    status: Status = Status.SUCCESS
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Referral Analytics
# ---------------------------------------------------------------------------

class ReferralRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    date_range_start: str
    date_range_end: str
    source: str
    medium: str
    sessions: int = 0
    page_views: int = 0
    conversions: int = 0
    is_ai_source: bool = False
    source_api: str = "ga4"
    status: Status = Status.SUCCESS


# ---------------------------------------------------------------------------
# Brand Demand
# ---------------------------------------------------------------------------

class BrandDemandRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    keyword: str
    date: str
    interest_value: int               # Google Trends 0-100
    source_api: str = "pytrends"
    status: Status = Status.SUCCESS


# ---------------------------------------------------------------------------
# Visibility Index
# ---------------------------------------------------------------------------

class VisibilityIndexResult(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope: str = "all"                # "all", platform name, query group, etc.
    total_observations: int = 0
    ai_answer_sov: float = 0.0       # % of queries where brand mentioned
    ai_citation_sov: float = 0.0     # % of queries where domain cited
    mean_prominence: float = 0.0
    mean_accuracy: float = 0.0
    mean_sentiment: float = 0.0
    visibility_index: float = 0.0
    weighted_visibility_index: float = 0.0
    status: Status = Status.SUCCESS
    reason: Optional[str] = None
