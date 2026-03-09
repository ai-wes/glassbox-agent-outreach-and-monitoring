from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import build

from glassbox_radar.contracts import OpportunityScore
from glassbox_radar.core.config import get_settings
from glassbox_radar.models import Company, Contact, Opportunity, Program


class OpportunitySheetsExporter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._service = None

    async def export_opportunity(
        self,
        company: Company,
        program: Program,
        contact: Contact | None,
        opportunity: Opportunity,
        score: OpportunityScore,
    ) -> dict[str, Any]:
        spreadsheet_id = self.settings.opportunities_sheet_spreadsheet_id
        if spreadsheet_id is None:
            return {}

        values = [[
            datetime.now(tz=UTC).isoformat(),
            company.id,
            company.name,
            company.domain or "",
            program.id,
            program.asset_name or "",
            program.target or "",
            program.modality or "",
            program.indication or "",
            contact.name if contact else "",
            contact.email if contact and contact.email else "",
            opportunity.id,
            score.radar_score,
            score.milestone_score,
            score.fragility_score,
            score.capital_score,
            score.reachability_score,
            score.tier or "",
            score.milestone_type.value,
            score.milestone_window_start.isoformat() if score.milestone_window_start else "",
            score.milestone_window_end.isoformat() if score.milestone_window_end else "",
            score.primary_buyer_role or "",
            score.outreach_angle or "",
            score.risk_hypothesis or "",
            opportunity.dossier_path or "",
        ]]

        response = (
            self._client()
            .spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=self.settings.opportunities_sheet_range_a1,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )
        updates = response.get("updates", {})
        return {
            "spreadsheet_id": spreadsheet_id,
            "sheet_range": self.settings.opportunities_sheet_range_a1,
            "updated_range": updates.get("updatedRange"),
            "updated_rows": updates.get("updatedRows"),
        }

    def _client(self):
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import service_account
            import google.auth
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('Google extras not installed. Run: pip install ".[google]"') from exc

        creds = None
        if self.settings.google_sheets_service_account_json:
            info = json.loads(self.settings.google_sheets_service_account_json)
            creds = service_account.Credentials.from_service_account_info(
                info,
                scopes=self.settings.sheets_scopes(),
            )
        else:
            creds, _ = google.auth.default(scopes=self.settings.sheets_scopes())

        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return self._service
