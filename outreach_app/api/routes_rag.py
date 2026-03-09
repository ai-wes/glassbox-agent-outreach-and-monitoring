from __future__ import annotations

from fastapi import APIRouter

from app.db.session import db_session
from app.rag.store import RagStore
from app.schemas.rag import RagUpsertRequest, RagUpsertResponse, RagQueryRequest, RagQueryResponse, RagQueryHit, RagDeleteDocRequest, RagDeleteResponse

router = APIRouter(prefix="/rag", tags=["rag"])
_store = RagStore()


@router.post("/upsert", response_model=RagUpsertResponse)
def rag_upsert(req: RagUpsertRequest):
    with db_session() as db:
        doc_id, chunks_added = _store.upsert_document(
            db,
            namespace=req.namespace,
            text=req.text,
            doc_id=req.doc_id,
            source=req.source,
            title=req.title,
            metadata=req.metadata,
            chunk_words_n=req.chunk_words,
            overlap_words_n=req.chunk_overlap_words,
        )
        return RagUpsertResponse(namespace=req.namespace, doc_id=doc_id, chunks_added=chunks_added)


@router.post("/query", response_model=RagQueryResponse)
def rag_query(req: RagQueryRequest):
    with db_session() as db:
        hits = _store.query(db, namespace=req.namespace, query_text=req.query, top_k=req.top_k, doc_id=req.doc_id)
        return RagQueryResponse(namespace=req.namespace, query=req.query, hits=[RagQueryHit(doc_id=h.doc_id, chunk_id=h.chunk_id, score=h.score, text=h.text, metadata=h.metadata) for h in hits])


@router.delete("/namespace/{namespace}", response_model=RagDeleteResponse)
def rag_delete_namespace(namespace: str):
    with db_session() as db:
        deleted = _store.delete_namespace(db, namespace=namespace)
        return RagDeleteResponse(ok=True, deleted_chunks=deleted)


@router.delete("/document", response_model=RagDeleteResponse)
def rag_delete_document(req: RagDeleteDocRequest):
    with db_session() as db:
        deleted = _store.delete_document(db, namespace=req.namespace, doc_id=req.doc_id)
        return RagDeleteResponse(ok=True, deleted_chunks=deleted)
