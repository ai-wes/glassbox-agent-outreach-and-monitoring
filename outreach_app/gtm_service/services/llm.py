from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
try:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover
    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def retry_if_exception_type(*args, **kwargs):
        return None

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

from outreach_app.gtm_service.core.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}" if settings.llm_api_key else "",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, ValidationError, KeyError, ValueError)),
    )
    async def generate_json(self, *, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
        if not self.settings.llm_ready:
            raise RuntimeError("LLM is not configured")
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return schema.model_validate(json.loads(content))

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, KeyError, ValueError)),
    )
    async def generate_text(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        if not self.settings.llm_ready:
            raise RuntimeError("LLM is not configured")
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"]).strip()
