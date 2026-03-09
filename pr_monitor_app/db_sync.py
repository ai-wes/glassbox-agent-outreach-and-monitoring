"""Sync SQLAlchemy engine for Layer 1 ingestion (advisory locks, APScheduler)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from pr_monitor_app.config import settings


def _async_to_sync_url(url: str) -> str:
    """Convert async DB URLs to sync-driver URLs for sync engine."""
    if url.startswith("sqlite+aiosqlite"):
        return re.sub(r"^sqlite\+aiosqlite", "sqlite", url, count=1)
    return re.sub(r"postgresql\+asyncpg", "postgresql+psycopg", url, count=1)


def make_sync_engine():
    sync_url = _async_to_sync_url(settings.database_url)
    return create_engine(
        sync_url,
        pool_pre_ping=True,
        future=True,
    )


ENGINE_SYNC = make_sync_engine()
SessionLocalSync = sessionmaker(
    bind=ENGINE_SYNC, autoflush=False, autocommit=False, expire_on_commit=False
)


@contextmanager
def sync_db_session() -> Iterator[Session]:
    session = SessionLocalSync()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
