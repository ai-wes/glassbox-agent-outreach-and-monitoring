"""Google Sheets integration layer.

This module provides utility functions to read and write data to a
Google Sheets spreadsheet.  It uses a service account credential
specified via the ``google_service_account_file`` setting.  All
operations are synchronous because the Google API client library is
blocking; Celery tasks should call these functions in worker
processes.

The sheet is treated as an operational dashboard with named ranges
matching the application data model.  Helper functions abstract the
API details and accept native Python lists or dictionaries.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings


logger = logging.getLogger(__name__)


def _get_sheets_service() -> Any:
    """Create a Google Sheets API service using service account credentials.

    The credentials file path and spreadsheet ID are sourced from
    environment variables via ``settings``.  This helper caches the
    built service so repeated calls share the same underlying HTTP
    transport.

    Returns:
        An authorised Sheets API service instance.
    """
    creds = Credentials.from_service_account_file(settings.google_service_account_file, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def append_rows(range_name: str, values: List[List[Any]]) -> None:
    """Append rows of values to a sheet.

    Args:
        range_name: A1 notation specifying the sheet and range (e.g. ``"Leads!A1:F"``).
        values: List of rows, where each row is a list of cell values.
    """
    service = _get_sheets_service()
    body = {
        "values": values
    }
    try:
        logger.info("Appending %d rows to range %s", len(values), range_name)
        service.spreadsheets().values().append(
            spreadsheetId=settings.google_sheets_spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
    except HttpError as err:
        logger.exception("Failed to append rows to Google Sheets: %s", err)
        raise


def update_rows(range_name: str, values: List[List[Any]]) -> None:
    """Write values to a specific range in a sheet, overwriting existing cells.

    Args:
        range_name: A1 notation specifying the sheet and range.
        values: A list of rows matching the shape of the range.
    """
    service = _get_sheets_service()
    body = {
        "values": values
    }
    try:
        logger.info("Updating range %s with %d rows", range_name, len(values))
        service.spreadsheets().values().update(
            spreadsheetId=settings.google_sheets_spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
    except HttpError as err:
        logger.exception("Failed to update rows in Google Sheets: %s", err)
        raise


def get_values(range_name: str) -> List[List[Any]]:
    """Retrieve values from a sheet range.

    Args:
        range_name: A1 notation specifying the sheet and range to fetch.

    Returns:
        A list of rows, each containing cell values.  Empty rows
        result in an empty list.
    """
    service = _get_sheets_service()
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.google_sheets_spreadsheet_id,
            range=range_name,
        ).execute()
        return result.get("values", [])
    except HttpError as err:
        logger.exception("Failed to get values from Google Sheets: %s", err)
        raise


def clear_range(range_name: str) -> None:
    """Clear all values from a specified sheet range.

    Args:
        range_name: A1 notation specifying the sheet and range.
    """
    service = _get_sheets_service()
    try:
        logger.info("Clearing range %s", range_name)
        service.spreadsheets().values().clear(
            spreadsheetId=settings.google_sheets_spreadsheet_id,
            range=range_name,
            body={},
        ).execute()
    except HttpError as err:
        logger.exception("Failed to clear range %s: %s", range_name, err)
        raise
