from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import EngagementFeedback
from pr_monitor_app.schemas import FeedbackCreate

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
async def create_feedback(payload: FeedbackCreate, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    fb = EngagementFeedback(
        client_id=payload.client_id,
        client_event_id=payload.client_event_id,
        action_taken=payload.action_taken,
        notes=payload.notes,
    )
    session.add(fb)
    await session.commit()
    return {"status": "ok"}
