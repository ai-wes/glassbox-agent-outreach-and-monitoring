from __future__ import annotations

from fastapi import FastAPI

from glassbox_radar.api import router as radar_router
from glassbox_radar.db import init_db as init_radar_db
from glassbox_radar.db import SessionLocal as RadarSessionLocal
from glassbox_radar.runtime_status import log_radar_runtime_warnings
from pr_monitor_app.api.routes import build_router
from pr_monitor_app.bootstrap.rss_sources import sync_rss_sources
from pr_monitor_app.config import settings
from pr_monitor_app.db import engine, session_scope
from pr_monitor_app.models import Base
import pr_monitor_app.models_onboarding as _monb  # noqa: F401
from pr_monitor_app.runtime_status import log_pr_runtime_warnings


async def startup_pr_monitor(app: FastAPI) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.rss_source_bootstrap_enabled:
        async with session_scope() as session:
            await sync_rss_sources(session)
    async with session_scope() as session:
        await log_pr_runtime_warnings(session)

    await init_radar_db()
    app.state.pr_monitor_settings = settings

    async with RadarSessionLocal() as session:
        await log_radar_runtime_warnings(session)


async def shutdown_pr_monitor(app: FastAPI) -> None:
    # Reserved for future lifecycle cleanup.
    _ = app


def install_pr_monitor_routes(app: FastAPI) -> None:
    app.include_router(build_router(include_health=False))
    app.include_router(radar_router, prefix="/radar")
