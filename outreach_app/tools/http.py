from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.tools.base import Tool, ToolContext, ToolResult


class HttpGetTool(Tool):
    name = "http.get"
    risk_tier = 0
    description = "HTTP GET a URL and store response body under outputs/."

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        url = kwargs["url"]
        timeout_s = float(kwargs.get("timeout_s", 15))
        headers = kwargs.get("headers", {})
        params = kwargs.get("params", {})

        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            r = client.get(url, headers=headers, params=params)
            r.raise_for_status()
            text = r.text

        eid = ctx.evidence.next_evidence_id("HTTP")
        out_path = ctx.evidence.write_text(f"outputs/{eid}_http_get.txt", text[:2_000_000])
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="http_get", path=out_path, sha256=digest, metadata={"url": url, "status": r.status_code})

        return ToolResult(ok=True, output={"url": url, "status_code": r.status_code, "bytes": len(text), "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "http_get", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)
