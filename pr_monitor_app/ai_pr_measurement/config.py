"""
Configuration management.

All secrets come from environment variables.
Brand config and prompt library come from JSON files whose paths
are set via environment variables.  If a required file or key is
missing the corresponding module will return SKIPPED.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brand configuration (loaded from JSON file)
# ---------------------------------------------------------------------------

class BrandConfig(BaseModel):
    brand_name: str
    brand_domains: list[str]
    brand_aliases: list[str] = Field(default_factory=list)
    key_claims: dict[str, str] = Field(default_factory=dict)
    competitors: list[str] = Field(default_factory=list)
    executive_names: list[str] = Field(default_factory=list)
    official_website: Optional[str] = None
    social_profiles: list[str] = Field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        names = [self.brand_name] + self.brand_aliases
        return list(dict.fromkeys(names))  # deduplicated, order-preserved


class PromptEntry(BaseModel):
    query: str
    group: str = "general"
    intent: str = "informational"
    business_value: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_level: float = Field(default=0.5, ge=0.0, le=1.0)
    platforms: list[str] = Field(default_factory=lambda: ["google", "openai", "perplexity"])

    @field_validator("platforms", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x).lower().strip() for x in v]
        return v


class PlatformWeights(BaseModel):
    """Audience-share weights per platform for index weighting."""
    google: float = 0.50
    bing: float = 0.10
    openai: float = 0.20
    perplexity: float = 0.15
    other: float = 0.05


# ---------------------------------------------------------------------------
# Secrets / env
# ---------------------------------------------------------------------------

class Secrets(BaseModel):
    serpapi_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    google_kg_api_key: Optional[str] = None
    ga4_property_id: Optional[str] = None
    ga4_credentials_path: Optional[str] = None  # path to service-account JSON


def load_secrets() -> Secrets:
    return Secrets(
        serpapi_key=os.environ.get("SERPAPI_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        perplexity_api_key=os.environ.get("PERPLEXITY_API_KEY"),
        google_kg_api_key=os.environ.get("GOOGLE_KG_API_KEY"),
        ga4_property_id=os.environ.get("GA4_PROPERTY_ID"),
        ga4_credentials_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    )


def load_brand_config(
    *,
    brand_name: Optional[str] = None,
    brand_config_id: Optional[uuid.UUID] = None,
) -> Optional[BrandConfig]:
    """Load brand config with DB-first behavior and file fallback."""
    source = os.environ.get("BRAND_CONFIG_SOURCE", "db").strip().lower()

    if source == "file":
        return _load_brand_config_from_file()

    # Default behavior is database-first for multi-brand operation.
    from_db = _load_brand_config_from_db(brand_name=brand_name, brand_config_id=brand_config_id)
    if from_db is not None:
        return from_db

    # Optional fallback to file if provided.
    return _load_brand_config_from_file()


def _load_brand_config_from_db(
    *,
    brand_name: Optional[str] = None,
    brand_config_id: Optional[uuid.UUID] = None,
) -> Optional[BrandConfig]:
    """Load brand config from database by id/name or latest updated row."""
    try:
        from sqlalchemy import select
        from pr_monitor_app.db_sync import sync_db_session
        from pr_monitor_app.models import BrandConfigDB
    except ImportError:
        logger.warning("DB not available for brand config — SKIPPED")
        return None

    id_filter = brand_config_id
    if id_filter is None:
        raw_id = os.environ.get("BRAND_CONFIG_ID", "").strip()
        if raw_id:
            try:
                id_filter = uuid.UUID(raw_id)
            except ValueError:
                logger.warning("Invalid BRAND_CONFIG_ID=%s; ignoring", raw_id)

    name_filter = (brand_name or "").strip()
    if not name_filter:
        name_filter = os.environ.get("BRAND_CONFIG_NAME", "").strip()

    with sync_db_session() as session:
        q = select(BrandConfigDB).order_by(BrandConfigDB.updated_at.desc())
        if id_filter is not None:
            q = q.where(BrandConfigDB.id == id_filter)
        elif name_filter:
            q = q.where(BrandConfigDB.brand_name == name_filter)
        row = session.execute(q.limit(1)).scalar_one_or_none()
        if not row:
            logger.warning("No matching brand config in DB — SKIPPED")
            return None
        return BrandConfig(
            brand_name=row.brand_name,
            brand_domains=list(row.brand_domains or []),
            brand_aliases=list(row.brand_aliases or []),
            key_claims=dict(row.key_claims or {}),
            competitors=list(row.competitors or []),
            executive_names=list(row.executive_names or []),
            official_website=row.official_website,
            social_profiles=list(row.social_profiles or []),
        )


def _load_brand_config_from_file() -> Optional[BrandConfig]:
    path_str = os.environ.get("BRAND_CONFIG_PATH")
    if not path_str:
        logger.warning("BRAND_CONFIG_PATH not set — file fallback skipped")
        return None
    p = Path(path_str)
    if not p.exists():
        logger.warning("Brand config file %s not found — SKIPPED", p)
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return BrandConfig(**data)


def load_prompt_library(*, brand: Optional[BrandConfig] = None) -> Optional[list[PromptEntry]]:
    path_str = os.environ.get("PROMPT_LIBRARY_PATH")
    if not path_str:
        logger.warning("PROMPT_LIBRARY_PATH not set — using generated default prompt library")
        return _default_prompt_library(brand)
    p = Path(path_str)
    if not p.exists():
        logger.warning("Prompt library file %s not found — using generated default prompt library", p)
        return _default_prompt_library(brand)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) == 0:
        logger.warning("Prompt library is empty — using generated default prompt library")
        return _default_prompt_library(brand)
    return [PromptEntry(**entry) for entry in data]


def _default_prompt_library(brand: Optional[BrandConfig]) -> list[PromptEntry]:
    brand_name = (brand.brand_name if brand else "the brand").strip() or "the brand"
    competitor = ""
    if brand and brand.competitors:
        competitor = (brand.competitors[0] or "").strip()

    comparison_target = competitor or "top competitors"
    social_hint = " and social media channels" if brand and brand.social_profiles else ""

    defaults = [
        PromptEntry(
            query=f"{brand_name} review",
            group="reputation",
            intent="navigational",
            business_value=0.85,
            risk_level=0.65,
        ),
        PromptEntry(
            query=f"{brand_name} complaints",
            group="reputation",
            intent="informational",
            business_value=0.9,
            risk_level=0.9,
        ),
        PromptEntry(
            query=f"{brand_name} customer service",
            group="service",
            intent="transactional",
            business_value=0.8,
            risk_level=0.6,
        ),
        PromptEntry(
            query=f"{brand_name} pricing",
            group="commercial",
            intent="commercial",
            business_value=0.82,
            risk_level=0.45,
        ),
        PromptEntry(
            query=f"{brand_name} alternatives",
            group="competition",
            intent="commercial",
            business_value=0.8,
            risk_level=0.5,
        ),
        PromptEntry(
            query=f"{brand_name} vs {comparison_target}",
            group="competition",
            intent="commercial",
            business_value=0.88,
            risk_level=0.5,
        ),
        PromptEntry(
            query=f"{brand_name} latest news",
            group="news",
            intent="informational",
            business_value=0.78,
            risk_level=0.55,
        ),
        PromptEntry(
            query=f"{brand_name} leadership team",
            group="authority",
            intent="informational",
            business_value=0.72,
            risk_level=0.4,
        ),
        PromptEntry(
            query=f"{brand_name} trust and safety",
            group="risk",
            intent="informational",
            business_value=0.87,
            risk_level=0.82,
        ),
        PromptEntry(
            query=f"{brand_name} sentiment across search{social_hint}",
            group="reputation",
            intent="informational",
            business_value=0.75,
            risk_level=0.55,
        ),
    ]
    return defaults


def load_platform_weights() -> PlatformWeights:
    path_str = os.environ.get("PLATFORM_WEIGHTS_PATH")
    if path_str:
        p = Path(path_str)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PlatformWeights(**data)
    return PlatformWeights()
