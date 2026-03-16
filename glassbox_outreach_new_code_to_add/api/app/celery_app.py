"""Celery application factory.

This module initialises a Celery app configured to use Redis as the
broker and results backend.  The Celery instance is shared across all
tasks via import.  Autodiscovery of tasks occurs on import of this
module, ensuring that any modules in the ``app.tasks`` package are
registered.
"""

from __future__ import annotations

from celery import Celery
from kombu.serialization import registry

from .config import settings


# Create the Celery instance
celery_app = Celery(
    "glassbox_outreach",
    broker=settings.redis_broker_url,
    backend=settings.redis_broker_url,
)

# Configure Celery to accept JSON serialization for tasks and results
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Autodiscover tasks from the tasks module
celery_app.autodiscover_tasks(packages=["glassbox_outreach.api.app.tasks"])
