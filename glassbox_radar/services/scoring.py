from __future__ import annotations

from collections import Counter
from datetime import date

from glassbox_radar.contracts import CollectionContext, MilestoneInference, OpportunityScore
from glassbox_radar.enums import EvidenceType, MilestoneType
from glassbox_radar.models import EvidenceNode, Program


CAPITAL_BANDS = {
    "small molecule": ("$8M-$20M", 65.0),
    "antibody": ("$12M-$30M", 72.0),
    "protein": ("$12M-$28M", 70.0),
    "gene therapy": ("$25M-$80M", 90.0),
    "cell therapy": ("$30M-$100M", 92.0),
    "rna": ("$18M-$45M", 80.0),
    "default": ("$10M-$35M", 68.0),
}


def _milestone_score(inference: MilestoneInference) -> float:
    if not inference.window_end:
        return 0.0
    days = (inference.window_end - date.today()).days
    if days <= 90:
        base = 95.0
    elif days <= 180:
        base = 80.0
    elif days <= 270:
        base = 62.0
    else:
        base = 45.0
    return round(base * max(inference.confidence, 0.35), 2)


def _fragility_score(program: Program, evidence_nodes: list[EvidenceNode], signals_text: str) -> float:
    base = 62.0
    evidence_counter = Counter(node.evidence_type for node in evidence_nodes)
    distinct_families = len(evidence_counter)
    human_relevance = sum(node.human_relevance_score for node in evidence_nodes) / max(len(evidence_nodes), 1)
    orthogonal = any(node.orthogonality_tag for node in evidence_nodes)
    replication = any(node.replication_signal for node in evidence_nodes)

    if distinct_families == 0:
        base += 18.0
    elif distinct_families == 1:
        base += 10.0
    elif distinct_families >= 4:
        base -= 12.0

    if evidence_counter.get(EvidenceType.HUMAN_DATA, 0) == 0:
        base += 15.0
    if evidence_counter.get(EvidenceType.GENETIC_VALIDATION, 0) == 0:
        base += 7.0
    if not orthogonal:
        base += 8.0
    if not replication:
        base += 5.0
    if human_relevance >= 0.7:
        base -= 12.0
    elif human_relevance <= 0.3:
        base += 8.0

    if "first-in-class" in signals_text or "novel target" in signals_text or "unprecedented" in signals_text:
        base += 8.0
    if "validated across multiple" in signals_text or "independent replication" in signals_text:
        base -= 8.0

    return max(5.0, min(98.0, round(base, 2)))


def _capital_score(program: Program, milestone_type: MilestoneType) -> tuple[str, float]:
    modality = (program.modality or "").lower()
    for key, (band, score) in CAPITAL_BANDS.items():
        if key in modality:
            if milestone_type == MilestoneType.CLINICAL_TRANSITION:
                return band, min(100.0, score + 5.0)
            return band, score
    band, score = CAPITAL_BANDS["default"]
    return band, score + (5.0 if milestone_type == MilestoneType.CLINICAL_TRANSITION else 0.0)


def _reachability_score(context: CollectionContext) -> tuple[float, str]:
    score = 30.0
    primary_buyer = "CSO"

    if context.contacts:
        score += 15.0
        if any((contact.role or "").lower() in {"ceo", "chief executive officer"} for contact in context.contacts):
            primary_buyer = "CEO"
            score += 8.0
        elif any((contact.role or "").lower() in {"cso", "chief scientific officer"} for contact in context.contacts):
            primary_buyer = "CSO"
            score += 8.0

    if context.warm_intro_paths:
        score += min(20.0, 5.0 * len(context.warm_intro_paths))
    if context.investors:
        score += min(15.0, 2.0 * len(context.investors))
        if primary_buyer == "CSO":
            primary_buyer = "CEO / Lead Investor"
    if context.board_members:
        score += min(10.0, 2.0 * len(context.board_members))
    if context.domain:
        score += 5.0

    return min(95.0, score), primary_buyer


def _tier(window_end: date | None) -> str:
    if not window_end:
        return "C"
    days = (window_end - date.today()).days
    if days <= 120:
        return "A"
    if days <= 240:
        return "B"
    return "C"


def _outreach_angle(milestone_type: MilestoneType, fragility_score: float) -> tuple[str, str]:
    if milestone_type == MilestoneType.PRE_IND:
        return (
            "Pre-IND mechanistic stress test",
            "A near-term IND package appears to depend on a mechanistic assumption that may not yet be supported by diverse orthogonal evidence.",
        )
    if milestone_type == MilestoneType.FINANCING:
        return (
            "Financing-readiness confidence check",
            "The upcoming financing narrative may be carrying more mechanistic certainty than the current evidence stack can safely support.",
        )
    if milestone_type == MilestoneType.PARTNERING:
        return (
            "Partnering diligence support",
            "The asset appears to be entering a partnering window where independent validation of the target story could materially change negotiating leverage.",
        )
    if milestone_type == MilestoneType.CLINICAL_TRANSITION:
        return (
            "Clinical transition risk review",
            "The program is nearing clinical transition and the translational bridge from preclinical models to human biology remains a key dependency.",
        )
    if fragility_score >= 75:
        return (
            "Mechanistic fragility review",
            "The current evidence package appears concentrated in a narrow set of models and would benefit from an independent stress test before major commitment.",
        )
    return (
        "Program confidence review",
        "The program is entering a decision window where external validation can reduce avoidable biological and capital risk.",
    )


def score_program(
    program: Program,
    evidence_nodes: list[EvidenceNode],
    inference: MilestoneInference,
    context: CollectionContext,
    signals_text: str,
) -> OpportunityScore:
    milestone_score = _milestone_score(inference)
    fragility_score = _fragility_score(program, evidence_nodes, signals_text.lower())
    capital_exposure_band, capital_score = _capital_score(program, inference.milestone_type)
    reachability_score, primary_buyer = _reachability_score(context)

    radar_score = round(
        0.30 * milestone_score
        + 0.35 * fragility_score
        + 0.20 * capital_score
        + 0.15 * reachability_score,
        2,
    )
    outreach_angle, risk_hypothesis = _outreach_angle(inference.milestone_type, fragility_score)

    return OpportunityScore(
        milestone_score=milestone_score,
        fragility_score=fragility_score,
        capital_score=capital_score,
        reachability_score=reachability_score,
        radar_score=radar_score,
        milestone_type=inference.milestone_type,
        milestone_confidence=inference.confidence,
        milestone_window_start=inference.window_start,
        milestone_window_end=inference.window_end,
        primary_buyer_role=primary_buyer,
        outreach_angle=outreach_angle,
        risk_hypothesis=risk_hypothesis,
        capital_exposure_band=capital_exposure_band,
        tier=_tier(inference.window_end),
    )
