from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from pr_monitor_app.config import settings

celery_app = Celery(
    "npe",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_redirect_stdouts=False,
)


@setup_logging.connect
def _setup_celery_logging(**kwargs):
    """Prevent Celery from configuring its own root-logger handlers.

    Instead we call our own configure_logging so that structlog's
    JSONRenderer is active and exactly one StreamHandler exists.
    """
    from pr_monitor_app.logging import configure_logging  # noqa: delayed import

    configure_logging(settings.log_level)

# Explicit task module import (works in local + container runtime)
celery_app.conf.imports = ("pr_monitor_app.tasks.tasks",)


_beat_schedule = {
    # Beat wakes up every minute; effective cadence is dynamically enforced
    # by worker-side schedule gates (see /admin/beat-schedule).
    "ingest-every-1-min": {
        "task": "npe.ingest_sources",
        "schedule": 60.0,
    },
    "process-every-1-min": {
        "task": "npe.process_pipeline",
        "schedule": 60.0,
    },
}

if settings.daily_podcast_enabled:
    _beat_schedule["daily-podcast-digest"] = {
        "task": "npe.daily_podcast",
        "schedule": crontab(
            hour=max(0, min(23, int(settings.daily_podcast_hour_utc))),
            minute=max(0, min(59, int(settings.daily_podcast_minute_utc))),
        ),
    }

celery_app.conf.beat_schedule = _beat_schedule
