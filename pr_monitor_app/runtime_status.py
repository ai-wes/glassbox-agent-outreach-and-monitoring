from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.models import Alert, Client, DailyPodcastReport, Event, RawEvent, Source, StrategicBrief, Subscription

logger = logging.getLogger(__name__)


def _sqlite_database_path(database_url: str) -> Path | None:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url[len(prefix):])
    if not database_url.startswith("sqlite"):
        return None
    return None


async def collect_pr_runtime_status(session: AsyncSession) -> dict[str, object]:
    counts = {
        "sources": await session.scalar(select(func.count()).select_from(Source)) or 0,
        "raw_events": await session.scalar(select(func.count()).select_from(RawEvent)) or 0,
        "events": await session.scalar(select(func.count()).select_from(Event)) or 0,
        "clients": await session.scalar(select(func.count()).select_from(Client)) or 0,
        "subscriptions": await session.scalar(select(func.count()).select_from(Subscription)) or 0,
        "alerts": await session.scalar(select(func.count()).select_from(Alert)) or 0,
        "briefs": await session.scalar(select(func.count()).select_from(StrategicBrief)) or 0,
    }
    latest_report = (
        (
            await session.execute(
                select(DailyPodcastReport)
                .order_by(DailyPodcastReport.report_date.desc(), DailyPodcastReport.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    db_path = _sqlite_database_path(settings.database_url)
    journal_path = Path(f"{db_path}-journal") if db_path is not None else None

    warnings: list[str] = []
    if counts["sources"] == 0:
        warnings.append("No PR sources are configured.")
    if counts["raw_events"] == 0:
        warnings.append("No raw PR events have been ingested.")
    if counts["clients"] == 0:
        warnings.append("No PR clients are configured; strategic scoring cannot run.")
    if counts["subscriptions"] == 0:
        warnings.append("No PR subscriptions are configured; client-linked ingestion is idle.")
    if counts["clients"] == 0 or counts["subscriptions"] == 0:
        warnings.append("Client events, alerts, and briefs will remain empty until client/topic/subscription records are seeded.")
    if journal_path is not None and journal_path.exists():
        warnings.append(f"SQLite journal file is present at {journal_path}; prior interrupted writes may require repair.")
    if latest_report is not None and latest_report.status != "completed":
        warnings.append("Latest daily podcast report finished in error state.")

    return {
        "database_url": settings.database_url,
        "database_path": str(db_path) if db_path is not None else None,
        "sqlite_journal_present": bool(journal_path and journal_path.exists()),
        "counts": counts,
        "latest_daily_podcast_report": (
            {
                "report_date": latest_report.report_date.isoformat() if latest_report.report_date else None,
                "status": latest_report.status,
                "title": latest_report.title,
                "error_message": latest_report.error_message,
            }
            if latest_report is not None
            else None
        ),
        "warnings": warnings,
    }


async def log_pr_runtime_warnings(session: AsyncSession) -> dict[str, object]:
    status = await collect_pr_runtime_status(session)
    for warning in status["warnings"]:
        logger.warning("pr_monitor_runtime_warning: %s", warning)
    return status
