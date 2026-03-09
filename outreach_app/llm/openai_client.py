from __future__ import annotations

from app.core.config import settings
from app.llm.base import LLMClient, LLMMessage, LLMResponse


class OpenAIClient(LLMClient):
    """
    Install: pip install ".[openai]"
    Env: OPENAI_API_KEY, OPENAI_MODEL
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        api_key = api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError("OpenAI not configured. Set OPENAI_API_KEY.")
        self.model = model or settings.openai_model
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError('OpenAI extras not installed. Run: pip install ".[openai]"') from e
        self._client = OpenAI(api_key=api_key)

    def chat(self, messages: list[LLMMessage], *, temperature: float = 0.2) -> LLMResponse:
        payload = [{"role": m.role, "content": m.content} for m in messages]
        res = self._client.chat.completions.create(model=self.model, messages=payload, temperature=temperature)
        msg = res.choices[0].message.content or ""
        usage = None
        if getattr(res, "usage", None) is not None:
            usage = res.usage.model_dump() if hasattr(res.usage, "model_dump") else dict(res.usage)
        return LLMResponse(content=msg, model=self.model, usage=usage)
