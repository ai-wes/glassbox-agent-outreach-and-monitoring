from __future__ import annotations

from fastapi import Header, HTTPException, status

from glassbox_radar.core.config import get_settings


async def require_api_token(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    expected = settings.api_token
    if not expected:
        return

    bearer_token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization.split(" ", 1)[1].strip()

    provided = x_api_key or bearer_token
    if provided == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API token",
    )
