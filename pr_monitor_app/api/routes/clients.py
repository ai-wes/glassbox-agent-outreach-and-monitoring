from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.models import Client
from pr_monitor_app.schemas import ClientCreate, ClientOut

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientOut)
async def create_client(payload: ClientCreate, session: AsyncSession = Depends(get_session)) -> ClientOut:
    existing = (await session.execute(select(Client).where(Client.name == payload.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Client with that name already exists")

    c = Client(
        name=payload.name,
        messaging_pillars=payload.messaging_pillars,
        risk_keywords=payload.risk_keywords,
        audience_profile=payload.audience_profile,
        brand_voice_profile=payload.brand_voice_profile,
        competitors=payload.competitors,
        signal_recipient=payload.signal_recipient,
        telegram_recipient=payload.telegram_recipient,
        whatsapp_recipient=payload.whatsapp_recipient,
        email_recipient=payload.email_recipient,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return ClientOut.model_validate(c)


@router.get("", response_model=list[ClientOut])
async def list_clients(session: AsyncSession = Depends(get_session)) -> list[ClientOut]:
    rows = (await session.execute(select(Client).order_by(Client.created_at.desc()))).scalars().all()
    return [ClientOut.model_validate(r) for r in rows]


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> ClientOut:
    c = (await session.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    return ClientOut.model_validate(c)


@router.delete("/{client_id}")
async def delete_client(client_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    c = (await session.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(c)
    await session.commit()
    return {"status": "deleted"}
