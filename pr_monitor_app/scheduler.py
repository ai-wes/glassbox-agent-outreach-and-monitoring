"""APScheduler for Layer 1 subscription ingestion tick loop."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from pr_monitor_app.db_sync import sync_db_session
from pr_monitor_app.ingestion.layer1_runner import ingest_due_subscriptions
from pr_monitor_app.schedule_config import get_ingest_tick_seconds, set_ingest_tick_seconds
from pr_monitor_app.state import StateStore

log = structlog.get_logger(__name__)

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "ingest_subscriptions"


def start_scheduler() -> None:
    """Start the APScheduler tick loop for subscription ingestion."""
    global _scheduler
    if _scheduler is not None:
        return

    def tick() -> None:
        try:
            with sync_db_session() as session:
                processed = ingest_due_subscriptions(session)
                log.info("scheduler_tick", processed=processed)
        except Exception as e:
            log.exception("scheduler_tick_error", error=str(e))

    state = StateStore.from_settings()
    tick_seconds = get_ingest_tick_seconds(state)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        tick,
        trigger=IntervalTrigger(seconds=tick_seconds),
        id=_JOB_ID,
        replace_existing=True,
    )
    _scheduler.start()
    log.info("scheduler_started", tick_seconds=tick_seconds)


def get_scheduler_status() -> dict[str, object]:
    state = StateStore.from_settings()
    configured_tick = get_ingest_tick_seconds(state)

    running = _scheduler is not None
    active_tick = None
    if _scheduler is not None:
        job = _scheduler.get_job(_JOB_ID)
        if job is not None and getattr(job.trigger, "interval", None) is not None:
            active_tick = int(job.trigger.interval.total_seconds())

    return {
        "running": running,
        "configured_tick_seconds": configured_tick,
        "active_tick_seconds": active_tick,
    }


def update_scheduler_tick_seconds(seconds: int) -> dict[str, object]:
    state = StateStore.from_settings()
    new_tick = set_ingest_tick_seconds(state, seconds)

    if _scheduler is not None:
        _scheduler.reschedule_job(_JOB_ID, trigger=IntervalTrigger(seconds=new_tick))
        log.info("scheduler_tick_updated", tick_seconds=new_tick)

    status = get_scheduler_status()
    status["updated"] = True
    return status
