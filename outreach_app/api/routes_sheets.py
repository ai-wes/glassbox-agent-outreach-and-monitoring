from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.integrations.google_sheets import (
    SheetsConfigurationError,
    SheetsRequestError,
    get_sheets_client,
)
from app.schemas.sheets import SheetsReadRequest, SheetsValuesResponse, SheetsAppendRequest, SheetsUpdateRequest, SheetsClearRequest, SheetsWriteResponse

router = APIRouter(prefix="/sheets", tags=["sheets"])


def _translate_sheets_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SheetsConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, SheetsRequestError):
        status_code = exc.status_code
        if status_code >= 500:
            status_code = 502
        return HTTPException(status_code=status_code, detail=str(exc))
    return HTTPException(status_code=500, detail="Unhandled Google Sheets integration error.")


@router.post("/read", response_model=SheetsValuesResponse)
def sheets_read(req: SheetsReadRequest):
    try:
        client = get_sheets_client()
        res = client.get_values(req.spreadsheet_id, req.range_a1, major_dimension=req.major_dimension)
        return SheetsValuesResponse(spreadsheet_id=req.spreadsheet_id, range_a1=res.get("range", req.range_a1), major_dimension=req.major_dimension, values=res.get("values", []))
    except Exception as exc:
        raise _translate_sheets_error(exc) from exc


@router.post("/append", response_model=SheetsWriteResponse)
def sheets_append(req: SheetsAppendRequest):
    try:
        client = get_sheets_client()
        res = client.append_values(req.spreadsheet_id, req.range_a1, req.values, value_input_option=req.value_input_option, insert_data_option=req.insert_data_option)
        updates = res.get("updates") or {}
        return SheetsWriteResponse(spreadsheet_id=req.spreadsheet_id, range_a1=req.range_a1, updated_cells=updates.get("updatedCells"), updates=updates)
    except Exception as exc:
        raise _translate_sheets_error(exc) from exc


@router.post("/update", response_model=SheetsWriteResponse)
def sheets_update(req: SheetsUpdateRequest):
    try:
        client = get_sheets_client()
        res = client.update_values(req.spreadsheet_id, req.range_a1, req.values, value_input_option=req.value_input_option)
        updates = res.get("updates") or {}
        return SheetsWriteResponse(spreadsheet_id=req.spreadsheet_id, range_a1=req.range_a1, updated_cells=updates.get("updatedCells"), updates=updates)
    except Exception as exc:
        raise _translate_sheets_error(exc) from exc


@router.post("/clear", response_model=SheetsWriteResponse)
def sheets_clear(req: SheetsClearRequest):
    try:
        client = get_sheets_client()
        res = client.clear_range(req.spreadsheet_id, req.range_a1)
        return SheetsWriteResponse(spreadsheet_id=req.spreadsheet_id, range_a1=req.range_a1, updates=res)
    except Exception as exc:
        raise _translate_sheets_error(exc) from exc
