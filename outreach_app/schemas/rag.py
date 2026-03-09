from __future__ import annotations

from pydantic import BaseModel, Field


class RagUpsertRequest(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=120)
    doc_id: str | None = Field(default=None)
    source: str | None = None
    title: str | None = None
    text: str = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)
    chunk_words: int | None = Field(default=None, ge=50, le=2000)
    chunk_overlap_words: int | None = Field(default=None, ge=0, le=500)


class RagUpsertResponse(BaseModel):
    namespace: str
    doc_id: str
    chunks_added: int


class RagQueryRequest(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    doc_id: str | None = None


class RagQueryHit(BaseModel):
    doc_id: str
    chunk_id: str
    score: float
    text: str
    metadata: dict


class RagQueryResponse(BaseModel):
    namespace: str
    query: str
    hits: list[RagQueryHit]


class RagDeleteDocRequest(BaseModel):
    namespace: str
    doc_id: str


class RagDeleteResponse(BaseModel):
    ok: bool
    deleted_chunks: int
