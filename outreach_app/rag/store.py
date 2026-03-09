from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.rag import RagChunk, RagDocument
from app.rag.embeddings import EmbeddingProvider, default_embedding_provider
from app.utils.id import new_id

_WS_RE = re.compile(r"\s+")


def _pack(vec: np.ndarray) -> bytes:
    if vec.dtype != np.float32:
        vec = vec.astype(np.float32)
    return vec.tobytes(order="C")


def _unpack(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)


def chunk_text_words(text: str, *, chunk_words: int, overlap_words: int) -> list[str]:
    words = [w for w in _WS_RE.split(text.strip()) if w]
    if not words:
        return []
    if chunk_words <= 0:
        raise ValueError("chunk_words must be > 0")
    if overlap_words < 0:
        raise ValueError("overlap_words must be >= 0")
    if overlap_words >= chunk_words:
        raise ValueError("overlap_words must be < chunk_words")

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_words, len(words))
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start = max(0, end - overlap_words)
    return chunks


@dataclass
class RagHit:
    doc_id: str
    chunk_id: str
    score: float
    text: str
    metadata: dict


class RagStore:
    """
    DB-backed vector store with brute-force cosine similarity.
    Embeddings are stored as float32 blobs.
    """

    def __init__(self, embedder: EmbeddingProvider | None = None):
        self.embedder = embedder or default_embedding_provider()

    def upsert_document(
        self,
        db: Session,
        *,
        namespace: str,
        text: str,
        doc_id: str | None = None,
        source: str | None = None,
        title: str | None = None,
        metadata: dict | None = None,
        chunk_words_n: int | None = None,
        overlap_words_n: int | None = None,
    ) -> tuple[str, int]:
        namespace = namespace.strip()
        if not namespace:
            raise ValueError("namespace required")
        if not text.strip():
            raise ValueError("text required")

        metadata = metadata or {}
        chunk_words_n = int(chunk_words_n or settings.rag_chunk_words)
        overlap_words_n = int(overlap_words_n or settings.rag_chunk_overlap_words)

        if doc_id:
            doc = db.query(RagDocument).filter(RagDocument.id == doc_id, RagDocument.namespace == namespace).first()
            if doc is None:
                doc = RagDocument(
                    id=doc_id,
                    namespace=namespace,
                    source=source,
                    title=title,
                    metadata_json=metadata,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(doc)
                db.flush()
            else:
                doc.source = source or doc.source
                doc.title = title or doc.title
                merged = dict(doc.metadata_json or {})
                merged.update(metadata)
                doc.metadata_json = merged
                doc.updated_at = datetime.utcnow()
                db.query(RagChunk).filter(RagChunk.document_id == doc.id).delete()
                db.flush()
        else:
            doc_id = new_id("RAGDOC", nbytes=14)
            doc = RagDocument(
                id=doc_id,
                namespace=namespace,
                source=source,
                title=title,
                metadata_json=metadata,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(doc)
            db.flush()

        chunks = chunk_text_words(text, chunk_words=chunk_words_n, overlap_words=overlap_words_n)
        if not chunks:
            return doc_id, 0

        vecs = self.embedder.embed_texts(chunks)
        dim = int(vecs[0].shape[0])

        for idx, (chunk, vec) in enumerate(zip(chunks, vecs)):
            if int(vec.shape[0]) != dim:
                raise ValueError("Inconsistent embedding dimension in embedder output.")
            db.add(
                RagChunk(
                    id=new_id("RAGCH", nbytes=14),
                    document_id=doc.id,
                    namespace=namespace,
                    chunk_index=idx,
                    text=chunk,
                    embedding=_pack(vec),
                    embedding_dim=dim,
                    metadata_json={"chunk_words": chunk_words_n, "overlap_words": overlap_words_n},
                    created_at=datetime.utcnow(),
                )
            )
        db.flush()
        return doc_id, len(chunks)

    def query(
        self,
        db: Session,
        *,
        namespace: str,
        query_text: str,
        top_k: int = 5,
        doc_id: str | None = None,
    ) -> list[RagHit]:
        namespace = namespace.strip()
        if not namespace:
            raise ValueError("namespace required")
        query_text = query_text.strip()
        if not query_text:
            raise ValueError("query_text required")
        top_k = int(top_k)
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be 1..50")

        qvec = self.embedder.embed_texts([query_text])[0].astype(np.float32)
        qdim = int(qvec.shape[0])

        q = db.query(RagChunk).filter(RagChunk.namespace == namespace)
        if doc_id:
            q = q.filter(RagChunk.document_id == doc_id)
        rows = q.all()

        hits: list[RagHit] = []
        for r in rows:
            if int(r.embedding_dim) != qdim:
                continue
            v = _unpack(r.embedding, qdim)
            score = float(np.dot(qvec, v))  # normalized -> cosine
            hits.append(RagHit(doc_id=r.document_id, chunk_id=r.id, score=score, text=r.text, metadata=dict(r.metadata_json or {})))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def delete_document(self, db: Session, *, namespace: str, doc_id: str) -> int:
        namespace = namespace.strip()
        if not namespace or not doc_id:
            raise ValueError("namespace and doc_id required")
        deleted = db.query(RagChunk).filter(RagChunk.namespace == namespace, RagChunk.document_id == doc_id).delete()
        db.query(RagDocument).filter(RagDocument.namespace == namespace, RagDocument.id == doc_id).delete()
        db.flush()
        return int(deleted or 0)

    def delete_namespace(self, db: Session, *, namespace: str) -> int:
        namespace = namespace.strip()
        if not namespace:
            raise ValueError("namespace required")
        deleted = db.query(RagChunk).filter(RagChunk.namespace == namespace).delete()
        db.query(RagDocument).filter(RagDocument.namespace == namespace).delete()
        db.flush()
        return int(deleted or 0)
