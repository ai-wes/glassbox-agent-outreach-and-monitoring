from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from app.orchestrator.policy import RiskTier
from app.rag.store import RagStore
from app.tools.base import Tool, ToolContext, ToolResult


class RagUpsertArgs(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1)
    doc_id: str | None = None
    source: str | None = None
    title: str | None = None
    metadata: dict = Field(default_factory=dict)
    chunk_words: int | None = Field(default=None, ge=50, le=2000)
    chunk_overlap_words: int | None = Field(default=None, ge=0, le=500)


class RagQueryArgs(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    doc_id: str | None = None


class RagDeleteDocArgs(BaseModel):
    namespace: str
    doc_id: str


class RagDeleteNamespaceArgs(BaseModel):
    namespace: str


class RagUpsertTool(Tool):
    name = "rag.upsert_text"
    risk_tier = int(RiskTier.TIER1_INTERNAL_WRITE)
    description = "Upsert text into the RAG store (chunk + embed + store)."
    args_model = RagUpsertArgs

    def __init__(self):
        self.store = RagStore()

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        args = RagUpsertArgs(**kwargs)
        doc_id, chunks_added = self.store.upsert_document(
            ctx.db,
            namespace=args.namespace,
            text=args.text,
            doc_id=args.doc_id,
            source=args.source,
            title=args.title,
            metadata=args.metadata,
            chunk_words_n=args.chunk_words,
            overlap_words_n=args.chunk_overlap_words,
        )

        eid = ctx.evidence.next_evidence_id("RAG")
        out = {"namespace": args.namespace, "doc_id": doc_id, "chunks_added": chunks_added}
        out_path = ctx.evidence.write_json(f"outputs/{eid}_rag_upsert.json", out)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="rag_upsert", path=out_path, sha256=digest, metadata={"namespace": args.namespace, "doc_id": doc_id})

        return ToolResult(ok=True, output={**out, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "rag_upsert", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)


class RagQueryTool(Tool):
    name = "rag.query"
    risk_tier = int(RiskTier.TIER0_READONLY)
    description = "Query the RAG store and return top-k chunks."
    args_model = RagQueryArgs

    def __init__(self):
        self.store = RagStore()

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        args = RagQueryArgs(**kwargs)
        hits = self.store.query(ctx.db, namespace=args.namespace, query_text=args.query, top_k=args.top_k, doc_id=args.doc_id)
        data = {
            "namespace": args.namespace,
            "query": args.query,
            "hits": [{"doc_id": h.doc_id, "chunk_id": h.chunk_id, "score": h.score, "text": h.text, "metadata": h.metadata} for h in hits],
        }

        eid = ctx.evidence.next_evidence_id("RAGQ")
        out_path = ctx.evidence.write_json(f"outputs/{eid}_rag_query.json", data)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="rag_query", path=out_path, sha256=digest, metadata={"namespace": args.namespace})

        return ToolResult(ok=True, output={**data, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "rag_query", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)


class RagDeleteDocumentTool(Tool):
    name = "rag.delete_document"
    risk_tier = int(RiskTier.TIER1_INTERNAL_WRITE)
    description = "Delete a document and its chunks from the RAG store."
    args_model = RagDeleteDocArgs

    def __init__(self):
        self.store = RagStore()

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        args = RagDeleteDocArgs(**kwargs)
        deleted = self.store.delete_document(ctx.db, namespace=args.namespace, doc_id=args.doc_id)

        eid = ctx.evidence.next_evidence_id("RAGDEL")
        out = {"ok": True, "namespace": args.namespace, "doc_id": args.doc_id, "deleted_chunks": deleted}
        out_path = ctx.evidence.write_json(f"outputs/{eid}_rag_delete_doc.json", out)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="rag_delete_document", path=out_path, sha256=digest, metadata={"namespace": args.namespace, "doc_id": args.doc_id})

        return ToolResult(ok=True, output={**out, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "rag_delete_document", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)


class RagDeleteNamespaceTool(Tool):
    name = "rag.delete_namespace"
    risk_tier = int(RiskTier.TIER1_INTERNAL_WRITE)
    description = "Delete all docs/chunks in a namespace from the RAG store."
    args_model = RagDeleteNamespaceArgs

    def __init__(self):
        self.store = RagStore()

    def call(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        args = RagDeleteNamespaceArgs(**kwargs)
        deleted = self.store.delete_namespace(ctx.db, namespace=args.namespace)

        eid = ctx.evidence.next_evidence_id("RAGNS")
        out = {"ok": True, "namespace": args.namespace, "deleted_chunks": deleted}
        out_path = ctx.evidence.write_json(f"outputs/{eid}_rag_delete_ns.json", out)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        ctx.evidence.add_artifact(evidence_id=eid, type="rag_delete_namespace", path=out_path, sha256=digest, metadata={"namespace": args.namespace})

        return ToolResult(ok=True, output={**out, "artifact_path": str(out_path), "sha256": digest, "artifacts": [{"evidence_id": eid, "type": "rag_delete_namespace", "path": str(out_path), "sha256": digest}]}, evidence_ids=[eid], external_effect=False)
