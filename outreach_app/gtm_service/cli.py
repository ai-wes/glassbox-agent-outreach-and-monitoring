from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn
from sqlalchemy import select

from outreach_app.gtm_service.core.config import get_settings
from outreach_app.gtm_service.db.models import Lead
from outreach_app.gtm_service.db.session import AsyncSessionLocal, init_db
from outreach_app.gtm_service.services.container import ServiceContainer
from outreach_app.gtm_service.services.orchestrator import PipelineOrchestrator
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput, CandidateIngestRequest, RawSignalInput

cli = typer.Typer(add_completion=False)


@cli.command('init-db')
def init_db_command() -> None:
    asyncio.run(init_db())
    typer.echo('database initialized')


@cli.command('serve')
def serve() -> None:
    settings = get_settings()
    uvicorn.run('outreach_app.gtm_service.main:app', host=settings.api_host, port=settings.api_port, reload=settings.app_env == 'development')


@cli.command('seed-demo')
def seed_demo() -> None:
    asyncio.run(_seed_demo())


@cli.command('ingest-rss')
def ingest_rss(feed_url: str) -> None:
    asyncio.run(_ingest_rss(feed_url))


@cli.command('import-csv')
def import_csv(path: Path) -> None:
    asyncio.run(_import_csv(path))


@cli.command('run-due')
def run_due() -> None:
    asyncio.run(_run_due())


@cli.command('rescore-all')
def rescore_all() -> None:
    asyncio.run(_rescore_all())


async def _container() -> ServiceContainer:
    settings = get_settings()
    return ServiceContainer(settings)


async def _seed_demo() -> None:
    await init_db()
    container = await _container()
    async with AsyncSessionLocal() as session:
        orchestrator = PipelineOrchestrator(
            settings=container.settings,
            session=session,
            source_service=container.source_service,
            research_agent=container.research_agent,
            scoring_service=container.scoring_service,
            router=container.router,
            sequence_service=container.sequence_service,
            crm_sync_service=container.crm_sync_service,
        )
        result = await orchestrator.ingest_candidate(
            CandidateIngestRequest(
                company=CandidateCompanyInput(
                    name='Example Bio',
                    domain='examplebio.ai',
                    website='https://examplebio.ai',
                    industry='AI drug discovery biotech',
                    funding_stage='Series A',
                ),
                contact=CandidateContactInput(
                    first_name='Ava',
                    last_name='Stone',
                    title='VP Business Development',
                    email='ava@examplebio.ai',
                    linkedin_url='https://www.linkedin.com/in/ava-stone',
                    email_verified=True,
                ),
                signals=[
                    RawSignalInput(
                        type='funding_event',
                        source='manual',
                        raw_text='Example Bio raised a Series A to advance AI-discovered targets and is hiring translational biology roles.',
                    )
                ],
                snippets=['Raised Series A', 'Hiring translational biology and platform roles'],
                auto_queue=True,
            )
        )
        typer.echo(result.model_dump_json(indent=2))
    await container.aclose()


async def _ingest_rss(feed_url: str) -> None:
    await init_db()
    container = await _container()
    async with AsyncSessionLocal() as session:
        rss_result = await container.source_service.import_rss(feed_url)
        orchestrator = PipelineOrchestrator(
            settings=container.settings,
            session=session,
            source_service=container.source_service,
            research_agent=container.research_agent,
            scoring_service=container.scoring_service,
            router=container.router,
            sequence_service=container.sequence_service,
            crm_sync_service=container.crm_sync_service,
        )
        count = 0
        for candidate in rss_result.items:
            await orchestrator.ingest_candidate(candidate)
            count += 1
        typer.echo(f'ingested {count} items')
    await container.aclose()


async def _import_csv(path: Path) -> None:
    await init_db()
    container = await _container()
    async with AsyncSessionLocal() as session:
        content = path.read_bytes()
        candidates = container.source_service.import_csv(content)
        orchestrator = PipelineOrchestrator(
            settings=container.settings,
            session=session,
            source_service=container.source_service,
            research_agent=container.research_agent,
            scoring_service=container.scoring_service,
            router=container.router,
            sequence_service=container.sequence_service,
            crm_sync_service=container.crm_sync_service,
        )
        count = 0
        for candidate in candidates:
            await orchestrator.ingest_candidate(candidate)
            count += 1
        typer.echo(f'imported {count} leads')
    await container.aclose()


async def _run_due() -> None:
    await init_db()
    container = await _container()
    async with AsyncSessionLocal() as session:
        result = await container.sequence_service.run_due_messages(session)
        typer.echo(result.model_dump_json(indent=2))
    await container.aclose()


async def _rescore_all() -> None:
    await init_db()
    container = await _container()
    async with AsyncSessionLocal() as session:
        orchestrator = PipelineOrchestrator(
            settings=container.settings,
            session=session,
            source_service=container.source_service,
            research_agent=container.research_agent,
            scoring_service=container.scoring_service,
            router=container.router,
            sequence_service=container.sequence_service,
            crm_sync_service=container.crm_sync_service,
        )
        lead_ids = [lead_id for (lead_id,) in (await session.execute(select(Lead.id))).all()]
        for lead_id in lead_ids:
            await orchestrator.rescore_lead(lead_id)
        typer.echo(f'rescored {len(lead_ids)} leads')
    await container.aclose()


if __name__ == '__main__':
    cli()
