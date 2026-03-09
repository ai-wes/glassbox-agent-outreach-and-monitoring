from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pr_monitor_app.config import settings
from pr_monitor_app.logging import get_logger

log = get_logger(component="analytics.embeddings")


class EmbeddingProvider(Protocol):
    """Minimal interface for an embedding backend."""

    @property
    def model_name(self) -> str: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return an embedding vector for each text (in the same order)."""
        ...


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 30.0


class OpenAIEmbeddingProvider:
    """OpenAI embedding provider via direct HTTP (no SDK dependency).

    Uses POST {base_url}/v1/embeddings with JSON:
      {"model": "...", "input": [ ... ]}

    The response format is:
      {"data":[{"embedding":[...], "index":0}, ...], "model":"..."}
    """

    def __init__(self, cfg: OpenAIEmbeddingConfig):
        self._cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url.rstrip("/"),
            timeout=httpx.Timeout(cfg.timeout_seconds),
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "User-Agent": settings.http_user_agent,
            },
        )

    @property
    def model_name(self) -> str:
        return self._cfg.model

    def close(self) -> None:
        self._client.close()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=12),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    )
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {"model": self._cfg.model, "input": texts}
        res = self._client.post("/v1/embeddings", content=json.dumps(payload))
        if res.status_code >= 400:
            raise RuntimeError(f"openai_embeddings_failed status={res.status_code} body={res.text[:800]}")

        body = res.json()
        data = body.get("data") or []
        # Ensure stable ordering by index
        data_sorted = sorted(data, key=lambda x: int(x.get("index", 0)))
        vectors: list[list[float]] = []
        for item in data_sorted:
            emb = item.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise RuntimeError("openai_embeddings_missing_vector")
            vectors.append([float(x) for x in emb])
        if len(vectors) != len(texts):
            raise RuntimeError("openai_embeddings_count_mismatch")
        return vectors


class NoopEmbeddingProvider:
    """Embedding provider that disables embeddings (keyword-only scoring)."""

    @property
    def model_name(self) -> str:
        return "none"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embeddings_disabled")


def make_embedding_provider() -> EmbeddingProvider:
    provider = (settings.analytics_embedding_provider or "none").strip().lower()

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("ANALYTICS_EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set")
        cfg = OpenAIEmbeddingConfig(
            api_key=settings.openai_api_key,
            base_url=str(settings.openai_base_url),
            model=settings.analytics_embedding_model,
            timeout_seconds=max(settings.http_timeout_seconds, 30.0),
        )
        log.info("embedding_provider_openai", model=cfg.model, base_url=cfg.base_url)
        return OpenAIEmbeddingProvider(cfg)

    if provider in ("none", "off", "disabled"):
        log.info("embedding_provider_disabled")
        return NoopEmbeddingProvider()

    raise RuntimeError(f"unknown_embedding_provider: {provider}")
