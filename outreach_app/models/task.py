from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(280), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    owner_agent: Mapped[str] = mapped_column(String(50), nullable=False, default="router")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
