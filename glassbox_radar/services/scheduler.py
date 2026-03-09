from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from glassbox_radar.core.config import get_settings
from glassbox_radar.services.pipeline import RadarPipeline

logger = logging.getLogger(__name__)


class EmbeddedScheduler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.settings = get_settings()
        self.session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self.settings.enable_embedded_scheduler:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="glassbox-radar-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _run_loop(self) -> None:
        pipeline = RadarPipeline(self.session_factory)
        interval_seconds = max(60, self.settings.ingest_interval_minutes * 60)
        while not self._stop.is_set():
            try:
                await pipeline.run()
            except Exception:
                logger.exception("Scheduled pipeline run failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue
