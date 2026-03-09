from __future__ import annotations

import importlib
import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

_ROUTE_MODULES = [
    "health",
    "agent",
    "clients",
    "topics",
    "subscriptions",
    "sources",
    "events",
    "client_events",
    "briefs",
    "drafts",
    "alerts",
    "feedback",
    "admin",
    "brand_configs",
]


def build_router() -> APIRouter:
    r = APIRouter()
    for module_name in _ROUTE_MODULES:
        try:
            module = importlib.import_module(f"pr_monitor_app.api.routes.{module_name}")
            router = getattr(module, "router")
            r.include_router(router)
        except Exception as exc:
            log.warning("Skipping route module %s: %s", module_name, exc)
    return r
