from __future__ import annotations

from pydantic import BaseModel, Field


class SheetsReadRequest(BaseModel):
    spreadsheet_id: str = Field(..., min_length=10)
    range_a1: str = Field(..., min_length=1)
    major_dimension: str = Field(default="ROWS", description="ROWS|COLUMNS")


class SheetsValuesResponse(BaseModel):
    spreadsheet_id: str
    range_a1: str
    major_dimension: str
    values: list[list[str | int | float | None]]


class SheetsAppendRequest(BaseModel):
    spreadsheet_id: str
    range_a1: str
    values: list[list[str | int | float | None]]
    value_input_option: str = Field(default="USER_ENTERED", description="RAW|USER_ENTERED")
    insert_data_option: str = Field(default="INSERT_ROWS", description="INSERT_ROWS|OVERWRITE")


class SheetsUpdateRequest(BaseModel):
    spreadsheet_id: str
    range_a1: str
    values: list[list[str | int | float | None]]
    value_input_option: str = Field(default="USER_ENTERED", description="RAW|USER_ENTERED")


class SheetsClearRequest(BaseModel):
    spreadsheet_id: str
    range_a1: str


class SheetsWriteResponse(BaseModel):
    spreadsheet_id: str
    range_a1: str
    updated_cells: int | None = None
    updates: dict | None = None
