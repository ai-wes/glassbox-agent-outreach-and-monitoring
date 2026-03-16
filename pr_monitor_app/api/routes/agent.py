from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.bootstrap.rss_sources import MANAGED_BY, managed_feed_urls
from glassbox_radar.core.config import get_settings as get_radar_settings
from glassbox_radar.db import SessionLocal as RadarSessionLocal
from glassbox_radar.models import Company as RadarCompany
from glassbox_radar.models import Opportunity as RadarOpportunity
from glassbox_radar.models import Program as RadarProgram
from glassbox_radar.runtime_status import collect_radar_runtime_status
from glassbox_radar.schemas import CompanyOut as RadarCompanyOut
from glassbox_radar.schemas import OpportunityOut as RadarOpportunityOut
from glassbox_radar.schemas import ProgramOut as RadarProgramOut
from glassbox_radar.services.pipeline import RadarPipeline
from glassbox_radar.services.watchlist_sync import sync_watchlist
from glassbox_radar.watchlist import load_watchlist
from pr_monitor_app.agent_runner import AgentProcessor
from pr_monitor_app.api.deps import get_session
from pr_monitor_app.api_schemas import (
    AgentJobOut,
    AgentOutputOut,
    OpenClawClaimResponse,
    OpenClawCompleteIn,
    OpenClawFailIn,
)
from pr_monitor_app.models import DailyPodcastReport, Event, RawEvent, Source
from pr_monitor_app.models_agent import AgentJob, AgentJobStatus, AgentOutput

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/skills/next", response_model=OpenClawClaimResponse)
async def claim_agent_jobs_for_openclaw(
    batch_size: int = Query(default=1, ge=1, le=50),
    brand_name: str | None = Query(default=None, description="Optional brand name override for job context"),
    brand_config_id: uuid.UUID | None = Query(default=None, description="Optional brand config id override for job context"),
) -> OpenClawClaimResponse:
    p = AgentProcessor()
    jobs = p.claim_next_for_openclaw(
        batch_size=batch_size,
        brand_name=brand_name.strip() if brand_name else None,
        brand_config_id=brand_config_id,
    )
    return OpenClawClaimResponse(jobs=jobs)


