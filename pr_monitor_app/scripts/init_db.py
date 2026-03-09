from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from pr_monitor_app.db import engine
from pr_monitor_app.models import Base
from pr_monitor_app import models_analytics as _models_analytics  # noqa: F401
from pr_monitor_app import models_agent as _models_agent  # noqa: F401

log = structlog.get_logger(__name__)


async def _init(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    log.info("init_db_start")
    asyncio.run(_init(engine))
    log.info("init_db_done")


if __name__ == "__main__":
    main()
