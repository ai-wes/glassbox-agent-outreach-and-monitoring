from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from glassbox_radar.core.config import get_settings
from glassbox_radar.models import Company, Opportunity, PipelineRun, Program, Signal
from glassbox_radar.watchlist import load_watchlist

logger = logging.getLogger(__name__)


async def collect_radar_runtime_status(session: AsyncSession) -> dict[str, object]:
    settings = get_settings()
    counts = {
        "companies": await session.scalar(select(func.count()).select_from(Company)) or 0,
        "programs": await session.scalar(select(func.count()).select_from(Program)) or 0,
        "opportunities": await session.scalar(select(func.count()).select_from(Opportunity)) or 0,
        "signals": await session.scalar(select(func.count()).select_from(Signal)) or 0,
        "pipeline_runs": await session.scalar(select(func.count()).select_from(PipelineRun)) or 0,
    }

    watchlist_entries = []
    if settings.watchlist_path.exists():
        watchlist_entries = load_watchlist(settings.watchlist_path)

    warnings: list[str] = []
    if not settings.watchlist_path.exists():
        warnings.append(f"Radar watchlist file is missing: {settings.watchlist_path}")
    elif not watchlist_entries:
        warnings.append(f"Radar watchlist is empty: {settings.watchlist_path}")
    if counts["companies"] == 0 or counts["programs"] == 0:
        warnings.append("Radar company/program inventory is empty; opportunity scoring cannot produce useful output.")
    if counts["signals"] == 0:
        warnings.append("Radar has not stored any signals yet.")
    if counts["pipeline_runs"] == 0:
        warnings.append("Radar pipeline has not completed a run yet.")

    return {
        "database_url": settings.database_url,
        "watchlist_path": str(settings.watchlist_path),
        "watchlist_exists": settings.watchlist_path.exists(),
        "watchlist_companies": len(watchlist_entries),
        "sheet_export_ready": bool(settings.sheet_export_ready),
        "counts": counts,
        "warnings": warnings,
    }


async def log_radar_runtime_warnings(session: AsyncSession) -> dict[str, object]:
    status = await collect_radar_runtime_status(session)
    for warning in status["warnings"]:
        logger.warning("radar_runtime_warning: %s", warning)
    return status
