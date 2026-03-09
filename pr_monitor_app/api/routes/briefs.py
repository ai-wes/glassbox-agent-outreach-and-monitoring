from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import StrategicBrief
from pr_monitor_app.schemas import BriefOut

router = APIRouter(prefix="/briefs", tags=["briefs"])


@router.get("", response_model=list[BriefOut])
async def list_briefs(limit: int = 100, session: AsyncSession = Depends(get_session)) -> list[BriefOut]:
    rows = (await session.execute(select(StrategicBrief).order_by(StrategicBrief.created_at.desc()).limit(min(max(limit, 1), 500)))).scalars().all()
    return [BriefOut.model_validate(r) for r in rows]


@router.get("/{brief_id}", response_model=BriefOut)
async def get_brief(brief_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> BriefOut:
    b = (await session.execute(select(StrategicBrief).where(StrategicBrief.id == brief_id))).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Not found")
    return BriefOut.model_validate(b)
