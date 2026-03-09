from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import Event, SourceType
from pr_monitor_app.schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
async def list_events(source_type: SourceType | None = None, limit: int = 100, session: AsyncSession = Depends(get_session)) -> list[EventOut]:
    q = select(Event).order_by(Event.published_at.desc()).limit(min(max(limit, 1), 500))
    if source_type:
        q = q.where(Event.source_type == source_type)
    rows = (await session.execute(q)).scalars().all()
    return [EventOut.model_validate(r) for r in rows]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> EventOut:
    e = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    return EventOut.model_validate(e)
