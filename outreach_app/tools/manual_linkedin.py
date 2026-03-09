from __future__ import annotations

import hashlib
from typing import Any

from app.orchestrator.policy import RiskTier
from app.tools.base import Tool, ToolContext, ToolResult


class ManualLinkedInActionTool(Tool):
    name = "linkedin.manual_action"
    risk_tier = int(RiskTier.TIER2_EXTERNAL_IMPACT)
    description = "Produce a manual LinkedIn action checklist + message copy."

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        profile_url = kwargs["profile_url"]
        action = kwargs.get("action", "connect_and_message")
        message = kwargs.get("message", "")
        notes = kwargs.get("notes", "")

        eid = ctx.evidence.next_evidence_id("LI")
        checklist = {
            "evidence_id": eid,
            "profile_url": profile_url,
            "action": action,
            "message_copy": message,
            "notes": notes,
            "instructions": [
                "Open the LinkedIn profile URL.",
                f"Perform action: {action}.",
                "Paste message copy (if applicable).",
                "Capture a screenshot/confirmation as evidence.",
            ],
        }
        out_path = ctx.evidence.write_json(f"outputs/{eid}_linkedin_manual_action.json", checklist)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="linkedin_manual_action", path=out_path, sha256=digest, metadata={"profile_url": profile_url})

        return ToolResult(ok=True, output={**checklist, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "linkedin_manual_action", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=True)
