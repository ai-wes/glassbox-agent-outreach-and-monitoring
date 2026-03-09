from __future__ import annotations

import logging

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

import app.models  # noqa: F401

logger = logging.getLogger(__name__)


def init_db() -> None:
    if not settings.auto_create_db:
        logger.info("AUTO_CREATE_DB disabled; skipping create_all()")
        return
    logger.info("AUTO_CREATE_DB enabled; creating tables if missing")
    Base.metadata.create_all(bind=engine)
