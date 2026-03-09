from __future__ import annotations

from collections.abc import Sequence

import httpx

from glassbox_radar.connectors.base import Collector
from glassbox_radar.contracts import CollectedSignal, CollectionContext
from glassbox_radar.core.config import get_settings
from glassbox_radar.enums import SignalType, SourceType
from glassbox_radar.utils import compact_whitespace, safe_parse_datetime


class ClinicalTrialsCollector(Collector):
    url = "https://clinicaltrials.gov/api/query/full_studies"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _query(self, context: CollectionContext) -> str:
        high_value_terms = [context.asset_name, context.target, context.company_name, context.indication]
        filtered = [f'"{value}"' for value in high_value_terms if value]
        return " OR ".join(filtered[:3])

    async def collect(self, context: CollectionContext, client: httpx.AsyncClient) -> Sequence[CollectedSignal]:
        query = self._query(context)
        if not query:
            return []

        params = {
            "expr": query,
            "min_rnk": 1,
            "max_rnk": self.settings.clinical_trials_max_rank,
            "fmt": "JSON",
        }
        response = await client.get(self.url, params=params)
        response.raise_for_status()
        payload = response.json()
        studies = payload.get("FullStudiesResponse", {}).get("FullStudies", [])

        signals: list[CollectedSignal] = []
        for item in studies:
            study = item.get("Study", {})
            protocol = study.get("ProtocolSection", {})
            identification = protocol.get("IdentificationModule", {})
            status = protocol.get("StatusModule", {})
            design = protocol.get("DesignModule", {})
            description = protocol.get("DescriptionModule", {})
            conditions = protocol.get("ConditionsModule", {})

            title = compact_whitespace(identification.get("OfficialTitle") or identification.get("BriefTitle"))
            condition_text = ", ".join(conditions.get("ConditionList", {}).get("Condition", [])[:5])
            phase_text = ", ".join(design.get("PhaseList", {}).get("Phase", [])[:3]) if design.get("PhaseList") else ""
            status_text = status.get("OverallStatus")
            content = compact_whitespace(
                " | ".join(
                    fragment
                    for fragment in [
                        description.get("BriefSummary"),
                        condition_text,
                        phase_text,
                        status_text,
                    ]
                    if fragment
                )
            )
            published_at = safe_parse_datetime(
                status.get("StudyFirstPostDateStruct", {}).get("StudyFirstPostDate")
                or status.get("StartDateStruct", {}).get("StartDate")
            )
            nct_id = identification.get("NCTId")
            signals.append(
                CollectedSignal(
                    source_type=SourceType.CLINICAL_TRIALS,
                    signal_type=SignalType.CLINICAL_TRIAL_UPDATE,
                    title=title or f"ClinicalTrials study {nct_id or ''}".strip(),
                    summary=compact_whitespace(
                        " | ".join(
                            fragment
                            for fragment in [
                                f"NCT: {nct_id}" if nct_id else None,
                                f"Status: {status_text}" if status_text else None,
                                f"Phase: {phase_text}" if phase_text else None,
                                f"Conditions: {condition_text}" if condition_text else None,
                            ]
                            if fragment
                        )
                    )
                    or None,
                    content=content or title,
                    source_url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "https://clinicaltrials.gov/",
                    published_at=published_at,
                    confidence=0.78,
                    raw_payload=study,
                    milestone_tags=["clinical_transition"] if phase_text else [],
                )
            )
        return signals
