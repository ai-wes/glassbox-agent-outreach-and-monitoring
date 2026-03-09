from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Iterable, List, Sequence

import numpy as np
try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional runtime dependency
    SentenceTransformer = None  # type: ignore[assignment]

from pr_monitor_app.config import settings
from pr_monitor_app.utils.text import normalize_text

log = logging.getLogger(__name__)
_FALLBACK_EMBEDDING_DIM = 384


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer | None:
    # SentenceTransformer caches models on disk; this load is heavy but done once per process.
    if SentenceTransformer is None:
        return None
    return SentenceTransformer(settings.embedding_model_name)


def _fallback_embed(text: str) -> np.ndarray:
    # Deterministic hash-based embedding keeps pipeline operational without torch.
    vec = np.zeros(_FALLBACK_EMBEDDING_DIM, dtype=np.float32)
    for token in normalize_text(text).split():
        vec[hash(token) % _FALLBACK_EMBEDDING_DIM] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def embed_texts(texts: Sequence[str]) -> EmbeddingResult:
    model = _get_model()
    cleaned = [normalize_text(t) for t in texts]
    if model is not None:
        try:
            # convert_to_numpy ensures a numpy array for speed, then convert to list for JSON/DB.
            vectors = model.encode(
                cleaned,
                batch_size=settings.embedding_batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,  # cosine similarity becomes dot product
                convert_to_numpy=True,
            )
            return EmbeddingResult(vectors=[v.astype(np.float32).tolist() for v in vectors])
        except Exception:
            log.exception("sentence_transformer_failed_falling_back")
    else:
        log.warning("sentence_transformers_unavailable_using_hash_fallback")
    return EmbeddingResult(vectors=[_fallback_embed(t).tolist() for t in cleaned])


def cosine_sim(a: Sequence[float], b: Sequence[float]) -> float:
    # assumes vectors are normalized; still safe for non-normalized.
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def max_cosine_sim(vec: Sequence[float], candidates: Iterable[Sequence[float]]) -> float:
    best = 0.0
    for c in candidates:
        if c is None:
            continue
        s = cosine_sim(vec, c)
        if s > best:
            best = s
    return best
