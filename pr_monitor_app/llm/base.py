from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: dict[str, Any]


class LLMClient(abc.ABC):
    @abc.abstractmethod
    async def generate(self, *, system: str, user: str, json_schema: Optional[dict[str, Any]] = None) -> LLMResponse:
        raise NotImplementedError
