from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from dateutil import parser as date_parser

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if value.startswith("http://") or value.startswith("https://"):
        return urlparse(value).netloc.lower().removeprefix("www.")
    return value.removeprefix("www.")


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme:
        return f"https://{value}"
    return value


def full_name(first_name: str | None, last_name: str | None, fallback: str | None = None) -> str | None:
    joined = " ".join(part for part in [first_name, last_name] if part)
    if joined:
        return joined
    return fallback


def infer_domain_from_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].lower()


def extract_emails(text: str) -> list[str]:
    return sorted(set(match.group(0).lower() for match in EMAIL_RE.finditer(text or "")))


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        try:
            dt = date_parser.parse(value)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError, OverflowError):
            return None


def compute_recency_score(occurred_at: datetime | None, now: datetime | None = None) -> float:
    if occurred_at is None:
        return 0.4
    now = now or datetime.now(timezone.utc)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    delta_days = max((now - occurred_at).total_seconds() / 86400, 0)
    if delta_days <= 7:
        return 1.0
    if delta_days <= 30:
        return 0.85
    if delta_days <= 90:
        return 0.65
    if delta_days <= 180:
        return 0.45
    return 0.25


def safe_snippet(text: str, max_len: int = 400) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return compact[:max_len]


def csv_rows(file_bytes: bytes) -> list[dict[str, str]]:
    decoded = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    return [{k.strip(): (v.strip() if isinstance(v, str) else "") for k, v in row.items()} for row in reader]


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result
