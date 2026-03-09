from __future__ import annotations

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from outreach_app.gtm_service.core.config import Settings


class JobScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=settings.sequence_timezone)

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def add_recurring_jobs(
        self,
        *,
        run_due: Callable[[], Awaitable[None]],
        ingest_feed: Callable[[str], Awaitable[None]],
    ) -> None:
        self.scheduler.add_job(run_due, 'interval', minutes=10, id='run_due_messages', replace_existing=True)
        for index, feed in enumerate(self.settings.rss_feeds):
            self.scheduler.add_job(ingest_feed, 'interval', hours=1, args=[feed], id=f'rss_feed_{index}', replace_existing=True)
