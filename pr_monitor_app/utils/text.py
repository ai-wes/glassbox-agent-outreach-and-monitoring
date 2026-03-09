from __future__ import annotations

import re
from typing import Iterable


_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")


def normalize_text(text: str) -> str:
    t = text or ""
    t = t.replace("\u00a0", " ")
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return t


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text or "")


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    t = (text or "").lower()
    hits: list[str] = []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if not k:
            continue
        if k in t:
            hits.append(kw)
    return hits


def top_capitalized_phrases(text: str, max_phrases: int = 12) -> list[str]:
    """
    Lightweight entity guesser to complement explicit dictionaries.
    Extracts sequences of Capitalized words (e.g. "European Commission").
    """
    if not text:
        return []
    candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})\b", text)
    # Deduplicate while preserving order
    seen = set()
    out = []
    for c in candidates:
        c = c.strip()
        if len(c) < 3:
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= max_phrases:
            break
    return out
