"""Brand config CRUD for OpenClaw agent and AI PR measurement."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.analytics.ai_pr_measurement import run_ai_pr_measurement_from_settings
from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import BrandConfigDB
from pr_monitor_app.schemas import BrandConfigCreate, BrandConfigOut, BrandConfigUpdate

router = APIRouter(prefix="/brand-configs", tags=["brand-configs"])


@router.get("", response_model=list[BrandConfigOut])
async def list_brand_configs(
    session: AsyncSession = Depends(get_session),
    brand_name: str | None = Query(default=None, description="Filter by exact brand name"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[BrandConfigOut]:
    """List all brand configs. OpenClaw can use this to retrieve configs when prompted."""
    q = select(BrandConfigDB).order_by(BrandConfigDB.updated_at.desc())
    if brand_name:
        q = q.where(BrandConfigDB.brand_name == brand_name.strip())
    rows = (await session.execute(q.limit(limit))).scalars().all()
    return [BrandConfigOut.model_validate(r) for r in rows]


@router.get("/{config_id}", response_model=BrandConfigOut)
async def get_brand_config(
    config_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> BrandConfigOut:
    """Get a single brand config by ID."""
    row = await session.get(BrandConfigDB, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="brand config not found")
    return BrandConfigOut.model_validate(row)


@router.get("/by-name/{brand_name}", response_model=BrandConfigOut)
async def get_brand_config_by_name(
    brand_name: str,
    session: AsyncSession = Depends(get_session),
) -> BrandConfigOut:
    """Get a brand config by brand name (for agent lookup)."""
    row = (
        await session.execute(
            select(BrandConfigDB).where(BrandConfigDB.brand_name == brand_name.strip())
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"brand config '{brand_name}' not found")
    return BrandConfigOut.model_validate(row)


@router.post("", response_model=BrandConfigOut, status_code=201)
async def create_brand_config(
    payload: BrandConfigCreate,
    session: AsyncSession = Depends(get_session),
) -> BrandConfigOut:
    """Create a new brand config. OpenClaw can use this when prompted to add a brand."""
    existing = (
        await session.execute(
            select(BrandConfigDB).where(BrandConfigDB.brand_name == payload.brand_name.strip())
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"brand config '{payload.brand_name}' already exists")

    row = BrandConfigDB(
        brand_name=payload.brand_name.strip(),
        brand_domains=payload.brand_domains or [],
        brand_aliases=payload.brand_aliases or [],
        key_claims=payload.key_claims or {},
        competitors=payload.competitors or [],
        executive_names=payload.executive_names or [],
        official_website=payload.official_website,
        social_profiles=payload.social_profiles or [],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return BrandConfigOut.model_validate(row)


@router.put("/{config_id}", response_model=BrandConfigOut)
async def update_brand_config(
    config_id: uuid.UUID,
    payload: BrandConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> BrandConfigOut:
    """Update an existing brand config. OpenClaw can use this when prompted to modify."""
    row = await session.get(BrandConfigDB, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="brand config not found")

    if payload.brand_domains is not None:
        row.brand_domains = payload.brand_domains
    if payload.brand_aliases is not None:
        row.brand_aliases = payload.brand_aliases
    if payload.key_claims is not None:
        row.key_claims = payload.key_claims
    if payload.competitors is not None:
        row.competitors = payload.competitors
    if payload.executive_names is not None:
        row.executive_names = payload.executive_names
    if payload.official_website is not None:
        row.official_website = payload.official_website
    if payload.social_profiles is not None:
        row.social_profiles = payload.social_profiles

    row.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(row)
    return BrandConfigOut.model_validate(row)


@router.patch("/{config_id}", response_model=BrandConfigOut)
async def patch_brand_config(
    config_id: uuid.UUID,
    payload: BrandConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> BrandConfigOut:
    """Partial update (same as PUT for this resource)."""
    return await update_brand_config(config_id, payload, session)


@router.post("/{config_id}/run-ai-pr")
async def run_ai_pr_for_brand_config(
    config_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run AI PR measurement for a specific brand config."""
    row = await session.get(BrandConfigDB, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="brand config not found")

    import asyncio

    result = await asyncio.to_thread(
        run_ai_pr_measurement_from_settings,
        brand_name=None,
        brand_config_id=str(config_id),
    )
    return {
        "mode": "sync",
        "brand_config_id": str(config_id),
        "brand_name": row.brand_name,
        "result": result,
    }


@router.delete("/{config_id}", status_code=204)
async def delete_brand_config(
    config_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a brand config. OpenClaw can use this when prompted to remove."""
    row = await session.get(BrandConfigDB, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="brand config not found")
    await session.delete(row)
    await session.commit()
