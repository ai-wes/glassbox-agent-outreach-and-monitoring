from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Iterable

from dateutil import parser as date_parser


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def make_content_hash(*parts: str | None) -> str:
    joined = "||".join(part or "" for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compact_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def safe_parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None


def days_from_now(days: int) -> date:
    return (utcnow() + timedelta(days=days)).date()


def normalize_text(value: str | None) -> str:
    return compact_whitespace(value).lower()


def contains_any(text: str, terms: Iterable[str]) -> bool:
    normalized = normalize_text(text)
    return any(term.lower() in normalized for term in terms if term)


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
