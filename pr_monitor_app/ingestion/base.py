from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from pr_monitor_app.models import SourceType


@dataclass(frozen=True)
class IngestedItem:
    external_id: str
    source_type: SourceType
    title: str
    url: str
    author: str
    published_at: datetime
    raw_text: str
    engagement_stats: dict[str, Any]


class Connector(abc.ABC):
    @abc.abstractmethod
    async def fetch(self) -> list[IngestedItem]:
        """Fetch new items from the source."""
        raise NotImplementedError
