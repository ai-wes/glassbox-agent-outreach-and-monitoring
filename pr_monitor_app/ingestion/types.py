"""Layer 1 ingestion types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from pr_monitor_app.models import EventSourceType


@dataclass
class EventCandidate:
    canonical_url: str
    title: str
    summary: Optional[str] = None
    content_text: Optional[str] = None
    content_hash: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    source_type: EventSourceType = EventSourceType.rss
    raw_json: dict[str, Any] | None = None
    dedup_salt: Optional[str] = None
