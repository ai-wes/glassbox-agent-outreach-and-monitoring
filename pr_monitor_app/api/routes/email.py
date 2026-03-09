from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.api.deps import get_session
from pr_monitor_app.config import settings
from pr_monitor_app.email.sender import build_email_sender
from pr_monitor_app.models import Client, EmailDirection, EmailMessage
from pr_monitor_app.schemas import EmailMessageOut, EmailReplyIn, EmailSendIn

router = APIRouter(prefix="/email", tags=["email"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_message_id(headers_blob: str) -> str | None:
    if not headers_blob:
        return None
    m = re.search(r"(?im)^message-id:\s*(.+)$", headers_blob)
    if m:
        return m.group(1).strip()
    return None


def _extract_in_reply_to(headers_blob: str) -> str | None:
    if not headers_blob:
        return None
    m = re.search(r"(?im)^in-reply-to:\s*(.+)$", headers_blob)
    if m:
        return m.group(1).strip()
    return None


def _extract_references(headers_blob: str) -> str | None:
    if not headers_blob:
        return None
    m = re.search(r"(?im)^references:\s*(.+)$", headers_blob)
    if m:
        return m.group(1).strip()
    return None


def _resolve_email(addr: str | None) -> str:
    raw = (addr or "").strip()
    if not raw:
        return ""
    _, parsed = parseaddr(raw)
    return (parsed or raw).strip().lower()


async def _authenticate_inbound(request: Request, secret: str | None = Query(default=None)) -> None:
    configured = (settings.email_inbound_secret or "").strip()
    if not configured:
        return
    provided = (
        request.headers.get("x-email-inbound-secret")
        or request.headers.get("x-inbound-secret")
        or (secret or "")
    ).strip()
    if provided != configured:
        raise HTTPException(status_code=401, detail="invalid inbound email secret")


@router.post("/inbound/sendgrid")
async def receive_sendgrid_inbound(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(_authenticate_inbound),
) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    payload: dict[str, Any]
    if "application/json" in content_type:
        payload = dict(await request.json())
    else:
        form = await request.form()
        payload = {k: v for k, v in form.items()}

    from_email = _resolve_email(str(payload.get("from") or payload.get("sender") or ""))
    to_email = _resolve_email(str(payload.get("to") or payload.get("recipient") or ""))
    subject = (payload.get("subject") or "").strip() or None
    text_body = (payload.get("text") or payload.get("body-plain") or "").strip() or None
    html_body = (payload.get("html") or payload.get("body-html") or "").strip() or None
    headers_blob = str(payload.get("headers") or "")

    if not from_email or not to_email:
        raise HTTPException(status_code=400, detail="missing from/to email")

    message_id = _extract_message_id(headers_blob)
    in_reply_to = _extract_in_reply_to(headers_blob)
    references = _extract_references(headers_blob)
    thread_id = in_reply_to or references or message_id

    client = (
        await session.execute(
            select(Client).where(func.lower(Client.email_recipient) == to_email)
        )
    ).scalar_one_or_none()

    msg = EmailMessage(
        client_id=client.id if client else None,
        direction=EmailDirection.inbound,
        provider="sendgrid",
        message_id=message_id,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        status="received",
        meta_json={"raw": payload},
        received_at=_now(),
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return {"status": "ok", "email_message_id": str(msg.id), "client_id": str(client.id) if client else None}


@router.get("/messages", response_model=list[EmailMessageOut])
async def list_email_messages(
    session: AsyncSession = Depends(get_session),
    client_id: uuid.UUID | None = None,
    direction: EmailDirection | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[EmailMessageOut]:
    q = select(EmailMessage).order_by(EmailMessage.created_at.desc()).limit(limit)
    if client_id:
        q = q.where(EmailMessage.client_id == client_id)
    if direction:
        q = q.where(EmailMessage.direction == direction)
    if status:
        q = q.where(EmailMessage.status == status.strip().lower())
    rows = (await session.execute(q)).scalars().all()
    return [EmailMessageOut.model_validate(r) for r in rows]


@router.get("/messages/{message_id}", response_model=EmailMessageOut)
async def get_email_message(message_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> EmailMessageOut:
    row = await session.get(EmailMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="email message not found")
    return EmailMessageOut.model_validate(row)


@router.post("/messages/{message_id}/reply", response_model=EmailMessageOut)
async def reply_to_email_message(
    message_id: uuid.UUID,
    payload: EmailReplyIn,
    session: AsyncSession = Depends(get_session),
) -> EmailMessageOut:
    original = await session.get(EmailMessage, message_id)
    if not original:
        raise HTTPException(status_code=404, detail="email message not found")
    if original.direction != EmailDirection.inbound:
        raise HTTPException(status_code=400, detail="can only reply to inbound messages")

    to_email = _resolve_email(payload.to_email or original.from_email)
    if not to_email:
        raise HTTPException(status_code=400, detail="missing recipient for reply")

    subj = (payload.subject or "").strip()
    if not subj:
        base = (original.subject or "").strip()
        subj = base if base.lower().startswith("re:") else f"Re: {base or 'Message'}"

    text_body = payload.body_text.strip()
    html_body = (payload.body_html or "").strip() or None

    sender = build_email_sender()
    thread_ref = original.thread_id or original.message_id

    try:
        send_res = await sender.send(
            recipient=to_email,
            subject=subj,
            body_text=text_body,
            body_html=html_body,
            in_reply_to=original.message_id,
            references=thread_ref,
        )
        sent_status = "sent" if send_res.ok else "failed"
        err = None
        provider_message_id = send_res.provider_message_id
    except Exception as exc:
        sent_status = "failed"
        err = str(exc)[:2000]
        provider_message_id = None

    out_msg = EmailMessage(
        client_id=original.client_id,
        direction=EmailDirection.outbound,
        provider="sendgrid",
        message_id=provider_message_id,
        thread_id=thread_ref or provider_message_id,
        in_reply_to=original.message_id,
        from_email=(settings.email_from or "").strip().lower(),
        to_email=to_email,
        subject=subj,
        text_body=text_body,
        html_body=html_body,
        status=sent_status,
        error_message=err,
        meta_json={"reply_to_email_message_id": str(original.id)},
        received_at=_now(),
        sent_at=_now() if sent_status == "sent" else None,
    )
    session.add(out_msg)
    await session.commit()
    await session.refresh(out_msg)
    return EmailMessageOut.model_validate(out_msg)


@router.post("/send", response_model=EmailMessageOut)
async def send_email(payload: EmailSendIn, session: AsyncSession = Depends(get_session)) -> EmailMessageOut:
    """Direct outbound email endpoint for ad-hoc sends (e.g. report dispatch)."""
    to_email = _resolve_email(payload.to)
    if not to_email:
        raise HTTPException(status_code=400, detail="invalid recipient email")

    subject = payload.subject.strip()
    text_body = payload.body_text.strip()
    html_body = (payload.body_html or "").strip() or None

    sender = build_email_sender()
    provider = (settings.email_provider or "sendgrid").strip().lower()
    from_email = _resolve_email(settings.email_from or "")

    if payload.client_id is not None:
        client = await session.get(Client, payload.client_id)
        if not client:
            raise HTTPException(status_code=404, detail="client not found")

    try:
        send_res = await sender.send(
            recipient=to_email,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
        )
        sent_status = "sent" if send_res.ok else "failed"
        err = None
        provider_message_id = send_res.provider_message_id
    except Exception as exc:
        sent_status = "failed"
        err = str(exc)[:2000]
        provider_message_id = None

    out_msg = EmailMessage(
        client_id=payload.client_id,
        direction=EmailDirection.outbound,
        provider=provider,
        message_id=provider_message_id,
        thread_id=provider_message_id,
        in_reply_to=None,
        from_email=from_email or "unknown@localhost",
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        status=sent_status,
        error_message=err,
        meta_json={"via": "api.send"},
        received_at=_now(),
        sent_at=_now() if sent_status == "sent" else None,
    )
    session.add(out_msg)
    await session.commit()
    await session.refresh(out_msg)
    return EmailMessageOut.model_validate(out_msg)

