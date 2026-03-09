from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    tags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
