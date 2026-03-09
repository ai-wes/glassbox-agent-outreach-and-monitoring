from __future__ import annotations

from dataclasses import dataclass

from outreach_app.gtm_service.services.research import ResearchOutput


@dataclass(slots=True)
class RoutingDecision:
    sequence_key: str
    offer: str
    eligible: bool
    do_not_contact_reason: str | None = None


class LeadRouter:
    def route(self, *, lead_grade: str, research: ResearchOutput, has_email_or_linkedin: bool) -> RoutingDecision:
        if not has_email_or_linkedin:
            return RoutingDecision(sequence_key=research.sequence_recommendation, offer=research.offer_recommendation, eligible=False, do_not_contact_reason="No reachable channel")
        if lead_grade == "D":
            return RoutingDecision(sequence_key=research.sequence_recommendation, offer=research.offer_recommendation, eligible=False, do_not_contact_reason="Lead grade below minimum threshold")
        if lead_grade == "C":
            return RoutingDecision(sequence_key=research.sequence_recommendation, offer=research.offer_recommendation, eligible=False, do_not_contact_reason="Nurture only until stronger intent appears")
        return RoutingDecision(sequence_key=research.sequence_recommendation, offer=research.offer_recommendation, eligible=True)
