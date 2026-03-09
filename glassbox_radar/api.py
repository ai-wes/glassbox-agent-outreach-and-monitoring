from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from glassbox_radar.core.security import require_api_token
from glassbox_radar.db import SessionLocal, get_db, init_db
from glassbox_radar.models import Company, Opportunity, Program
from glassbox_radar.schemas import CompanyOut, OpportunityOut, ProgramOut
from glassbox_radar.services.pipeline import RadarPipeline
from glassbox_radar.services.scheduler import EmbeddedScheduler
from glassbox_radar.services.watchlist_sync import sync_watchlist
from glassbox_radar.watchlist import load_watchlist
from glassbox_radar.core.config import get_settings
from glassbox_radar.core.logging import configure_logging


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_api_token)])
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    try:
        from fastapi.templating import Jinja2Templates
    except AssertionError as exc:
        raise HTTPException(status_code=503, detail="dashboard templates unavailable until jinja2 is installed") from exc

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
    companies_result = await db.execute(select(Company))
    programs_result = await db.execute(select(Program))
    opportunities_result = await db.execute(
        select(Opportunity)
        .options(selectinload(Opportunity.company), selectinload(Opportunity.program))
        .order_by(Opportunity.radar_score.desc())
        .limit(25)
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "companies": companies_result.scalars().all(),
            "programs": programs_result.scalars().all(),
            "opportunities": opportunities_result.scalars().unique().all(),
        },
    )


@router.get("/api/companies", response_model=list[CompanyOut], dependencies=[Depends(require_api_token)])
async def list_companies(db: AsyncSession = Depends(get_db)) -> list[Company]:
    result = await db.execute(select(Company).order_by(Company.name.asc()))
    return list(result.scalars().all())


@router.get("/api/programs", response_model=list[ProgramOut], dependencies=[Depends(require_api_token)])
async def list_programs(db: AsyncSession = Depends(get_db)) -> list[Program]:
    result = await db.execute(select(Program).order_by(Program.latest_radar_score.desc().nullslast(), Program.created_at.desc()))
    return list(result.scalars().all())


@router.get("/api/opportunities", response_model=list[OpportunityOut], dependencies=[Depends(require_api_token)])
async def list_opportunities(db: AsyncSession = Depends(get_db)) -> list[Opportunity]:
    result = await db.execute(select(Opportunity).order_by(Opportunity.radar_score.desc(), Opportunity.updated_at.desc()))
    return list(result.scalars().all())


@router.post("/api/pipeline/run", dependencies=[Depends(require_api_token)])
async def run_pipeline() -> dict:
    pipeline = RadarPipeline(SessionLocal)
    return await pipeline.run()


@router.post("/api/watchlist/sync", dependencies=[Depends(require_api_token)])
async def run_watchlist_sync(db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    companies = load_watchlist(settings.watchlist_path)
    return await sync_watchlist(db, companies)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    await init_db()
    scheduler = EmbeddedScheduler(SessionLocal)
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Glassbox Radar", lifespan=lifespan)
    app.include_router(router)
    return app
