from __future__ import annotations

from app.llm.base import LLMClient, LLMMessage, LLMResponse


class RuleBasedLLM(LLMClient):
    def __init__(self, model: str = "rule-based"):
        self.model = model

    def chat(self, messages: list[LLMMessage], *, temperature: float = 0.2) -> LLMResponse:
        last = messages[-1].content if messages else ""
        content = (
            "LLM not configured. Provide OPENAI_API_KEY for intelligent planning.\n"
            "Last message:\n\n" + last
        )
        return LLMResponse(content=content, model=self.model, usage=None)
