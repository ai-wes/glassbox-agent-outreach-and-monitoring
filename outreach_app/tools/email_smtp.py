from __future__ import annotations

import hashlib
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.orchestrator.policy import RiskTier
from app.tools.base import Tool, ToolContext, ToolResult


class SmtpEmailTool(Tool):
    name = "email.send_smtp"
    risk_tier = int(RiskTier.TIER2_EXTERNAL_IMPACT)
    description = "Send an email over SMTP and store an .eml copy as evidence."

    def _allowlisted(self, to_addr: str) -> bool:
        addr = to_addr.strip().lower()
        if settings.email_addresses():
            return addr in settings.email_addresses()
        if settings.email_domains():
            if "@" not in addr:
                return False
            return addr.split("@", 1)[1] in settings.email_domains()
        return True

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.dry_run:
            raise PermissionError("Dry-run blocks email sending.")

        to_addr = kwargs["to"]
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")
        cc = kwargs.get("cc", [])
        bcc = kwargs.get("bcc", [])

        if not self._allowlisted(to_addr):
            raise PermissionError("Recipient is not allowlisted.")

        if not (settings.smtp_host and settings.smtp_user and settings.smtp_pass and settings.smtp_from):
            raise RuntimeError("SMTP not configured. Set SMTP_HOST/USER/PASS/FROM.")

        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = to_addr
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)

        eid = ctx.evidence.next_evidence_id("EMAIL")
        eml_name = f"{eid}_{to_addr.replace('@', '_at_')}.eml"
        eml_path, _ = ctx.evidence.store_artifact_bytes(eml_name, msg.as_bytes())
        digest = hashlib.sha256(Path(eml_path).read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="email_eml", path=Path(eml_path), sha256=digest, metadata={"to": to_addr, "subject": subject})

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg, from_addr=settings.smtp_from, to_addrs=[to_addr] + cc + bcc)

        return ToolResult(ok=True, output={"to": to_addr, "subject": subject, "eml_path": str(eml_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "email_eml", "path": str(eml_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=True)
