from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import AlertTier, ClientEvent
from pr_monitor_app.schemas import ClientEventOut

router = APIRouter(prefix="/client-events", tags=["client-events"])


@router.get("", response_model=list[ClientEventOut])
async def list_client_events(
    client_id: uuid.UUID | None = None,
    tier: AlertTier | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
) -> list[ClientEventOut]:
    q = select(ClientEvent).order_by(ClientEvent.created_at.desc()).limit(min(max(limit, 1), 1000))
    if client_id:
        q = q.where(ClientEvent.client_id == client_id)
    if tier:
        q = q.where(ClientEvent.tier == tier)
    rows = (await session.execute(q)).scalars().all()
    return [ClientEventOut.model_validate(r) for r in rows]
