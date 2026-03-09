from __future__ import annotations

from fastapi import FastAPI

from outreach_app.gtm_service.api.routes import router as gtm_router
from outreach_app.gtm_service.core.config import get_settings
from outreach_app.gtm_service.core.logging import configure_logging
from outreach_app.gtm_service.db.session import AsyncSessionLocal, init_db
from outreach_app.gtm_service.services.container import ServiceContainer
from outreach_app.gtm_service.services.jobs import JobScheduler
from outreach_app.gtm_service.services.orchestrator import PipelineOrchestrator


async def startup_gtm(app: FastAPI) -> None:
    settings = get_settings()
    configure_logging(settings)
    container = ServiceContainer(settings)
    scheduler = JobScheduler(settings)

    app.state.gtm_settings = settings
    app.state.gtm_container = container
    app.state.gtm_scheduler = scheduler

    await init_db()

    async def run_due_job() -> None:
        async with AsyncSessionLocal() as session:
            await container.sequence_service.run_due_messages(session)

    async def ingest_feed_job(feed_url: str) -> None:
        async with AsyncSessionLocal() as session:
            orchestrator = PipelineOrchestrator(
                settings=settings,
                session=session,
                source_service=container.source_service,
                research_agent=container.research_agent,
                scoring_service=container.scoring_service,
                router=container.router,
                sequence_service=container.sequence_service,
                crm_sync_service=container.crm_sync_service,
            )
            rss_result = await container.source_service.import_rss(feed_url)
            for candidate in rss_result.items:
                candidate.auto_queue = False
                await orchestrator.ingest_candidate(candidate)

    scheduler.add_recurring_jobs(run_due=run_due_job, ingest_feed=ingest_feed_job)
    scheduler.start()


async def shutdown_gtm(app: FastAPI) -> None:
    scheduler = getattr(app.state, "gtm_scheduler", None)
    if scheduler is not None:
        scheduler.shutdown()

    container = getattr(app.state, "gtm_container", None)
    if container is not None:
        await container.aclose()


def install_gtm_routes(app: FastAPI) -> None:
    app.include_router(gtm_router, prefix="/crm/gtm")
