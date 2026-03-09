from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
