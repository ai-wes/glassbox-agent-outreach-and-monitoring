from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import Alert, AlertTier, NotificationChannel
from pr_monitor_app.schemas import AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    tier: AlertTier | None = None,
    channel: NotificationChannel | None = None,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
) -> list[AlertOut]:
    q = select(Alert).order_by(Alert.created_at.desc()).limit(min(max(limit, 1), 1000))
    if tier:
        q = q.where(Alert.tier == tier)
    if channel:
        q = q.where(Alert.channel == channel)
    rows = (await session.execute(q)).scalars().all()
    return [AlertOut.model_validate(r) for r in rows]
