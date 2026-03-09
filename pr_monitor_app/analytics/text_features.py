from __future__ import annotations

import re

from pr_monitor_app.config import settings
from pr_monitor_app.utils.text import normalize_text
from pr_monitor_app.utils.hashing import sha256_hex


def select_event_text(*, title: str, summary: str | None, content_text: str | None) -> str:
    """Select the best available text for analytics and normalize.

    Preference order:
      1) content_text
      2) summary
      3) title

    We also enforce a maximum character limit to keep processing predictable.
    """
    raw = (content_text or "").strip() or (summary or "").strip() or (title or "").strip()
    raw = normalize_text(raw)

    # Basic de-noising
    raw = _strip_common_boilerplate(raw)

    if len(raw) > settings.analytics_max_event_text_chars:
        raw = raw[: settings.analytics_max_event_text_chars]

    return raw


def event_text_hash(text: str) -> str:
    return sha256_hex(text)


_boilerplate_re = re.compile(
    r"(?i)\b(cookie(s)?|privacy policy|terms of service|subscribe|sign up|newsletter|accept all)\b"
)


def _strip_common_boilerplate(text: str) -> str:
    # Very light-touch boilerplate stripping.
    # We don't want to accidentally delete meaningful context.
    return _boilerplate_re.sub("", text).strip()
