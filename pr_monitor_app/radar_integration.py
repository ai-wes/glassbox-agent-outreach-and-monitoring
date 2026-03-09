from __future__ import annotations

from fastapi import FastAPI

from glassbox_radar.api import router as radar_router
from glassbox_radar.core.config import get_settings
from glassbox_radar.core.logging import configure_logging
from glassbox_radar.db import SessionLocal, init_db
from glassbox_radar.services.scheduler import EmbeddedScheduler


async def startup_radar(app: FastAPI) -> None:
    settings = get_settings()
    configure_logging()
    await init_db()

    scheduler = EmbeddedScheduler(SessionLocal)
    app.state.radar_settings = settings
    app.state.radar_scheduler = scheduler
    await scheduler.start()


async def shutdown_radar(app: FastAPI) -> None:
    scheduler = getattr(app.state, "radar_scheduler", None)
    if scheduler is not None:
        await scheduler.stop()


def install_radar_routes(app: FastAPI) -> None:
    app.include_router(radar_router, prefix="/radar")
