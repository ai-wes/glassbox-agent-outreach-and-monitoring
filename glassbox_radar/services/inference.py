from __future__ import annotations

from collections import Counter
from datetime import timedelta

from glassbox_radar.contracts import MilestoneInference
from glassbox_radar.enums import MilestoneType
from glassbox_radar.models import Program, Signal
from glassbox_radar.utils import days_from_now, utcnow


def infer_milestone(program: Program, signals: list[Signal]) -> MilestoneInference:
    weighted = Counter[MilestoneType]()
    rationale: list[str] = []

    stage = (program.stage or "").lower()
    if "ind-enabling" in stage:
        weighted[MilestoneType.PRE_IND] += 3
        rationale.append("Program stage already marked as IND-enabling.")
    elif "preclinical" in stage:
        weighted[MilestoneType.PRE_IND] += 1
        rationale.append("Program stage is preclinical, which biases toward pre-IND execution.")
    elif "phase 1" in stage or "phase i" in stage:
        weighted[MilestoneType.CLINICAL_TRANSITION] += 4
        rationale.append("Program stage references Phase 1 readiness.")

    for signal in signals:
        for tag in signal.milestone_tags:
            try:
                weighted[MilestoneType(tag)] += 2
            except ValueError:
                continue

        text = " ".join(filter(None, [signal.title, signal.summary, signal.content or ""]))
        lower = text.lower()

        if "cfo" in lower or "runway" in lower:
            weighted[MilestoneType.FINANCING] += 2
            rationale.append(f"{signal.title}: finance-related language detected.")
        if "business development" in lower or "partnering" in lower or "license" in lower:
            weighted[MilestoneType.PARTNERING] += 2
            rationale.append(f"{signal.title}: partnering-related language detected.")
        if "first-in-human" in lower or "phase 1" in lower or "phase i" in lower:
            weighted[MilestoneType.CLINICAL_TRANSITION] += 3
            rationale.append(f"{signal.title}: clinical transition language detected.")
        if "ind-enabling" in lower or "toxicology" in lower or "cmc" in lower:
            weighted[MilestoneType.PRE_IND] += 3
            rationale.append(f"{signal.title}: IND preparation language detected.")

    if not weighted:
        return MilestoneInference(
            milestone_type=MilestoneType.UNKNOWN,
            confidence=0.0,
            window_start=None,
            window_end=None,
            rationale=["No milestone-specific evidence found."],
        )

    milestone_type, total_weight = weighted.most_common(1)[0]
    total_sum = sum(weighted.values())
    confidence = min(1.0, total_weight / max(total_sum, 1))

    if milestone_type == MilestoneType.PRE_IND:
        window_start = days_from_now(60)
        window_end = days_from_now(180)
    elif milestone_type == MilestoneType.FINANCING:
        window_start = days_from_now(15)
        window_end = days_from_now(120)
    elif milestone_type == MilestoneType.PARTNERING:
        window_start = days_from_now(30)
        window_end = days_from_now(180)
    elif milestone_type == MilestoneType.CLINICAL_TRANSITION:
        window_start = days_from_now(30)
        window_end = days_from_now(150)
    else:
        window_start = None
        window_end = None

    if signals:
        newest = max((signal.published_at for signal in signals if signal.published_at), default=None)
        if newest and window_start and window_end:
            if milestone_type == MilestoneType.FINANCING:
                window_start = newest.date()
                window_end = (newest + timedelta(days=90)).date()
            elif milestone_type == MilestoneType.PRE_IND:
                window_start = (newest + timedelta(days=45)).date()
                window_end = (newest + timedelta(days=180)).date()
            elif milestone_type == MilestoneType.PARTNERING:
                window_start = (newest + timedelta(days=30)).date()
                window_end = (newest + timedelta(days=150)).date()
            elif milestone_type == MilestoneType.CLINICAL_TRANSITION:
                window_start = (newest + timedelta(days=21)).date()
                window_end = (newest + timedelta(days=120)).date()

    return MilestoneInference(
        milestone_type=milestone_type,
        confidence=confidence,
        window_start=window_start,
        window_end=window_end,
        rationale=rationale[:8] or [f"Inferred {milestone_type.value} from recent evidence."],
    )
