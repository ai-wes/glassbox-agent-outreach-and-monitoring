from __future__ import annotations

from fastapi import Header, HTTPException

from app.core.config import settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    keys = settings.agent_keys()
    if not keys:
        return "dev-open"
    if not x_api_key or x_api_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return x_api_key
