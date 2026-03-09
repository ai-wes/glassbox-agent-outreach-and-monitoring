from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), ForeignKey("runs.id"), index=True, nullable=False)

    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
