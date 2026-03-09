from __future__ import annotations

import secrets
import time


def new_id(prefix: str, nbytes: int = 12) -> str:
    token = secrets.token_urlsafe(nbytes).rstrip("=")
    return f"{prefix}_{token}"


def unix_ms() -> int:
    return int(time.time() * 1000)
