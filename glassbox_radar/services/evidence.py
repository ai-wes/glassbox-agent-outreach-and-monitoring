from __future__ import annotations

from glassbox_radar.enums import EvidenceType, PublicationStatus, SourceType


HUMAN_RELEVANCE = {
    EvidenceType.HUMAN_DATA: 0.95,
    EvidenceType.GENETIC_VALIDATION: 0.6,
    EvidenceType.ANIMAL_MODEL: 0.35,
    EvidenceType.ORTHOGONAL_ASSAY: 0.45,
    EvidenceType.BIOMARKER: 0.7,
    EvidenceType.TOXICOLOGY: 0.4,
    EvidenceType.CMC: 0.2,
    EvidenceType.REPLICATION: 0.5,
}


def publication_status_for_source(source_type: SourceType) -> PublicationStatus:
    if source_type in {SourceType.BIORXIV, SourceType.MEDRXIV}:
        return PublicationStatus.PREPRINT
    if source_type == SourceType.PUBMED:
        return PublicationStatus.PEER_REVIEWED
    if source_type == SourceType.CLINICAL_TRIALS:
        return PublicationStatus.REGISTRY
    return PublicationStatus.CORPORATE


def human_relevance_for_evidence(evidence_type: EvidenceType) -> float:
    return HUMAN_RELEVANCE.get(evidence_type, 0.3)
