from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput
from outreach_app.gtm_service.services.llm import LLMClient
from outreach_app.gtm_service.services.research import ResearchOutput


class ScoringAdjustment(BaseModel):
    company_fit_delta: int = 0
    persona_fit_delta: int = 0
    trigger_strength_delta: int = 0
    pain_fit_delta: int = 0
    reachability_delta: int = 0
    rationale: list[str] = []
    confidence: float = 0.0


class ScoreBreakdown(BaseModel):
    company_fit: int
    persona_fit: int
    trigger_strength: int
    pain_fit: int
    reachability: int
    total_score: int
    lead_grade: str
    rationale: dict[str, Any]
    model_confidence: float


class LeadScoringService:
    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    async def score(self, *, company: CandidateCompanyInput, contact: CandidateContactInput | None, research: ResearchOutput, signal_count: int) -> ScoreBreakdown:
        base = self._rule_score(company=company, contact=contact, research=research, signal_count=signal_count)
        if not self.settings.llm_ready or self.llm_client is None:
            return base
        try:
            adjustment = await self.llm_client.generate_json(
                system_prompt="You are calibrating a lead score. Only apply small adjustments if evidence clearly supports it. Return strict JSON.",
                user_prompt=(
                    f"Company={company.model_dump_json()}\n"
                    f"Contact={contact.model_dump_json() if contact else 'null'}\n"
                    f"Research={research.model_dump_json()}\n"
                    f"Base score={base.model_dump_json()}\n"
                    "Each delta must be between -3 and +3."
                ),
                schema=ScoringAdjustment,
            )
            return self._apply_adjustment(base, adjustment)
        except Exception:
            return base

    def _rule_score(self, *, company: CandidateCompanyInput, contact: CandidateContactInput | None, research: ResearchOutput, signal_count: int) -> ScoreBreakdown:
        company_fit = persona_fit = trigger_strength = pain_fit = reachability = 0
        rationale: dict[str, Any] = {"company_fit": [], "persona_fit": [], "trigger_strength": [], "pain_fit": [], "reachability": []}
        icp = research.icp_class
        persona = research.persona_class
        if icp == "ai_bio_startup":
            company_fit += 18
            rationale["company_fit"].append("AI-bio startup fit")
        elif icp == "pharma_bd":
            company_fit += 20
            rationale["company_fit"].append("pharma BD fit")
        elif icp == "investor":
            company_fit += 17
            rationale["company_fit"].append("investor fit")
        elif icp == "partner_hcls":
            company_fit += 19
            rationale["company_fit"].append("partner/HCLS fit")
        if company.industry and any(term in company.industry.lower() for term in ["biotech", "pharma", "life", "bio"]):
            company_fit += 5
            rationale["company_fit"].append("industry relevance")
        if company.funding_stage and company.funding_stage.lower() in {"seed", "series a", "series b", "growth"}:
            company_fit += 2
            rationale["company_fit"].append("fundable stage")
        persona_fit += {"technical_lead": 17, "vp_bd": 18, "founder": 19, "investor": 18, "partner": 16}.get(persona, 10)
        rationale["persona_fit"].append(f"persona={persona}")
        if contact and contact.title and any(term in contact.title.lower() for term in ["chief", "vp", "head", "director", "partner", "principal"]):
            persona_fit += 2
            rationale["persona_fit"].append("seniority present")
        trigger_strength += min(signal_count * 5, 15)
        rationale["trigger_strength"].append(f"signal_count={signal_count}")
        if research.why_now:
            trigger_strength += min(len(research.why_now) * 3, 10)
            rationale["trigger_strength"].append("why_now signals present")
        if any("funding" in item.lower() for item in research.why_now):
            trigger_strength += 3
            rationale["trigger_strength"].append("fresh funding trigger")
        if any("google cloud" in item.lower() or "gcp" in item.lower() for item in research.why_now):
            trigger_strength += 2
            rationale["trigger_strength"].append("cloud trigger")
        pain_fit += min(len(research.pain_hypotheses) * 5, 15)
        rationale["pain_fit"].append(f"pain_count={len(research.pain_hypotheses)}")
        if any(term in " ".join(research.pain_hypotheses).lower() for term in ["validation", "diligence", "proof"]):
            pain_fit += 5
            rationale["pain_fit"].append("core Glassbox pain")
        if contact and contact.email:
            reachability += 6
            rationale["reachability"].append("email present")
        if contact and contact.linkedin_url:
            reachability += 2
            rationale["reachability"].append("linkedin present")
        if contact and contact.email_verified:
            reachability += 2
            rationale["reachability"].append("email verified")
        company_fit = min(company_fit, 25)
        persona_fit = min(persona_fit, 20)
        trigger_strength = min(trigger_strength, 25)
        pain_fit = min(pain_fit, 20)
        reachability = min(reachability, 10)
        total = company_fit + persona_fit + trigger_strength + pain_fit + reachability
        return ScoreBreakdown(
            company_fit=company_fit,
            persona_fit=persona_fit,
            trigger_strength=trigger_strength,
            pain_fit=pain_fit,
            reachability=reachability,
            total_score=total,
            lead_grade=self._grade(total),
            rationale=rationale,
            model_confidence=research.confidence,
        )

    def _apply_adjustment(self, base: ScoreBreakdown, adjustment: ScoringAdjustment) -> ScoreBreakdown:
        company_fit = max(0, min(25, base.company_fit + adjustment.company_fit_delta))
        persona_fit = max(0, min(20, base.persona_fit + adjustment.persona_fit_delta))
        trigger_strength = max(0, min(25, base.trigger_strength + adjustment.trigger_strength_delta))
        pain_fit = max(0, min(20, base.pain_fit + adjustment.pain_fit_delta))
        reachability = max(0, min(10, base.reachability + adjustment.reachability_delta))
        total = company_fit + persona_fit + trigger_strength + pain_fit + reachability
        rationale = dict(base.rationale)
        rationale["llm_adjustment"] = adjustment.rationale
        return ScoreBreakdown(
            company_fit=company_fit,
            persona_fit=persona_fit,
            trigger_strength=trigger_strength,
            pain_fit=pain_fit,
            reachability=reachability,
            total_score=total,
            lead_grade=self._grade(total),
            rationale=rationale,
            model_confidence=max(base.model_confidence, adjustment.confidence),
        )

    def _grade(self, total: int) -> str:
        if total >= self.settings.grade_a_min:
            return "A"
        if total >= self.settings.grade_b_min:
            return "B"
        if total >= self.settings.grade_c_min:
            return "C"
        return "D"
