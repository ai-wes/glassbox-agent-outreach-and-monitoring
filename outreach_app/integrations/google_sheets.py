from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings


class SheetsError(RuntimeError):
    """Base error for Google Sheets integration failures."""


class SheetsConfigurationError(SheetsError):
    """Raised when the service cannot build Sheets credentials/client."""


class SheetsRequestError(SheetsError):
    """Raised when the Google Sheets API rejects a request."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class SheetsClient:
    """
    Wrapper around Google Sheets API.

    Requires:
      pip install ".[google]"

    Auth:
      - Preferred: GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON (service account json string)
      - Alternative: GOOGLE_APPLICATION_CREDENTIALS (path) or ADC.
    """

    def __init__(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except Exception as e:
            raise SheetsConfigurationError('Google extras not installed. Run: pip install ".[google]"') from e

        scopes = settings.sheets_scopes()
        try:
            info = settings.sheets_service_account_info()
        except ValueError as e:
            raise SheetsConfigurationError(str(e)) from e
        if info is not None:
            try:
                creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                raise SheetsConfigurationError(
                    "Invalid GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON for Google Sheets auth."
                ) from e
        else:
            adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if adc_path:
                path = Path(adc_path)
                if not path.exists():
                    raise SheetsConfigurationError(
                        f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {adc_path}"
                    )
                try:
                    payload = json.loads(path.read_text())
                except Exception:
                    payload = None
                if isinstance(payload, dict) and "installed" in payload:
                    raise SheetsConfigurationError(
                        "GOOGLE_APPLICATION_CREDENTIALS points to an OAuth client-secret file "
                        "(`installed` JSON), not Application Default Credentials. Use a service "
                        "account JSON or an authorized_user ADC file."
                    )
            try:
                import google.auth
                creds, _ = google.auth.default(scopes=scopes)
            except Exception as e:
                raise SheetsConfigurationError(
                    "Google credentials not configured. Set GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON "
                    "or GOOGLE_APPLICATION_CREDENTIALS / Application Default Credentials. "
                    f"Underlying error: {e}"
                ) from e

        try:
            self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        except Exception as e:
            raise SheetsConfigurationError("Failed to initialize Google Sheets API client.") from e

    @staticmethod
    def _raise_request_error(exc: Exception) -> None:
        status_code = getattr(getattr(exc, "resp", None), "status", None) or 502
        message = str(exc)
        try:
            payload = exc.error_details[0]
            if isinstance(payload, dict):
                message = payload.get("message") or message
        except Exception:
            pass
        raise SheetsRequestError(message, status_code=int(status_code)) from exc

    def get_values(self, spreadsheet_id: str, range_a1: str, major_dimension: str = "ROWS") -> dict:
        try:
            req = self._service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_a1, majorDimension=major_dimension
            )
            return req.execute()
        except Exception as exc:
            self._raise_request_error(exc)

    def append_values(
        self,
        spreadsheet_id: str,
        range_a1: str,
        values: list[list[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict:
        try:
            body = {"values": values}
            req = self._service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueInputOption=value_input_option,
                insertDataOption=insert_data_option,
                body=body,
            )
            return req.execute()
        except Exception as exc:
            self._raise_request_error(exc)

    def update_values(
        self,
        spreadsheet_id: str,
        range_a1: str,
        values: list[list[Any]],
        *,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        try:
            body = {"values": values}
            req = self._service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueInputOption=value_input_option,
                body=body,
            )
            return req.execute()
        except Exception as exc:
            self._raise_request_error(exc)

    def clear_range(self, spreadsheet_id: str, range_a1: str) -> dict:
        try:
            req = self._service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id, range=range_a1, body={}
            )
            return req.execute()
        except Exception as exc:
            self._raise_request_error(exc)


@lru_cache(maxsize=1)
def get_sheets_client() -> SheetsClient:
    return SheetsClient()
