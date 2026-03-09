from __future__ import annotations

import abc
import hashlib
import logging
import math
import re

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class EmbeddingProvider(abc.ABC):
    @abc.abstractmethod
    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        """
        Return L2-normalized float32 vectors.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def dim(self) -> int:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic offline embedding using the hashing trick.
    """

    def __init__(self, dim: int | None = None):
        self._dim = int(dim or settings.rag_embedding_dim)
        if self._dim < 64:
            raise ValueError("RAG_EMBEDDING_DIM must be >= 64")

    @property
    def dim(self) -> int:
        return self._dim

    def _tokenize(self, text: str) -> list[str]:
        return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]

    def _token_hash(self, token: str) -> tuple[int, float]:
        # Stable 64-bit hash
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        v = int.from_bytes(h, "little", signed=False)
        idx = v % self._dim
        sign = -1.0 if ((v >> 63) & 1) else 1.0
        return idx, sign

    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for text in texts:
            v = np.zeros((self._dim,), dtype=np.float32)
            tokens = self._tokenize(text)
            if not tokens:
                out.append(v)
                continue
            counts: dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            for tok, c in counts.items():
                idx, sign = self._token_hash(tok)
                v[idx] += sign * (1.0 + math.log(1.0 + float(c)))
            n = float(np.linalg.norm(v))
            if n > 0:
                v /= n
            out.append(v)
        return out


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embeddings provider (optional).

    Requires:
      pip install ".[openai]"
      OPENAI_API_KEY
    """

    def __init__(self, model: str | None = None):
        self._model = model or settings.openai_embedding_model
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError('OpenAI extras not installed. Run: pip install ".[openai]"') from e
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._dim_cache: int | None = None

    @property
    def dim(self) -> int:
        return self._dim_cache or int(settings.rag_embedding_dim)

    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        res = self._client.embeddings.create(model=self._model, input=texts)
        vecs: list[np.ndarray] = []
        for item in res.data:
            arr = np.array(item.embedding, dtype=np.float32)
            n = float(np.linalg.norm(arr))
            if n > 0:
                arr /= n
            vecs.append(arr)
        if vecs and self._dim_cache is None:
            self._dim_cache = int(vecs[0].shape[0])
        return vecs


def default_embedding_provider() -> EmbeddingProvider:
    if settings.openai_api_key:
        try:
            return OpenAIEmbeddingProvider()
        except Exception:
            logger.exception("OpenAI embeddings unavailable; falling back to hash embeddings.")
    return HashEmbeddingProvider()
