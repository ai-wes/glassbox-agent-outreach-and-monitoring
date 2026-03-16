from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import or_, select

from app.core.config import settings
from app.db.session import db_session
from app.models.task import Task
from app.orchestrator.planner import Planner
from app.orchestrator.service import Orchestrator
from app.tools.factory import build_registry

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_scheduler_paused = False
_state_lock = Lock()
_JOB_ID = "outreach_run_queued_tasks"

_tools = build_registry()
_planner = Planner(_tools)
_orchestrator = Orchestrator(_tools, _planner)


def run_scheduled_tasks_once() -> dict[str, int]:
    with _state_lock:
        paused = _scheduler_paused
    if paused:
        summary = {
            "selected": 0,
            "processed": 0,
            "challenges": 0,
            "failures": 0,
            "skipped": 1,
        }
        logger.info("outreach_scheduler_tick_skipped", extra={"reason": "paused", **summary})
        return summary

    now = datetime.utcnow()
    processed = 0
    challenges = 0
    failures = 0
    task_ids: list[str] = []

    with db_session() as db:
        rows = (
            db.execute(
                select(Task.id)
                .where(Task.status == "queued")
                .where(or_(Task.due_at.is_(None), Task.due_at <= now))
                .order_by(Task.priority.asc(), Task.created_at.asc())
                .limit(max(1, settings.schedule_batch_size))
            )
            .scalars()
            .all()
        )
        task_ids = list(rows)

    for task_id in task_ids:
        try:
            with db_session() as db:
                task = db.get(Task, task_id)
                if task is None:
                    continue
                if task.status != "queued":
                    continue
                if task.due_at is not None and task.due_at > now:
                    continue

                run, challenge = _orchestrator.start_run(
                    db=db,
                    task=task,
                    requested_by=settings.schedule_requested_by,
                    force_agent=None,
                    dry_run=False,
                )
                processed += 1
                if challenge is not None:
                    challenges += 1
                logger.info(
                    "outreach_scheduler_task_run",
                    extra={
                        "task_id": task.id,
                        "run_id": run.id,
                        "run_status": run.status,
                        "requires_approval": challenge is not None,
                    },
                )
        except Exception:
            failures += 1
            with db_session() as db:
                task = db.get(Task, task_id)
                if task is not None:
                    task.status = "needs_attention"
                    task.updated_at = datetime.utcnow()
                    db.add(task)
            logger.exception(
                "outreach_scheduler_task_error",
                extra={"task_id": task_id},
            )

    summary = {
        "selected": len(task_ids),
        "processed": processed,
        "challenges": challenges,
        "failures": failures,
    }
    logger.info("outreach_scheduler_tick", extra=summary)
    return summary


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    poll_seconds = max(5, int(settings.schedule_poll_seconds))
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_scheduled_tasks_once,
        trigger=IntervalTrigger(seconds=poll_seconds),
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "outreach_scheduler_started",
        extra={
            "poll_seconds": poll_seconds,
            "batch_size": int(settings.schedule_batch_size),
        },
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("outreach_scheduler_stopped")


def set_scheduler_paused(paused: bool) -> dict[str, object]:
    global _scheduler_paused
    with _state_lock:
        _scheduler_paused = bool(paused)
    logger.info("outreach_scheduler_pause_updated", extra={"paused": _scheduler_paused})
    return get_scheduler_status()


def get_scheduler_status() -> dict[str, object]:
    running = _scheduler is not None
    next_run_at = None
    if _scheduler is not None:
        job = _scheduler.get_job(_JOB_ID)
        if job is not None and job.next_run_time is not None:
            next_run_at = job.next_run_time.isoformat()

    with _state_lock:
        paused = _scheduler_paused

    return {
        "enabled": bool(settings.schedule_enable_runner),
        "running": running,
        "paused": paused,
        "job_id": _JOB_ID,
        "poll_seconds": int(settings.schedule_poll_seconds),
        "batch_size": int(settings.schedule_batch_size),
        "requested_by": settings.schedule_requested_by,
        "next_run_at": next_run_at,
    }
