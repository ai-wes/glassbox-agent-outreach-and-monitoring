from __future__ import annotations

from typing import AsyncIterator, Iterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from pr_monitor_app.db import SessionLocal
from pr_monitor_app.db_sync import SessionLocalSync


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_sync_session() -> Iterator[Session]:
    """Sync session for Layer 1 subscription ingestion (advisory locks)."""
    session = SessionLocalSync()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
