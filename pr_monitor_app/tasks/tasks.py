from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from pr_monitor_app.daily_podcast.scheduled import run_daily_podcast_digest
from pr_monitor_app.db import session_scope
from pr_monitor_app.models import DailyPodcastReport
from pr_monitor_app.pipeline.run import run_ingestion, run_processing
from pr_monitor_app.schedule_config import get_beat_schedule_seconds
from pr_monitor_app.state import StateStore
from pr_monitor_app.tasks.celery_app import celery_app

log = structlog.get_logger(__name__)

_WORKER_LOOP: asyncio.AbstractEventLoop | None = None
_WORKER_LOOP_PID: int | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a stable event loop per worker process.

    Celery prefork workers may execute many tasks in the same process.
    Reusing one loop avoids asyncpg/SQLAlchemy pool objects getting bound
    to different loops across successive tasks.
    """
    global _WORKER_LOOP, _WORKER_LOOP_PID

    pid = os.getpid()
    if (
        _WORKER_LOOP is None
        or _WORKER_LOOP_PID != pid
        or _WORKER_LOOP.is_closed()
    ):
        _WORKER_LOOP = asyncio.new_event_loop()
        _WORKER_LOOP_PID = pid
        asyncio.set_event_loop(_WORKER_LOOP)
    return _WORKER_LOOP


def _run(coro):
    """
    Run an async coroutine from a Celery worker process.
    Celery workers are synchronous; use one persistent loop per process.
    """
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


@celery_app.task(name="npe.ingest_sources", bind=True)
def ingest_sources_task(self, force: bool = False) -> dict[str, Any]:
    log.info("task_ingest_sources_start", task_id=self.request.id)

    state = StateStore.from_settings()
    if not force:
        schedule = get_beat_schedule_seconds(state)
        gate_seconds = int(schedule["ingest_seconds"])
        if not state.acquire_lock("npe:schedule:gate:ingest", ttl_seconds=gate_seconds):
            log.debug(
                "task_ingest_sources_skipped_schedule",
                task_id=self.request.id,
                gate_seconds=gate_seconds,
            )
            return {"skipped": True, "reason": "interval_not_elapsed", "interval_seconds": gate_seconds}

    lock_key = "npe:lock:ingest"
    if not state.acquire_lock(lock_key, ttl_seconds=8 * 60):
        log.warning("task_ingest_sources_skipped_lock", task_id=self.request.id)
        return {"skipped": True, "reason": "lock_busy"}

    async def _coro():
        async with session_scope() as session:
            return await run_ingestion(session)

    try:
        res = _run(_coro())
        log.info("task_ingest_sources_done", task_id=self.request.id, result=res)
        return res
    finally:
        state.release_lock(lock_key)


@celery_app.task(name="npe.process_pipeline", bind=True)
def process_pipeline_task(self, force: bool = False) -> dict[str, Any]:
    log.info("task_process_pipeline_start", task_id=self.request.id)

    state = StateStore.from_settings()
    if not force:
        schedule = get_beat_schedule_seconds(state)
        gate_seconds = int(schedule["process_seconds"])
        if not state.acquire_lock("npe:schedule:gate:process", ttl_seconds=gate_seconds):
            log.debug(
                "task_process_pipeline_skipped_schedule",
                task_id=self.request.id,
                gate_seconds=gate_seconds,
            )
            return {"skipped": True, "reason": "interval_not_elapsed", "interval_seconds": gate_seconds}

    lock_key = "npe:lock:process"
    if not state.acquire_lock(lock_key, ttl_seconds=20 * 60):
        log.warning("task_process_pipeline_skipped_lock", task_id=self.request.id)
        return {"skipped": True, "reason": "lock_busy"}

    async def _coro():
        async with session_scope() as session:
            return await run_processing(session)

    try:
        res = _run(_coro())
        log.info("task_process_pipeline_done", task_id=self.request.id, result=res)
        return res
    finally:
        state.release_lock(lock_key)


@celery_app.task(name="npe.daily_podcast", bind=True)
def daily_podcast_task(self) -> dict[str, Any]:
    log.info("task_daily_podcast_start", task_id=self.request.id)

    state = StateStore.from_settings()
    lock_key = "npe:lock:daily_podcast"
    if not state.acquire_lock(lock_key, ttl_seconds=2 * 60 * 60):
        log.warning("task_daily_podcast_skipped_lock", task_id=self.request.id)
        return {"skipped": True, "reason": "lock_busy"}

    try:
        run_result = run_daily_podcast_digest()

        async def _store():
            async with session_scope() as session:
                report_date = run_result.report_date
                report = (
                    await session.execute(
                        select(DailyPodcastReport).where(DailyPodcastReport.report_date == report_date)
                    )
                ).scalars().first()
                if report is None:
                    report = DailyPodcastReport(report_date=report_date, title=run_result.title, report_md=run_result.report_md)
                    session.add(report)
                report.title = run_result.title
                report.report_md = run_result.report_md
                report.source_path = run_result.source_path
                report.source_hash = run_result.source_hash
                report.status = run_result.status
                report.error_message = run_result.error_message
                report.meta_json = dict(run_result.meta or {})
                await session.flush()
                return {
                    "report_id": str(report.id),
                    "status": report.status,
                    "report_date": report.report_date.isoformat(),
                    "title": report.title,
                }

        stored = _run(_store())
        result = {
            "stored": stored,
            "source_path": run_result.source_path,
            "source_hash": run_result.source_hash,
        }
        log.info("task_daily_podcast_done", task_id=self.request.id, result=result)
        return result
    finally:
        state.release_lock(lock_key)
