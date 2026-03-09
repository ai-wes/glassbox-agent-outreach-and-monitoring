from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, Any] | None = None


class LLMClient(abc.ABC):
    @abc.abstractmethod
    def chat(self, messages: list[LLMMessage], *, temperature: float = 0.2) -> LLMResponse:
        raise NotImplementedError
