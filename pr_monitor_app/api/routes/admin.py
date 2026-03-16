from __future__ import annotations

import json
import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.analytics.ai_pr_measurement import run_ai_pr_measurement_from_settings
from pr_monitor_app.api.deps import get_session
from pr_monitor_app.bootstrap.rss_sources import sync_rss_sources
from pr_monitor_app.config import settings
from pr_monitor_app.models import DailyPodcastReport
from pr_monitor_app.runtime_status import collect_pr_runtime_status
from pr_monitor_app.schedule_config import get_beat_schedule_seconds, set_beat_schedule_seconds
from pr_monitor_app.scheduler import get_scheduler_status, update_scheduler_tick_seconds
from pr_monitor_app.state import StateStore

router = APIRouter(prefix="/admin", tags=["admin"])


class SchedulerPatchIn(BaseModel):
    ingest_tick_seconds: int = Field(ge=1, le=86400)


class BeatSchedulePatchIn(BaseModel):
    ingest_seconds: int | None = Field(default=None, ge=1, le=86400)
    process_seconds: int | None = Field(default=None, ge=1, le=86400)


class RepairEventsIn(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)
    rebuild_clusters: bool = True


@router.post("/run/ingest")
async def run_ingest(sync: bool = Query(default=False), session: AsyncSession = Depends(get_session)) -> dict:
    if sync:
        try:
            from pr_monitor_app.pipeline.run import run_ingestion
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"ingestion pipeline unavailable: {exc}")

        res = await run_ingestion(session)
        await session.commit()
        return {"mode": "sync", "result": res}

    try:
        from pr_monitor_app.tasks.tasks import ingest_sources_task
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ingest task unavailable: {exc}")

    task = ingest_sources_task.delay(force=True)
    return {"mode": "async", "task_id": task.id}


@router.post("/run/process")
async def run_process(sync: bool = Query(default=False), session: AsyncSession = Depends(get_session)) -> dict:
    if sync:
        try:
            from pr_monitor_app.pipeline.run import run_processing
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"processing pipeline unavailable: {exc}")

        res = await run_processing(session)
        await session.commit()
        return {"mode": "sync", "result": res}

    try:
        from pr_monitor_app.tasks.tasks import process_pipeline_task
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"process task unavailable: {exc}")

    task = process_pipeline_task.delay(force=True)
    return {"mode": "async", "task_id": task.id}


@router.post("/run/repair-events")
async def repair_events(payload: RepairEventsIn, session: AsyncSession = Depends(get_session)) -> dict:
    from pr_monitor_app.pipeline.clustering import rebuild_all_clusters
    from pr_monitor_app.pipeline.normalization import refresh_normalized_events

    refreshed = await refresh_normalized_events(session, limit=payload.limit)
    clusters = None
    if payload.rebuild_clusters:
        clusters = await rebuild_all_clusters(session)
    await session.commit()
    return {"mode": "sync", "refresh": refreshed, "clusters": clusters}


@router.post("/run/daily-podcast")
async def run_daily_podcast() -> dict:
    try:
        from pr_monitor_app.tasks.tasks import daily_podcast_task
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"daily podcast task unavailable: {exc}")

    task = daily_podcast_task.delay()
    return {"mode": "async", "task_id": task.id}


@router.post("/bootstrap/rss-sources")
async def bootstrap_rss_sources(session: AsyncSession = Depends(get_session)) -> dict:
    result = await sync_rss_sources(session)
    await session.commit()
    return result


