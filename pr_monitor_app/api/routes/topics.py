from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import Client, TopicLens
from pr_monitor_app.schemas import TopicLensCreate, TopicLensOut

router = APIRouter(prefix="/topics", tags=["topics"])


@router.post("", response_model=TopicLensOut)
async def create_topic(payload: TopicLensCreate, session: AsyncSession = Depends(get_session)) -> TopicLensOut:
    c = (await session.execute(select(Client).where(Client.id == payload.client_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = (
        await session.execute(
            select(TopicLens).where(TopicLens.client_id == payload.client_id, TopicLens.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Topic with that name already exists for this client")

    t = TopicLens(
        client_id=payload.client_id,
        name=payload.name,
        description=payload.description,
        keywords=payload.keywords,
        competitor_overrides=payload.competitor_overrides,
        risk_flags=payload.risk_flags,
        opportunity_tags=payload.opportunity_tags,
        embedding=None,  # computed by pipeline
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return TopicLensOut.model_validate(t)


@router.get("", response_model=list[TopicLensOut])
async def list_topics(client_id: uuid.UUID | None = None, session: AsyncSession = Depends(get_session)) -> list[TopicLensOut]:
    q = select(TopicLens).order_by(TopicLens.created_at.desc())
    if client_id:
        q = q.where(TopicLens.client_id == client_id)
    rows = (await session.execute(q)).scalars().all()
    return [TopicLensOut.model_validate(r) for r in rows]


@router.get("/{topic_id}", response_model=TopicLensOut)
async def get_topic(topic_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> TopicLensOut:
    t = (await session.execute(select(TopicLens).where(TopicLens.id == topic_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    return TopicLensOut.model_validate(t)


@router.delete("/{topic_id}")
async def delete_topic(topic_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    t = (await session.execute(select(TopicLens).where(TopicLens.id == topic_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(t)
    await session.commit()
    return {"status": "deleted"}