@router.post("/skills/{job_id}/complete")
async def complete_agent_job_from_openclaw(job_id: uuid.UUID, payload: OpenClawCompleteIn) -> dict:
    p = AgentProcessor()
    try:
        res = p.complete_job_from_openclaw(
            job_id=job_id,
            output_json=payload.output,
            model=payload.model,
            summary_text=payload.summary_text,
            meta_json=payload.meta,
        )
        return {"status": "ok", "result": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{job_id}/fail")
async def fail_agent_job_from_openclaw(job_id: uuid.UUID, payload: OpenClawFailIn) -> dict:
    p = AgentProcessor()
    try:
        res = p.fail_job_from_openclaw(job_id=job_id, error_message=payload.error_message)
        return {"status": "ok", "result": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/jobs", response_model=list[AgentJobOut])
async def list_agent_jobs(
    session: AsyncSession = Depends(get_session),
    client_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    q = select(AgentJob).order_by(AgentJob.created_at.desc())
    if client_id:
        q = q.where(AgentJob.client_id == client_id)
    if status:
        st = status.strip().lower()
        try:
            q = q.where(AgentJob.status == AgentJobStatus(st))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid status")

    rows = (await session.execute(q.limit(int(limit)))).scalars().all()
    return [
        AgentJobOut(
            id=r.id,
            event_id=r.event_id,
            client_id=r.client_id,
            topic_ids=list(r.topic_ids_json or []),
            top_relevance_score=float(r.top_relevance_score or 0.0),
            priority=r.priority,
            status=r.status.value,
            agent_version=r.agent_version,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
            output_id=r.output_id,
            error_message=r.error_message,
        )
        for r in rows
    ]


@router.get("/jobs/{job_id}", response_model=AgentJobOut)
async def get_agent_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(AgentJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return AgentJobOut(
        id=row.id,
        event_id=row.event_id,
        client_id=row.client_id,
        topic_ids=list(row.topic_ids_json or []),
        top_relevance_score=float(row.top_relevance_score or 0.0),
        priority=row.priority,
        status=row.status.value,
        agent_version=row.agent_version,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        output_id=row.output_id,
        error_message=row.error_message,
    )


@router.get("/outputs", response_model=list[AgentOutputOut])
async def list_agent_outputs(
    session: AsyncSession = Depends(get_session),
    client_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    q = select(AgentOutput).order_by(AgentOutput.generated_at.desc())
    if client_id:
        q = q.where(AgentOutput.client_id == client_id)
    if event_id:
        q = q.where(AgentOutput.event_id == event_id)

    rows = (await session.execute(q.limit(int(limit)))).scalars().all()
    return [
        AgentOutputOut(
            id=r.id,
            event_id=r.event_id,
            client_id=r.client_id,
            agent_version=r.agent_version,
            model=r.model,
            generated_at=r.generated_at,
            output=dict(r.output_json or {}),
            summary_text=r.summary_text,
            prompt_tokens=r.prompt_tokens,
            output_tokens=r.output_tokens,
            meta=dict(r.meta_json or {}),
        )
        for r in rows
    ]


@router.get("/outputs/{output_id}", response_model=AgentOutputOut)
async def get_agent_output(output_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(AgentOutput, output_id)
    if row is None:
        raise HTTPException(status_code=404, detail="output not found")
    return AgentOutputOut(
        id=row.id,
        event_id=row.event_id,
        client_id=row.client_id,
        agent_version=row.agent_version,
        model=row.model,
        generated_at=row.generated_at,
        output=dict(row.output_json or {}),
        summary_text=row.summary_text,
        prompt_tokens=row.prompt_tokens,
        output_tokens=row.output_tokens,
        meta=dict(row.meta_json or {}),
    )


@router.get("/daily-podcast/reports")
async def list_daily_podcast_reports(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, ge=1, le=365),
    include_content: bool = Query(default=False),
):
    rows = (
        (
            await session.execute(
                select(DailyPodcastReport)
                .order_by(DailyPodcastReport.report_date.desc(), DailyPodcastReport.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "report_date": r.report_date.isoformat() if isinstance(r.report_date, date) else None,
            "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "source_path": r.source_path,
            "source_hash": r.source_hash,
            "error_message": r.error_message,
            "summary_excerpt": (r.report_md or "")[:280].strip(),
            "report_md": r.report_md if include_content else None,
            "meta": dict(r.meta_json or {}),
        }
        for r in rows
    ]


@router.get("/daily-podcast/reports/latest")
async def get_latest_daily_podcast_report(
    session: AsyncSession = Depends(get_session),
    include_content: bool = Query(default=True),
):
    row = (
        (
            await session.execute(
                select(DailyPodcastReport)
                .order_by(DailyPodcastReport.report_date.desc(), DailyPodcastReport.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="daily podcast report not found")
    return {
        "id": str(row.id),
        "report_date": row.report_date.isoformat() if isinstance(row.report_date, date) else None,
        "title": row.title,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "source_path": row.source_path,
        "source_hash": row.source_hash,
        "error_message": row.error_message,
        "summary_excerpt": (row.report_md or "")[:280].strip(),
        "report_md": row.report_md if include_content else None,
        "meta": dict(row.meta_json or {}),
    }


@router.get("/reports/daily-podcast")
async def list_daily_podcast_report_summaries(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, ge=1, le=365),
):
    rows = (
        (
            await session.execute(
                select(DailyPodcastReport)
                .order_by(DailyPodcastReport.report_date.desc(), DailyPodcastReport.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "report_date": r.report_date.isoformat() if isinstance(r.report_date, date) else None,
            "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "summary_excerpt": (r.report_md or "")[:280].strip(),
            "source_path": r.source_path,
        }
        for r in rows
    ]


@router.get("/reports/daily-podcast/{report_id}")
async def get_daily_podcast_report(report_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(DailyPodcastReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="daily podcast report not found")
    return {
        "id": str(row.id),
        "report_date": row.report_date.isoformat() if isinstance(row.report_date, date) else None,
        "title": row.title,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "source_path": row.source_path,
        "source_hash": row.source_hash,
        "error_message": row.error_message,
        "report_md": row.report_md,
        "meta": dict(row.meta_json or {}),
    }


@router.get("/reports/market/events")
async def list_market_event_reports(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, ge=1, le=200),
    env_rss_only: bool = Query(default=True),
):
    stmt = (
        select(Event, RawEvent, Source)
        .join(RawEvent, RawEvent.id == Event.raw_event_id, isouter=True)
        .join(Source, Source.id == RawEvent.source_id, isouter=True)
        .order_by(Event.published_at.desc(), Event.created_at.desc())
        .limit(limit)
    )
    canonical_feed_urls = managed_feed_urls()
    if env_rss_only and canonical_feed_urls:
        stmt = stmt.where(Source.url.in_(canonical_feed_urls))

    rows = (await session.execute(stmt)).all()
    if rows:
        return [
            {
                "event_id": str(event.id),
                "title": event.title,
                "url": event.url,
                "source_type": event.source_type.value,
                "published_at": event.published_at.isoformat() if event.published_at else None,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "source_name": source.name if source else None,
                "source_url": source.url if source else None,
                "authority_score": float(source.authority_score) if source else None,
                "managed_by": (source.config or {}).get("managed_by") if source else None,
                "feed_category": (source.config or {}).get("feed_category") if source else None,
                "summary_excerpt": (event.raw_text or "")[:280].strip(),
                "detected_entities": list(event.detected_entities or [])[:12],
                "sentiment": float(event.sentiment),
                "is_env_feed": bool(source and ((source.config or {}).get("managed_by") == MANAGED_BY)),
                "is_normalized": True,
            }
            for event, _raw_event, source in rows
        ]

    raw_stmt = (
        select(RawEvent, Source)
        .join(Source, Source.id == RawEvent.source_id)
        .order_by(RawEvent.fetched_at.desc())
        .limit(limit)
    )
    if env_rss_only and canonical_feed_urls:
        raw_stmt = raw_stmt.where(Source.url.in_(canonical_feed_urls))
    raw_rows = (await session.execute(raw_stmt)).all()
    return [
        {
            "event_id": str(raw_event.id),
            "title": (raw_event.payload or {}).get("title") or "Untitled event",
            "url": (raw_event.payload or {}).get("url") or source.url,
            "source_type": (raw_event.payload or {}).get("source_type") or source.source_type.value,
            "published_at": (raw_event.payload or {}).get("published_at"),
            "created_at": raw_event.fetched_at.isoformat() if raw_event.fetched_at else None,
            "source_name": source.name,
            "source_url": source.url,
            "authority_score": float(source.authority_score),
            "managed_by": (source.config or {}).get("managed_by"),
            "feed_category": (source.config or {}).get("feed_category"),
            "summary_excerpt": ((raw_event.payload or {}).get("raw_text") or "")[:280].strip(),
            "detected_entities": [],
            "sentiment": None,
            "is_env_feed": bool((source.config or {}).get("managed_by") == MANAGED_BY),
            "is_normalized": False,
        }
        for raw_event, source in raw_rows
    ]


@router.get("/radar/companies", response_model=list[RadarCompanyOut])
async def list_radar_companies(limit: int = Query(default=100, ge=1, le=500)):
    async with RadarSessionLocal() as session:
        rows = (await session.execute(select(RadarCompany).order_by(RadarCompany.name.asc()).limit(limit))).scalars().all()
    return list(rows)


@router.get("/radar/programs", response_model=list[RadarProgramOut])
async def list_radar_programs(limit: int = Query(default=100, ge=1, le=500)):
    async with RadarSessionLocal() as session:
        rows = (
            await session.execute(
                select(RadarProgram)
                .order_by(RadarProgram.latest_radar_score.desc().nullslast(), RadarProgram.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return list(rows)


@router.get("/radar/opportunities", response_model=list[RadarOpportunityOut])
async def list_radar_opportunities(limit: int = Query(default=100, ge=1, le=500)):
    async with RadarSessionLocal() as session:
        rows = (
            await session.execute(
                select(RadarOpportunity)
                .order_by(RadarOpportunity.radar_score.desc(), RadarOpportunity.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return list(rows)


@router.get("/radar/status")
async def get_radar_status() -> dict[str, object]:
    async with RadarSessionLocal() as session:
        return await collect_radar_runtime_status(session)


@router.get("/reports/radar/opportunities")
async def list_radar_report_summaries(limit: int = Query(default=50, ge=1, le=200)):
    async with RadarSessionLocal() as session:
        rows = (
            await session.execute(
                select(RadarOpportunity, RadarCompany, RadarProgram)
                .join(RadarCompany, RadarCompany.id == RadarOpportunity.company_id)
                .join(RadarProgram, RadarProgram.id == RadarOpportunity.program_id)
                .order_by(RadarOpportunity.updated_at.desc())
                .limit(limit)
            )
        ).all()

    return [
        {
            "opportunity_id": opportunity.id,
            "company_name": company.name,
            "program_id": program.id,
            "program_target": program.target,
            "asset_name": program.asset_name,
            "status": opportunity.status.value,
            "tier": opportunity.tier,
            "radar_score": opportunity.radar_score,
            "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
            "dossier_path": opportunity.dossier_path,
            "sheet_row_reference": opportunity.sheet_row_reference,
        }
        for opportunity, company, program in rows
    ]


@router.get("/reports/radar/opportunities/{opportunity_id}")
async def get_radar_report(opportunity_id: str, include_content: bool = Query(default=True)):
    async with RadarSessionLocal() as session:
        row = (
            await session.execute(
                select(RadarOpportunity, RadarCompany, RadarProgram)
                .join(RadarCompany, RadarCompany.id == RadarOpportunity.company_id)
                .join(RadarProgram, RadarProgram.id == RadarOpportunity.program_id)
                .where(RadarOpportunity.id == opportunity_id)
            )
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="opportunity not found")

    opportunity, company, program = row
    dossier_content = None
    if include_content and opportunity.dossier_path:
        dossier_path = Path(opportunity.dossier_path)
        if dossier_path.exists() and dossier_path.is_file():
            dossier_content = dossier_path.read_text(encoding="utf-8")

    return {
        "opportunity_id": opportunity.id,
        "company": {"id": company.id, "name": company.name, "domain": company.domain},
        "program": {
            "id": program.id,
            "asset_name": program.asset_name,
            "target": program.target,
            "indication": program.indication,
            "stage": program.stage,
        },
        "report": {
            "status": opportunity.status.value,
            "tier": opportunity.tier,
            "radar_score": opportunity.radar_score,
            "milestone_score": opportunity.milestone_score,
            "fragility_score": opportunity.fragility_score,
            "capital_score": opportunity.capital_score,
            "reachability_score": opportunity.reachability_score,
            "outreach_angle": opportunity.outreach_angle,
            "risk_hypothesis": opportunity.risk_hypothesis,
            "capital_exposure_band": opportunity.capital_exposure_band,
            "sheet_row_reference": opportunity.sheet_row_reference,
            "dossier_path": opportunity.dossier_path,
            "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
            "dossier_markdown": dossier_content,
        },
    }


@router.get("/reports/radar/opportunities/{opportunity_id}/download")
async def download_radar_dossier(opportunity_id: str):
    async with RadarSessionLocal() as session:
        opportunity = await session.get(RadarOpportunity, opportunity_id)

    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    if not opportunity.dossier_path:
        raise HTTPException(status_code=404, detail="dossier not available")

    dossier_path = Path(opportunity.dossier_path)
    if not dossier_path.exists() or not dossier_path.is_file():
        raise HTTPException(status_code=404, detail="dossier file missing")

    return FileResponse(
        path=str(dossier_path),
        filename=dossier_path.name,
        media_type="text/markdown",
    )


@router.post("/radar/pipeline/run")
async def run_radar_pipeline() -> dict:
    pipeline = RadarPipeline(RadarSessionLocal)
    return await pipeline.run()


@router.post("/radar/watchlist/sync")
async def run_radar_watchlist_sync() -> dict:
    settings = get_radar_settings()
    companies = load_watchlist(settings.watchlist_path)
    async with RadarSessionLocal() as session:
        return await sync_watchlist(session, companies)
