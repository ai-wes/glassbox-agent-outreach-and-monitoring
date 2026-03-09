from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, Float, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(40), ForeignKey("tasks.id"), index=True, nullable=False)

    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created", index=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    max_risk_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_uri: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    task = relationship("Task", backref="runs")
