from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.run import ApprovalRequestOut, RunOut
from app.schemas.task import TaskOut


class ToolSpec(BaseModel):
    name: str
    risk_tier: int
    description: str | None = None
    args_schema: dict[str, Any] | None = None


class AgentToolCallRequest(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    domain: str = Field(default="ops", description="exec|gtm|narrative|ops")
    priority: int = Field(default=50, ge=0, le=100)
    requested_by: str = Field(default="agent")
    dry_run: bool = False


class AgentExecuteRequest(BaseModel):
    title: str
    domain: str = Field(default="ops", description="exec|gtm|narrative|ops")
    priority: int = Field(default=50, ge=0, le=100)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    requested_by: str = Field(default="agent")
    dry_run: bool = False


class AgentExecutionResponse(BaseModel):
    task: TaskOut
    run: RunOut | None
    approval: ApprovalRequestOut | None
