from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from pr_monitor_app.api.routes import build_router
from pr_monitor_app.bootstrap.rss_sources import sync_rss_sources
from pr_monitor_app.config import settings
from pr_monitor_app.db import engine, session_scope
from pr_monitor_app.logging import configure_logging
from pr_monitor_app.models import Base
from pr_monitor_app.radar_integration import install_radar_routes, shutdown_radar, startup_radar
from pr_monitor_app.runtime_status import log_pr_runtime_warnings
from pr_monitor_app.scheduler import start_scheduler

# Ensure all model modules are imported so Base.metadata knows every table
import pr_monitor_app.models_analytics as _ma  # noqa: F401
import pr_monitor_app.models_agent as _mag  # noqa: F401
import pr_monitor_app.models_onboarding as _monb  # noqa: F401

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create any missing tables (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.rss_source_bootstrap_enabled:
        async with session_scope() as session:
            await sync_rss_sources(session)

    async with session_scope() as session:
        await log_pr_runtime_warnings(session)

    await startup_radar(app)

    if settings.ingest_enable_scheduler:
        start_scheduler()
    yield
    await shutdown_radar(app)


app = FastAPI(
    title="Narrative Pulse Engine (NPE)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(build_router())
install_radar_routes(app)

# Metrics at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
