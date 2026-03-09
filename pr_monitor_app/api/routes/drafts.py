from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import CreativeDraftSet
from pr_monitor_app.schemas import DraftSetOut

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("/by-brief/{brief_id}", response_model=DraftSetOut)
async def get_drafts_by_brief(brief_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> DraftSetOut:
    d = (await session.execute(select(CreativeDraftSet).where(CreativeDraftSet.brief_id == brief_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return DraftSetOut.model_validate(d)


@router.get("/{draft_id}", response_model=DraftSetOut)
async def get_draft(draft_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> DraftSetOut:
    d = (await session.execute(select(CreativeDraftSet).where(CreativeDraftSet.id == draft_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return DraftSetOut.model_validate(d)
