from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    PUBMED = "pubmed"
    BIORXIV = "biorxiv"
    MEDRXIV = "medrxiv"
    CLINICAL_TRIALS = "clinical_trials"
    RSS = "rss"


class SignalType(StrEnum):
    PUBLICATION = "publication"
    PREPRINT = "preprint"
    CLINICAL_TRIAL_UPDATE = "clinical_trial_update"
    PRESS_RELEASE = "press_release"
    FINANCING_EVENT = "financing_event"
    PARTNERING_EVENT = "partnering_event"
    EXECUTIVE_HIRE = "executive_hire"
    OTHER = "other"


class EvidenceType(StrEnum):
    ANIMAL_MODEL = "animal_model"
    HUMAN_DATA = "human_data"
    GENETIC_VALIDATION = "genetic_validation"
    ORTHOGONAL_ASSAY = "orthogonal_assay"
    BIOMARKER = "biomarker"
    TOXICOLOGY = "toxicology"
    CMC = "cmc"
    REPLICATION = "replication"


class PublicationStatus(StrEnum):
    PREPRINT = "preprint"
    PEER_REVIEWED = "peer_reviewed"
    CORPORATE = "corporate"
    REGISTRY = "registry"
    UNKNOWN = "unknown"


class MilestoneType(StrEnum):
    PRE_IND = "pre_ind"
    FINANCING = "financing"
    PARTNERING = "partnering"
    CLINICAL_TRANSITION = "clinical_transition"
    UNKNOWN = "unknown"


class OpportunityStatus(StrEnum):
    DETECTED = "detected"
    VALIDATED = "validated"
    OUTREACH_QUEUED = "outreach_queued"
    CONTACTED = "contacted"
    DIAGNOSTIC_CALL = "diagnostic_call"
    SNAPSHOT_PROPOSED = "snapshot_proposed"
    SNAPSHOT_LIVE = "snapshot_live"
    AUDIT_PROPOSED = "audit_proposed"
    AUDIT_WON = "audit_won"
    CLOSED_LOST = "closed_lost"


class PipelineRunStatus(StrEnum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
