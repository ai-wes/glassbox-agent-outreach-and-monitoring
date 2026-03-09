from __future__ import annotations

import hashlib


def sha256_hex(data: str) -> str:
    return hashlib.sha256((data or "").encode("utf-8")).hexdigest()
