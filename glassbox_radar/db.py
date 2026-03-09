from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from glassbox_radar.core.config import get_settings
from glassbox_radar.models import Base


settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def init_db() -> None:
    if not settings.auto_create_tables:
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
