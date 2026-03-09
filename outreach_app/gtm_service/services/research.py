from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput
from outreach_app.gtm_service.services.llm import LLMClient
from outreach_app.gtm_service.services.text_utils import safe_snippet, unique_preserve_order


class ExtractedSignal(BaseModel):
    type: str
    summary: str
    confidence: float = 0.65
    occurred_at: datetime | None = None


class ResearchOutput(BaseModel):
    icp_class: str
    persona_class: str
    why_now: list[str]
    pain_hypotheses: list[str]
    offer_recommendation: str
    sequence_recommendation: str
    proof_angle: str
    trigger_line: str
    trigger_short: str
    partner_intro: str
    extracted_signals: list[ExtractedSignal] = Field(default_factory=list)
    confidence: float = 0.65


TITLE_MAP = {
    "founder": "founder",
    "ceo": "founder",
    "cso": "founder",
    "chief scientific officer": "founder",
    "business development": "vp_bd",
    "strategy": "vp_bd",
    "director": "technical_lead",
    "platform": "technical_lead",
    "computational biology": "technical_lead",
    "translational": "technical_lead",
    "partner": "partner",
    "alliances": "partner",
    "investor": "investor",
    "principal": "investor",
}


class ResearchAgent:
    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    async def research(self, *, company: CandidateCompanyInput, contact: CandidateContactInput | None, snippets: list[str], existing_signals: list[dict[str, Any]] | None = None) -> ResearchOutput:
        heuristic = self._heuristic_research(company=company, contact=contact, snippets=snippets, existing_signals=existing_signals or [])
        if not self.settings.llm_ready or self.llm_client is None:
            return heuristic
        system_prompt = "You are a B2B lead research analyst for Glassbox Bio. Extract only structured sales intelligence. Return strict JSON."
        user_prompt = (
            f"Company: {company.model_dump_json()}\n"
            f"Contact: {contact.model_dump_json() if contact else 'null'}\n"
            f"Snippets: {snippets[: self.settings.max_signal_snippets]}\n"
            f"Existing signals: {existing_signals or []}\n"
            "Use icp_class in: ai_bio_startup, pharma_bd, investor, partner_hcls. "
            "Use persona_class in: founder, vp_bd, technical_lead, investor, partner. "
            "Recommend sequence in: technical_intro, productized_pilot_exec, social_warm_partner, investor_diligence, founder_fundraising. "
            "Recommend offer in: TRI Preview, Standard run, Deep run, 3-target pilot, investor memo."
        )
        try:
            llm_result = await self.llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=ResearchOutput)
            return self._merge(heuristic, llm_result)
        except Exception:
            return heuristic

    def _merge(self, heuristic: ResearchOutput, llm_result: ResearchOutput) -> ResearchOutput:
        merged = llm_result.model_copy(deep=True)
        merged.why_now = unique_preserve_order(llm_result.why_now + heuristic.why_now)
        merged.pain_hypotheses = unique_preserve_order(llm_result.pain_hypotheses + heuristic.pain_hypotheses)
        existing = {signal.type for signal in merged.extracted_signals}
        for signal in heuristic.extracted_signals:
            if signal.type not in existing:
                merged.extracted_signals.append(signal)
        merged.confidence = max(heuristic.confidence, llm_result.confidence)
        return merged

    def _heuristic_research(self, *, company: CandidateCompanyInput, contact: CandidateContactInput | None, snippets: list[str], existing_signals: list[dict[str, Any]]) -> ResearchOutput:
        merged_text = "\n".join(snippets + [item.get("raw_text", "") for item in existing_signals]).lower()
        persona_class = self._infer_persona_class(contact)
        icp_class = self._infer_icp_class(company, merged_text, persona_class)
        extracted_signals = self._extract_signals(snippets + [item.get("raw_text", "") for item in existing_signals])
        why_now = unique_preserve_order([signal.summary for signal in extracted_signals[:3]])
        pain_hypotheses = self._infer_pains(company, merged_text)
        sequence_recommendation, offer_recommendation = self._route(icp_class, persona_class, merged_text)
        trigger_short = why_now[0] if why_now else f"{company.name} is active in AI-bio"
        confidence = 0.55 + min(len(extracted_signals) * 0.05, 0.2)
        return ResearchOutput(
            icp_class=icp_class,
            persona_class=persona_class,
            why_now=why_now or [f"{company.name} shows activity consistent with validation pressure"],
            pain_hypotheses=pain_hypotheses,
            offer_recommendation=offer_recommendation,
            sequence_recommendation=sequence_recommendation,
            proof_angle=self._proof_angle(icp_class, persona_class),
            trigger_line=safe_snippet(trigger_short, 120),
            trigger_short=safe_snippet(trigger_short, 100),
            partner_intro="A partner on your side thought this might be relevant.",
            extracted_signals=extracted_signals,
            confidence=min(confidence, 0.9),
        )

    def _infer_persona_class(self, contact: CandidateContactInput | None) -> str:
        if not contact:
            return "founder"
        raw_title = (contact.title or contact.inferred_buying_role or "").lower()
        for needle, persona in TITLE_MAP.items():
            if needle in raw_title:
                return persona
        if any(term in raw_title for term in ["vp", "head", "chief"]):
            return "vp_bd"
        return "technical_lead"

    def _infer_icp_class(self, company: CandidateCompanyInput, merged_text: str, persona_class: str) -> str:
        company_text = " ".join(part for part in [company.name, company.industry or "", company.funding_stage or "", merged_text] if part).lower()
        if any(term in company_text for term in ["ventures", "capital", "fund", "investment"]):
            return "investor"
        if any(term in company_text for term in ["google cloud", "gcp", "marketplace", "co-sell", "partner"]):
            return "partner_hcls"
        if any(term in company_text for term in ["pharma", "portfolio", "asset strategy", "business development"]):
            return "pharma_bd"
        if any(term in company_text for term in ["ai", "drug discovery", "computational biology", "platform"]):
            return "ai_bio_startup"
        if persona_class == "investor":
            return "investor"
        return "ai_bio_startup"

    def _extract_signals(self, texts: list[str]) -> list[ExtractedSignal]:
        combined = [safe_snippet(text, 600) for text in texts if text.strip()]
        extracted: list[ExtractedSignal] = []
        now = datetime.now(timezone.utc)
        rules: list[tuple[str, str, str]] = [
            (r"\b(raised|series [abce]|seed round|financing)\b", "funding_event", "recent funding event"),
            (r"\b(hiring|job opening|careers|director, translational|computational biology role)\b", "hiring", "active hiring in relevant functions"),
            (r"\b(announced|launch(ed)?|introduced)\b", "launch", "recent platform or program announcement"),
            (r"\b(google cloud|gcp|marketplace)\b", "cloud_partner", "Google Cloud or GCP signal"),
            (r"\b(validation|reproducibility|diligence|target risk|board|investor)\b", "pain_signal", "language consistent with diligence pressure"),
            (r"\b(kras|egfr|target|program)\b", "target_claim", "public target or program claims"),
            (r"\b(publication|preprint|paper|poster)\b", "publication", "new publication or scientific disclosure"),
        ]
        for text in combined:
            lower = text.lower()
            for pattern, signal_type, summary in rules:
                if re.search(pattern, lower):
                    extracted.append(ExtractedSignal(type=signal_type, summary=summary, confidence=0.72, occurred_at=now))
        by_type: dict[str, ExtractedSignal] = {}
        for signal in extracted:
            current = by_type.get(signal.type)
            if current is None or signal.confidence > current.confidence:
                by_type[signal.type] = signal
        return list(by_type.values())

    def _infer_pains(self, company: CandidateCompanyInput, merged_text: str) -> list[str]:
        pains: list[str] = []
        if any(term in merged_text for term in ["reproducibility", "validation", "uncertainty"]):
            pains.append("target validation uncertainty")
        if any(term in merged_text for term in ["board", "portfolio", "capital allocation", "go/no-go"]):
            pains.append("board-level capital allocation pressure")
        if any(term in merged_text for term in ["fundraise", "investor", "proof"]):
            pains.append("fundraising proof burden")
        if any(term in merged_text for term in ["platform", "trust", "audit"]):
            pains.append("platform trust deficit")
        if company.funding_stage and company.funding_stage.lower() in {"seed", "series a", "series b"}:
            pains.append("need for fast prioritization before wet-lab spend")
        return unique_preserve_order(pains) or ["diligence friction around scientific claims"]

    def _route(self, icp_class: str, persona_class: str, merged_text: str) -> tuple[str, str]:
        if icp_class == "investor" or persona_class == "investor":
            return "investor_diligence", "investor memo"
        if icp_class == "partner_hcls" or persona_class == "partner":
            return "social_warm_partner", "Deep run"
        if persona_class == "technical_lead":
            return "technical_intro", "TRI Preview"
        if persona_class == "founder":
            return "founder_fundraising", "Standard run"
        if "pilot" in merged_text or persona_class == "vp_bd":
            return "productized_pilot_exec", "3-target pilot"
        return "productized_pilot_exec", "Standard run"

    def _proof_angle(self, icp_class: str, persona_class: str) -> str:
        if icp_class == "investor":
            return "independent diligence signal for investment committees"
        if persona_class == "technical_lead":
            return "artifact-level reproducibility and deterministic audit trails"
        if persona_class == "founder":
            return "fundraising credibility through sealed scientific proof"
        return "board-grade evidence with TRI risk bands"
