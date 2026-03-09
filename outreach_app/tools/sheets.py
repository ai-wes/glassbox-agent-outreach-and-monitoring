from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.google_sheets import get_sheets_client
from app.orchestrator.policy import RiskTier
from app.tools.base import Tool, ToolContext, ToolResult


class SheetsReadArgs(BaseModel):
    spreadsheet_id: str = Field(..., min_length=10)
    range_a1: str = Field(..., min_length=1)
    major_dimension: str = Field(default="ROWS")


class SheetsAppendArgs(BaseModel):
    spreadsheet_id: str
    range_a1: str
    values: list[list[Any]]
    value_input_option: str = Field(default="USER_ENTERED")
    insert_data_option: str = Field(default="INSERT_ROWS")


class SheetsUpdateArgs(BaseModel):
    spreadsheet_id: str
    range_a1: str
    values: list[list[Any]]
    value_input_option: str = Field(default="USER_ENTERED")


class SheetsClearArgs(BaseModel):
    spreadsheet_id: str
    range_a1: str


class SheetsReadTool(Tool):
    name = "sheets.read_range"
    risk_tier = int(RiskTier.TIER0_READONLY)
    description = "Read a range from a Google Sheet (A1 notation)."
    args_model = SheetsReadArgs

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        args = SheetsReadArgs(**kwargs)
        client = get_sheets_client()
        res = client.get_values(args.spreadsheet_id, args.range_a1, major_dimension=args.major_dimension)

        eid = ctx.evidence.next_evidence_id("SHEETS")
        out_path = ctx.evidence.write_json(f"outputs/{eid}_sheets_read.json", res)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="sheets_read", path=out_path, sha256=digest, metadata={"spreadsheet_id": args.spreadsheet_id, "range": args.range_a1})

        return ToolResult(ok=True, output={**res, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "sheets_read", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)


class SheetsAppendTool(Tool):
    name = "sheets.append_rows"
    risk_tier = int(RiskTier.TIER2_EXTERNAL_IMPACT)
    description = "Append rows to a Google Sheet."
    args_model = SheetsAppendArgs

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.dry_run:
            raise PermissionError("Dry-run blocks Sheets writes.")
        args = SheetsAppendArgs(**kwargs)
        client = get_sheets_client()
        res = client.append_values(args.spreadsheet_id, args.range_a1, args.values, value_input_option=args.value_input_option, insert_data_option=args.insert_data_option)

        eid = ctx.evidence.next_evidence_id("SHEETSAPP")
        out_path = ctx.evidence.write_json(f"outputs/{eid}_sheets_append.json", res)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="sheets_append", path=out_path, sha256=digest, metadata={"spreadsheet_id": args.spreadsheet_id, "range": args.range_a1})

        return ToolResult(ok=True, output={**res, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "sheets_append", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=True)


class SheetsUpdateTool(Tool):
    name = "sheets.update_range"
    risk_tier = int(RiskTier.TIER2_EXTERNAL_IMPACT)
    description = "Update a range in a Google Sheet."
    args_model = SheetsUpdateArgs

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.dry_run:
            raise PermissionError("Dry-run blocks Sheets writes.")
        args = SheetsUpdateArgs(**kwargs)
        client = get_sheets_client()
        res = client.update_values(args.spreadsheet_id, args.range_a1, args.values, value_input_option=args.value_input_option)

        eid = ctx.evidence.next_evidence_id("SHEETSUPD")
        out_path = ctx.evidence.write_json(f"outputs/{eid}_sheets_update.json", res)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="sheets_update", path=out_path, sha256=digest, metadata={"spreadsheet_id": args.spreadsheet_id, "range": args.range_a1})

        return ToolResult(ok=True, output={**res, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "sheets_update", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=True)


class SheetsClearTool(Tool):
    name = "sheets.clear_range"
    risk_tier = int(RiskTier.TIER2_EXTERNAL_IMPACT)
    description = "Clear a range in a Google Sheet."
    args_model = SheetsClearArgs

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.dry_run:
            raise PermissionError("Dry-run blocks Sheets writes.")
        args = SheetsClearArgs(**kwargs)
        client = get_sheets_client()
        res = client.clear_range(args.spreadsheet_id, args.range_a1)

        eid = ctx.evidence.next_evidence_id("SHEETSCLEAR")
        out_path = ctx.evidence.write_json(f"outputs/{eid}_sheets_clear.json", res)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="sheets_clear", path=out_path, sha256=digest, metadata={"spreadsheet_id": args.spreadsheet_id, "range": args.range_a1})

        return ToolResult(ok=True, output={**res, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "sheets_clear", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=True)
