from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any

import httpx

from outreach_app.gtm_service.core.config import Settings


class EmailDeliveryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.outbox_path.mkdir(parents=True, exist_ok=True)

    async def send_email(self, *, to_email: str, subject: str, body: str, metadata: dict[str, Any] | None = None) -> str:
        message = EmailMessage()
        message["From"] = formataddr((self.settings.smtp_from_name, self.settings.smtp_from_email))
        message["To"] = to_email
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=(self.settings.smtp_from_email.split("@", 1)[1] if "@" in self.settings.smtp_from_email else None))
        if self.settings.smtp_reply_to:
            message["Reply-To"] = self.settings.smtp_reply_to
        message.set_content(body)
        provider_message_id = message["Message-ID"]
        if not self.settings.allow_auto_send or not self.settings.smtp_ready:
            return await self._write_outbox(message, metadata)
        await asyncio.to_thread(self._smtp_send, message)
        return provider_message_id

    def _smtp_send(self, message: EmailMessage) -> None:
        if not self.settings.smtp_host:
            raise RuntimeError("SMTP host not configured")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as client:
            client.ehlo()
            if self.settings.smtp_use_tls:
                client.starttls()
                client.ehlo()
            if self.settings.smtp_username and self.settings.smtp_password:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)

    async def _write_outbox(self, message: EmailMessage, metadata: dict[str, Any] | None = None) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_to = message["To"].replace("@", "_at_").replace(".", "_")
        path = self.settings.outbox_path / f"{timestamp}_{safe_to}.eml"
        payload = message.as_bytes()
        if metadata:
            payload += ("\n\nX-Metadata: " + str(metadata) + "\n").encode()
        await asyncio.to_thread(path.write_bytes, payload)
        return str(path)


class LinkedInDispatchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self.client.aclose()

    async def dispatch(self, *, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not self.settings.linkedin_webhook_url:
            return "manual", {"task": payload}
        headers = {}
        if self.settings.linkedin_webhook_secret:
            headers["X-Webhook-Secret"] = self.settings.linkedin_webhook_secret
        response = await self.client.post(self.settings.linkedin_webhook_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json() if response.content else {}
        provider_id = str(data.get("id") or data.get("task_id") or "webhook")
        return provider_id, data
