from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.schemas.outreach import GeneratedMessage, SequencePreview
from outreach_app.gtm_service.services.research import ResearchOutput
from outreach_app.gtm_service.templates.sequences import APPROVED_METRIC_CLAIMS, SEQUENCES


class ClaimGuardrailError(ValueError):
    """Raised when generated copy violates approved-claims policy."""



class OutreachGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def preview_sequence(self, *, sequence_key: str, company_name: str, contact_first_name: str | None, research: ResearchOutput, now: datetime | None = None, partner_name: str | None = None) -> SequencePreview:
        template = SEQUENCES[sequence_key]
        context = self._build_context(sequence_key=sequence_key, company_name=company_name, contact_first_name=contact_first_name, research=research, partner_name=partner_name)
        messages: list[GeneratedMessage] = []
        for step in template.steps:
            subject = step.subject_template.format(**context) if step.subject_template else None
            body = step.body_template.format(**context)
            body = self._apply_claim_guardrails(body)
            if subject:
                subject = self._apply_claim_guardrails(subject)
            messages.append(GeneratedMessage(step_number=step.step_number, channel=step.channel, delay_days=step.delay_days, subject=subject, body=body, metadata_json={**step.metadata_json, "scheduled_local_date": self._scheduled_local_date(now=now, delay_days=step.delay_days)}))
        return SequencePreview(sequence_key=sequence_key, messages=messages)

    def _build_context(self, *, sequence_key: str, company_name: str, contact_first_name: str | None, research: ResearchOutput, partner_name: str | None) -> dict[str, str]:
        trigger_line = research.trigger_line or f"{company_name} shows activity consistent with validation pressure"
        trigger_short = research.trigger_short or trigger_line
        proof_line = self._proof_line(sequence_key)
        partner_intro = f"{partner_name} thought you might value this." if partner_name else research.partner_intro or "A partner thought this might be useful."
        return {
            "company_name": company_name,
            "first_name": contact_first_name or "there",
            "trigger_line": trigger_line,
            "trigger_short": trigger_short,
            "proof_line": proof_line,
            "partner_intro": partner_intro,
            "hook_subject": self._subject_hook(sequence_key, company_name, trigger_short),
        }

    def _proof_line(self, sequence_key: str) -> str:
        approved = self.settings.approved_proof_snippets
        metric_claim = {
            "technical_intro": APPROVED_METRIC_CLAIMS["cut_should_we_fund_cycles_42"],
            "productized_pilot_exec": APPROVED_METRIC_CLAIMS["clarified_go_no_go"],
            "social_warm_partner": APPROVED_METRIC_CLAIMS["board_memo_72h"],
            "investor_diligence": "Deterministic evidence can sharpen investment committee diligence before wet-lab burn ramps.",
            "founder_fundraising": "Portable proof can make fundraising scrutiny less narrative-dependent.",
        }.get(sequence_key, "Deterministic evidence helps replace prose with proof.")
        snippet = approved[0] if approved else "deterministic audit"
        if sequence_key == "technical_intro":
            return f"A recent run used {snippet} and {metric_claim}."
        if sequence_key == "productized_pilot_exec":
            return f"Typical pilot: 3 targets, 2 weeks, and we’ve {metric_claim}."
        if sequence_key == "social_warm_partner":
            return f"Last partner-led motion {metric_claim}."
        return metric_claim

    def _subject_hook(self, sequence_key: str, company_name: str, trigger_short: str) -> str:
        trigger_short = trigger_short.rstrip(".")
        if sequence_key == "technical_intro":
            return f"{trigger_short} → faster diligence signal"
        if sequence_key == "founder_fundraising":
            return f"{company_name}: fundraising proof, sealed"
        return f"{company_name}: deterministic diligence artifacts"

    def _scheduled_local_date(self, now: datetime | None, delay_days: int) -> str:
        zone = ZoneInfo(self.settings.sequence_timezone)
        anchor = now.astimezone(zone) if now else datetime.now(zone)
        return (anchor + timedelta(days=delay_days)).date().isoformat()

    def _apply_claim_guardrails(self, text: str) -> str:
        lower = text.lower()
        allowed_exact = [claim.lower() for claim in APPROVED_METRIC_CLAIMS.values()]
        for match in re.finditer(r"\b\d+%\b", lower):
            phrase = match.group(0)
            if not any(phrase in allowed for allowed in allowed_exact):
                raise ClaimGuardrailError(f"Unapproved metric claim detected: {phrase}")
        for pattern in [r"\btop campaign\b", r"\bbest-in-class\b", r"\bguarantee\b", r"\bzero risk\b"]:
            if re.search(pattern, lower):
                raise ClaimGuardrailError(f"Forbidden claim detected by pattern: {pattern}")
        return text
