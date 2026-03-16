from __future__ import annotations

import html
import re
from typing import Iterable

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional runtime dependency
    BeautifulSoup = None  # type: ignore[assignment]

_WHITESPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")
_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_TOKEN_RE = re.compile(r"^#(?:x[0-9a-f]+|\d{2,5})$", re.IGNORECASE)
_BOILERPLATE_MARKERS = (
    "transcript:",
    "contact lex:",
    "episode links:",
    "sponsors:",
    "podcast links:",
    "outline:",
    "show notes:",
    "timestamps:",
    "chapters:",
)
_NOISE_ENTITIES = {
    "a",
    "advertise",
    "advertise good",
    "an",
    "and",
    "but",
    "check",
    "contact",
    "featuring",
    "feedback",
    "follow",
    "for",
    "from",
    "hiring",
    "how",
    "links",
    "other",
    "outline",
    "podcast",
    "read",
    "see",
    "sponsors",
    "thank",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "transcript",
    "website",
}


def normalize_text(text: str) -> str:
    t = text or ""
    t = html.unescape(t)
    t = t.replace("\u00a0", " ")
    t = t.replace("\u200b", " ")
    t = t.replace("\ufeff", " ")
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return t


def clean_source_text(text: str, *, max_chars: int | None = None) -> str:
    t = html.unescape(text or "")
    if "<" in t and ">" in t:
        if BeautifulSoup is not None:
            t = BeautifulSoup(t, "html.parser").get_text(" ", strip=False)
        else:
            t = _TAG_RE.sub(" ", t)
    t = normalize_text(t)
    if max_chars is not None and max_chars > 0 and len(t) > max_chars:
        clipped = t[:max_chars].rsplit(" ", 1)[0].strip()
        t = clipped or t[:max_chars].strip()
    return t


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text or "")


def strip_repeated_prefix(text: str, prefix: str) -> str:
    body = normalize_text(text)
    head = normalize_text(prefix)
    if not body or not head:
        return body
    if body.lower().startswith(head.lower()):
        trimmed = body[len(head):].lstrip(" :-|")
        return normalize_text(trimmed)
    return body


def strip_boilerplate_sections(
    text: str,
    *,
    markers: tuple[str, ...] = _BOILERPLATE_MARKERS,
    min_prefix_chars: int = 160,
) -> str:
    body = normalize_text(text)
    if not body:
        return body

    lowered = body.lower()
    cut_at: int | None = None
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= min_prefix_chars and (cut_at is None or idx < cut_at):
            cut_at = idx

    if cut_at is None:
        return body
    return normalize_text(body[:cut_at])


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
        if is_noise_entity(c):
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= max_phrases:
            break
    return out


def is_noise_entity(text: str) -> bool:
    candidate = normalize_text(text)
    if not candidate:
        return True
    lowered = candidate.lower()
    if lowered in _NOISE_ENTITIES:
        return True
    if _HTML_ENTITY_TOKEN_RE.fullmatch(candidate):
        return True
    if not any(ch.isalpha() for ch in candidate):
        return True
    return False
