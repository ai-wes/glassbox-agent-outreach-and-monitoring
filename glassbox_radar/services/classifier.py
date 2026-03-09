from __future__ import annotations

import re
from collections.abc import Iterable

from glassbox_radar.contracts import CollectionContext, CollectedSignal
from glassbox_radar.enums import EvidenceType, MilestoneType, SignalType
from glassbox_radar.utils import compact_whitespace, normalize_text


MILESTONE_PATTERNS: dict[MilestoneType, list[re.Pattern[str]]] = {
    MilestoneType.PRE_IND: [
        re.compile(r"\bind[- ]?enabling\b", re.I),
        re.compile(r"\bglp tox(?:icology)?\b", re.I),
        re.compile(r"\btoxicology\b", re.I),
        re.compile(r"\bcmc\b", re.I),
        re.compile(r"\bmanufactur(?:e|ing)\b", re.I),
        re.compile(r"\bregulatory\b", re.I),
        re.compile(r"\bind submission\b", re.I),
    ],
    MilestoneType.FINANCING: [
        re.compile(r"\bseries [abcde]\b", re.I),
        re.compile(r"\bfinancing\b", re.I),
        re.compile(r"\bprivate placement\b", re.I),
        re.compile(r"\braised?\b", re.I),
        re.compile(r"\bventure financing\b", re.I),
        re.compile(r"\broadshow\b", re.I),
        re.compile(r"\binvestor presentation\b", re.I),
        re.compile(r"\brunway\b", re.I),
    ],
    MilestoneType.PARTNERING: [
        re.compile(r"\blicens(?:e|ing)\b", re.I),
        re.compile(r"\bpartner(?:ing)?\b", re.I),
        re.compile(r"\bstrategic alternatives\b", re.I),
        re.compile(r"\bbusiness development\b", re.I),
        re.compile(r"\bcollaboration\b", re.I),
        re.compile(r"\basset sale\b", re.I),
    ],
    MilestoneType.CLINICAL_TRANSITION: [
        re.compile(r"\bphase 1\b", re.I),
        re.compile(r"\bphase i\b", re.I),
        re.compile(r"\bfirst[- ]in[- ]human\b", re.I),
        re.compile(r"\btrial initiation\b", re.I),
        re.compile(r"\bdosed first patient\b", re.I),
        re.compile(r"\bclinical trial\b", re.I),
    ],
}

EVIDENCE_PATTERNS: dict[EvidenceType, list[re.Pattern[str]]] = {
    EvidenceType.ANIMAL_MODEL: [
        re.compile(r"\bmouse\b", re.I),
        re.compile(r"\bmurine\b", re.I),
        re.compile(r"\brat\b", re.I),
        re.compile(r"\bxenograft\b", re.I),
        re.compile(r"\bnon-human primate\b", re.I),
        re.compile(r"\bnhp\b", re.I),
    ],
    EvidenceType.HUMAN_DATA: [
        re.compile(r"\bpatient[- ]derived\b", re.I),
        re.compile(r"\bprimary human\b", re.I),
        re.compile(r"\bhuman biopsy\b", re.I),
        re.compile(r"\bpatient sample\b", re.I),
        re.compile(r"\bhuman cells?\b", re.I),
        re.compile(r"\bpbmc\b", re.I),
    ],
    EvidenceType.GENETIC_VALIDATION: [
        re.compile(r"\bcrispr\b", re.I),
        re.compile(r"\bknockout\b", re.I),
        re.compile(r"\bknockdown\b", re.I),
        re.compile(r"\bsiRNA\b", re.I),
        re.compile(r"\bshRNA\b", re.I),
        re.compile(r"\boverexpression\b", re.I),
    ],
    EvidenceType.ORTHOGONAL_ASSAY: [
        re.compile(r"\borthogonal\b", re.I),
        re.compile(r"\bindependent assay\b", re.I),
        re.compile(r"\bmultiple assays?\b", re.I),
        re.compile(r"\bvalidated across\b", re.I),
    ],
    EvidenceType.BIOMARKER: [
        re.compile(r"\bbiomarker\b", re.I),
        re.compile(r"\bpharmacodynamic\b", re.I),
        re.compile(r"\btarget engagement\b", re.I),
    ],
    EvidenceType.TOXICOLOGY: [
        re.compile(r"\btoxicology\b", re.I),
        re.compile(r"\btox\b", re.I),
        re.compile(r"\bsafety pharmacology\b", re.I),
    ],
    EvidenceType.CMC: [
        re.compile(r"\bcmc\b", re.I),
        re.compile(r"\bmanufactur(?:e|ing)\b", re.I),
        re.compile(r"\bprocess development\b", re.I),
    ],
    EvidenceType.REPLICATION: [
        re.compile(r"\breplicat(?:ed|ion)\b", re.I),
        re.compile(r"\breproduced\b", re.I),
        re.compile(r"\bvalidated independently\b", re.I),
    ],
}


def _match_patterns(text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def classify_signal(
    signal: CollectedSignal,
    context: CollectionContext,
) -> CollectedSignal:
    text = compact_whitespace(" ".join(filter(None, [signal.title, signal.summary, signal.content])))
    normalized = normalize_text(text)

    milestone_tags = list(signal.milestone_tags)
    for milestone_type, patterns in MILESTONE_PATTERNS.items():
        if _match_patterns(normalized, patterns):
            milestone_tags.append(milestone_type.value)

    evidence_tags = list(signal.evidence_tags)
    for evidence_type, patterns in EVIDENCE_PATTERNS.items():
        if _match_patterns(normalized, patterns):
            evidence_tags.append(evidence_type.value)

    signal_type = signal.signal_type
    if any(tag == MilestoneType.FINANCING.value for tag in milestone_tags):
        signal_type = SignalType.FINANCING_EVENT
    elif any(tag == MilestoneType.PARTNERING.value for tag in milestone_tags):
        signal_type = SignalType.PARTNERING_EVENT

    if re.search(r"\b(cfo|chief financial officer|vp finance)\b", normalized):
        signal_type = SignalType.EXECUTIVE_HIRE
        milestone_tags.append(MilestoneType.FINANCING.value)

    if re.search(r"\b(head of bd|business development|vp partnering)\b", normalized):
        signal_type = SignalType.EXECUTIVE_HIRE
        milestone_tags.append(MilestoneType.PARTNERING.value)

    if signal.source_url and context.domain and context.domain.lower() in signal.source_url.lower():
        signal.confidence = min(1.0, max(signal.confidence, 0.8))

    signal.signal_type = signal_type
    signal.evidence_tags = sorted(set(evidence_tags))
    signal.milestone_tags = sorted(set(milestone_tags))
    return signal
