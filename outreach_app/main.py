from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.api import router as api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.init import init_db
from app.scheduler import start_scheduler, stop_scheduler
from outreach_app.gtm_service.integration import install_gtm_routes, shutdown_gtm, startup_gtm
from pr_monitor_app.integration import install_pr_monitor_routes, shutdown_pr_monitor, startup_pr_monitor


def create_app() -> FastAPI:
    configure_logging()
    init_db()

    app = FastAPI(title="Glassbox Operator API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    install_gtm_routes(app)
    install_pr_monitor_routes(app)

    @app.on_event("startup")
    async def startup_scheduler() -> None:
        if settings.schedule_enable_runner:
            start_scheduler()
        await startup_gtm(app)
        await startup_pr_monitor(app)

    @app.on_event("shutdown")
    async def shutdown_scheduler() -> None:
        stop_scheduler()
        await shutdown_gtm(app)
        await shutdown_pr_monitor(app)

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @app.get("/healthz", tags=["system"])
    def healthz():
        return {"ok": True, "app": settings.app_name, "env": settings.environment}

    return app


app = create_app()
