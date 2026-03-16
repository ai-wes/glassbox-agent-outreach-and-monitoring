from __future__ import annotations

from pydantic import BaseModel, Field


class DomainDiscoveryRequest(BaseModel):
    domains: list[str] = Field(default_factory=list)


class LimitedRunRequest(BaseModel):
    limit: int = 100


class ProspectingRunRead(BaseModel):
    task: str
    processed: int
    success_count: int
    failure_count: int
    lead_ids: list[str] = Field(default_factory=list)
    contact_ids: list[str] = Field(default_factory=list)
    synced: dict[str, int] | None = None
