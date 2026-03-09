from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolContext, ToolResult


class FileSystemTool(Tool):
    name = "fs.write_text"
    risk_tier = 1
    description = "Write text into the run evidence pack under outputs/."

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        rel_path = kwargs["rel_path"]
        content = kwargs["content"]

        base_dir = Path(ctx.evidence.root).resolve()
        dst = (base_dir / "outputs" / rel_path).resolve()
        if not str(dst).startswith(str(base_dir)):
            raise ValueError("Path traversal blocked.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        eid = ctx.evidence.next_evidence_id("FS")
        ctx.evidence.add_artifact(evidence_id=eid, type="text", path=dst, sha256=digest, metadata={"rel_path": rel_path})

        return ToolResult(ok=True, output={"path": str(dst), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "text", "path": str(dst), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)
