from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True, nullable=False)

    scope: Mapped[str] = mapped_column(String(120), nullable=False, default="run")
    requested_by: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    token_sha256: Mapped[str] = mapped_column(String(128), nullable=False)

    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
