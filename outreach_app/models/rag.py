from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, Integer, JSON, ForeignKey, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(120), index=True, nullable=False)

    source: Mapped[str | None] = mapped_column(String(280), nullable=True)
    title: Mapped[str | None] = mapped_column(String(280), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chunks = relationship("RagChunk", backref="document", cascade="all, delete-orphan")


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(60), ForeignKey("rag_documents.id"), index=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(120), index=True, nullable=False)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)

    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
