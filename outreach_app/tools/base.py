from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from app.orchestrator.evidence import EvidencePack


@dataclass
class ToolContext:
    run_id: str
    task_id: str
    requested_by: str
    evidence: EvidencePack
    dry_run: bool
    db: Any
    scratch: dict


@dataclass
class ToolResult:
    ok: bool
    output: dict
    evidence_ids: list[str]
    external_effect: bool = False


class Tool(abc.ABC):
    name: str
    risk_tier: int
    description: str | None = None
    args_model: Any = None  # Optional Pydantic model class

    @abc.abstractmethod
    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    def spec(self) -> dict:
        schema = None
        if self.args_model is not None:
            try:
                schema = self.args_model.model_json_schema()
            except Exception:
                schema = None
        return {"name": self.name, "risk_tier": int(self.risk_tier), "description": self.description, "args_schema": schema}
