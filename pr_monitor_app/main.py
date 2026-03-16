from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from pr_monitor_app.api.routes import build_router
from pr_monitor_app.bootstrap.rss_sources import sync_rss_sources
from pr_monitor_app.config import settings
from pr_monitor_app.db import engine, session_scope
from pr_monitor_app.logging import configure_logging, get_logger
from pr_monitor_app.models import Base
from pr_monitor_app.radar_integration import install_radar_routes, shutdown_radar, startup_radar
from pr_monitor_app.runtime_status import log_pr_runtime_warnings
from pr_monitor_app.scheduler import start_scheduler

# Ensure all model modules are imported so Base.metadata knows every table
import pr_monitor_app.models_analytics as _ma  # noqa: F401
import pr_monitor_app.models_agent as _mag  # noqa: F401
import pr_monitor_app.models_onboarding as _monb  # noqa: F401

configure_logging(settings.log_level)
logger = get_logger(component="pr_monitor_app.main")


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


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")
    logger.warning(
        "request_validation_error",
        method=request.method,
        path=request.url.path,
        errors=exc.errors(),
        body=body_text,
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "message": "Request validation failed",
            "path": request.url.path,
            "body": body_text,
        },
    )

app.include_router(build_router())
install_radar_routes(app)

# Metrics at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
