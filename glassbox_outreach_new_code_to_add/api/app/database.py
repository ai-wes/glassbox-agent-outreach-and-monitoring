"""Database setup and session management.

This module configures the SQLAlchemy engine and provides functions
for acquiring and releasing database sessions.  We use an asynchronous
engine (`create_async_engine`) because FastAPI routes are `async` and
Celery tasks may also run asynchronously when interacting with the
database.  The underlying driver is AsyncPG.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings


# Create a base class for declarative models
Base = declarative_base()

# Create the asynchronous engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Create a configured session factory
async_session_factory = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_session() -> AsyncSession:
    """Provide a transactional scope around a series of operations.

    This dependency yields a new `AsyncSession` for each request and
    ensures that the session is properly closed after the request
    finishes.  It can be used with FastAPI's `Depends`.
    """

    async with async_session_factory() as session:
        yield session