from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from npe.config import settings
from npe.llm.base import LLMClient, LLMResponse


class OpenAICompatClient(LLMClient):
    """
    Works with OpenAI's public API OR any OpenAI-compatible endpoint.

    Prefers Responses API if available (POST /v1/responses). Falls back to Chat Completions
    (POST /v1/chat/completions).

    - Base URL: settings.llm_base_url (e.g., https://api.openai.com/v1)
    - API Key: settings.llm_api_key
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 45,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.7, min=0.7, max=8))
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=self._headers()) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _extract_text_from_responses(self, data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or []
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    t = c.get("text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t)
        if parts:
            return "\n".join(parts).strip()
        # Some gateways return output_text directly
        if isinstance(data.get("output_text"), str):
            return data["output_text"].strip()
        return json.dumps(data, ensure_ascii=False)

    def _extract_text_from_chat(self, data: dict[str, Any]) -> str:
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception:
            return json.dumps(data, ensure_ascii=False)

    def _best_effort_json(self, text: str) -> Any:
        """
        Attempts to parse JSON from model output.
        Handles cases where the model wraps JSON in code fences or adds leading text.
        """
        t = text.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\n", "", t)
            t = t.replace("```", "").strip()
        try:
            return json.loads(t)
        except Exception:
            # Find first JSON object/array substring
            m = re.search(r"(\{.*\}|\[.*\])", t, re.DOTALL)
            if m:
                return json.loads(m.group(1))
        raise ValueError("LLM did not return valid JSON")

    async def generate(self, *, system: str, user: str, json_schema: Optional[dict[str, Any]] = None) -> LLMResponse:
        if not self.api_key:
            raise ValueError("LLM API key missing. Set LLM_API_KEY.")
        # Prefer Responses API
        try:
            payload = {
                "model": self.model,
                "input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if json_schema:
                # Many OpenAI-compatible providers accept response_format/json_schema; keep best-effort.
                payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
            data = await self._post("/responses", payload)
            text = self._extract_text_from_responses(data)
            return LLMResponse(text=text, raw=data)
        except httpx.HTTPStatusError as e:
            # If the server doesn't support /responses, fallback to /chat/completions
            if e.response is not None and e.response.status_code in (404, 405):
                pass
            else:
                raise
        except Exception:
            # Fallback; only if /responses call fails for compatibility reasons
            pass

        payload2 = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_schema:
            payload2["response_format"] = {"type": "json_object"}
        data2 = await self._post("/chat/completions", payload2)
        text2 = self._extract_text_from_chat(data2)
        return LLMResponse(text=text2, raw=data2)

    async def generate_json(self, *, system: str, user: str, json_schema: Optional[dict[str, Any]] = None) -> tuple[dict[str, Any], LLMResponse]:
        resp = await self.generate(system=system, user=user, json_schema=json_schema)
        parsed = self._best_effort_json(resp.text)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object from LLM")
        return parsed, resp


def build_llm_client() -> Optional[OpenAICompatClient]:
    if not settings.llm_enabled:
        return None
    if not settings.llm_api_key:
        raise ValueError("LLM_ENABLED=true but LLM_API_KEY is empty.")
    return OpenAICompatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
