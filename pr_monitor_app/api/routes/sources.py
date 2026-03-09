from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import Source
from pr_monitor_app.schemas import SourceCreate, SourceOut

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=SourceOut)
async def create_source(payload: SourceCreate, session: AsyncSession = Depends(get_session)) -> SourceOut:
    s = Source(
        source_type=payload.source_type,
        name=payload.name,
        url=payload.url,
        authority_score=payload.authority_score,
        config=payload.config,
        active=payload.active,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return SourceOut.model_validate(s)


@router.get("", response_model=list[SourceOut])
async def list_sources(active: bool | None = None, session: AsyncSession = Depends(get_session)) -> list[SourceOut]:
    q = select(Source).order_by(Source.created_at.desc())
    if active is not None:
        q = q.where(Source.active.is_(active))
    rows = (await session.execute(q)).scalars().all()
    return [SourceOut.model_validate(r) for r in rows]


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> SourceOut:
    s = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    return SourceOut.model_validate(s)


@router.delete("/{source_id}")
async def delete_source(source_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    s = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(s)
    await session.commit()
    return {"status": "deleted"}