@router.get("/daily-podcast/status")
async def get_daily_podcast_status(session: AsyncSession = Depends(get_session)) -> dict:
    latest = (
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
    return {
        "enabled": bool(settings.daily_podcast_enabled),
        "schedule_utc": {
            "hour": int(settings.daily_podcast_hour_utc),
            "minute": int(settings.daily_podcast_minute_utc),
        },
        "latest_report": (
            {
                "id": str(latest.id),
                "report_date": latest.report_date.isoformat() if latest.report_date else None,
                "title": latest.title,
                "status": latest.status,
                "created_at": latest.created_at.isoformat() if latest.created_at else None,
                "source_path": latest.source_path,
                "source_hash": latest.source_hash,
                "error_message": latest.error_message,
                "summary_excerpt": (latest.report_md or "")[:280].strip(),
            }
            if latest
            else None
        ),
    }


@router.get("/runtime-status")
async def get_runtime_status(session: AsyncSession = Depends(get_session)) -> dict:
    return await collect_pr_runtime_status(session)


@router.get("/scheduler")
async def get_scheduler() -> dict:
    state = StateStore.from_settings()
    beat = get_beat_schedule_seconds(state)
    aps = get_scheduler_status()
    return {
        "ingest_enable_scheduler": bool(settings.ingest_enable_scheduler),
        "daily_podcast_enabled": bool(settings.daily_podcast_enabled),
        "daily_podcast_time_utc": {
            "hour": int(settings.daily_podcast_hour_utc),
            "minute": int(settings.daily_podcast_minute_utc),
        },
        "apscheduler": aps,
        "beat_schedule_seconds": beat,
    }


@router.patch("/scheduler")
async def patch_scheduler(payload: SchedulerPatchIn) -> dict:
    updated = update_scheduler_tick_seconds(payload.ingest_tick_seconds)
    state = StateStore.from_settings()
    beat = get_beat_schedule_seconds(state)
    return {
        "ingest_enable_scheduler": bool(settings.ingest_enable_scheduler),
        "daily_podcast_enabled": bool(settings.daily_podcast_enabled),
        "daily_podcast_time_utc": {
            "hour": int(settings.daily_podcast_hour_utc),
            "minute": int(settings.daily_podcast_minute_utc),
        },
        "apscheduler": updated,
        "beat_schedule_seconds": beat,
    }


@router.patch("/beat-schedule")
async def patch_beat_schedule(payload: BeatSchedulePatchIn) -> dict:
    if payload.ingest_seconds is None and payload.process_seconds is None:
        return {
            "updated": False,
            "reason": "no_fields_provided",
            "beat_schedule_seconds": get_beat_schedule_seconds(StateStore.from_settings()),
        }

    state = StateStore.from_settings()
    beat = set_beat_schedule_seconds(
        state,
        ingest_seconds=payload.ingest_seconds,
        process_seconds=payload.process_seconds,
    )
    return {
        "updated": True,
        "beat_schedule_seconds": beat,
        "note": "Effective cadence applies on next beat-triggered task run.",
    }


@router.post("/run/analysis/ai-pr")
async def run_ai_pr_analysis(
    brand_name: str | None = Query(default=None, description="Optional brand name to run against"),
    brand_config_id: str | None = Query(default=None, description="Optional brand config UUID to run against"),
) -> dict:
    import asyncio

    res = await asyncio.to_thread(
        run_ai_pr_measurement_from_settings,
        brand_name=brand_name.strip() if brand_name else None,
        brand_config_id=brand_config_id,
    )
    return {"mode": "sync", "result": res}


@router.post("/run/analysis/ai-pr/report")
async def generate_ai_pr_report(
    output_dir: str = Query(default="output", description="Directory containing run output files"),
) -> dict:
    """Re-generate the HTML report from a previous AI PR measurement run output."""
    import asyncio

    from pr_monitor_app.ai_pr_measurement.report_compiler import compile_report_from_output_dir

    path = await asyncio.to_thread(compile_report_from_output_dir, output_dir)
    return {"report_path": path}


def _read_json(path: str) -> dict | list | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/analysis/ai-pr/output")
async def get_ai_pr_output(
    output_dir: str | None = Query(default=None, description="Directory containing AI PR output files"),
) -> dict:
    """Expose latest AI PR output artifacts via API."""
    out_dir = (output_dir or settings.ai_pr_measurement_output_dir or "output").strip()

    import asyncio

    def _load() -> dict:
        run_summary = _read_json(os.path.join(out_dir, "run_summary.json"))
        demand_summary = _read_json(os.path.join(out_dir, "demand_summary.json"))
        visibility_index = _read_json(os.path.join(out_dir, "visibility_index.json"))
        zero_click = _read_json(os.path.join(out_dir, "zero_click_summary.json"))
        referral_summary = _read_json(os.path.join(out_dir, "referral_summary.json"))
        entity_checks = _read_json(os.path.join(out_dir, "entity_checks.json"))
        return {
            "output_dir": out_dir,
            "run_summary": run_summary,
            "demand_summary": demand_summary,
            "visibility_index": visibility_index,
            "zero_click_summary": zero_click,
            "referral_summary": referral_summary,
            "entity_checks": entity_checks,
        }

    return await asyncio.to_thread(_load)


@router.get("/analysis/ai-pr/brand-demand")
async def get_ai_pr_brand_demand(
    db_path: str | None = Query(default=None, description="Path to AI PR SQLite DB"),
    keyword: str | None = Query(default=None, description="Filter by exact keyword"),
    brand_name: str | None = Query(default=None, description="Filter keywords that contain brand name"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    """Query brand demand rows from AI PR measurement SQLite storage."""
    target_db = (db_path or settings.ai_pr_measurement_db_path or "ai_pr_measurement.db").strip()

    import asyncio

    def _query() -> dict:
        if not os.path.exists(target_db):
            return {"db_path": target_db, "count": 0, "rows": [], "reason": "db_not_found"}

        conn = sqlite3.connect(target_db)
        conn.row_factory = sqlite3.Row
        try:
            clauses: list[str] = []
            params: list[str | int] = []
            if keyword:
                clauses.append("keyword = ?")
                params.append(keyword.strip())
            if brand_name:
                clauses.append("keyword LIKE ?")
                params.append(f"%{brand_name.strip()}%")

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            q = (
                "SELECT id, timestamp, keyword, date, interest_value, source_api, status "
                f"FROM brand_demand {where} ORDER BY date DESC, timestamp DESC LIMIT ?"
            )
            params.append(int(limit))
            rows = conn.execute(q, params).fetchall()
            out = [dict(r) for r in rows]
            return {"db_path": target_db, "count": len(out), "rows": out}
        finally:
            conn.close()

    return await asyncio.to_thread(_query)
