from __future__ import annotations

from fastapi import APIRouter

from app.api.routes_core import router as core_router
from app.api.routes_rag import router as rag_router
from app.api.routes_sheets import router as sheets_router
from app.api.routes_agent import router as agent_router

router = APIRouter()
router.include_router(core_router)
router.include_router(rag_router)
router.include_router(sheets_router)
router.include_router(agent_router)
