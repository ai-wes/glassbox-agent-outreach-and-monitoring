from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pr_monitor_app.config import settings

_engine_kwargs = {"pool_pre_ping": True}
if not settings.database_url.startswith("sqlite+aiosqlite"):
    _engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
