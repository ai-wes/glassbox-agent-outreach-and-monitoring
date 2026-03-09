from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class DailyPodcastRunResult:
    report_date: date
    status: str
    title: str
    report_md: str
    source_path: str | None = None
    source_hash: str | None = None
    meta: dict[str, Any] | None = None
    error_message: str | None = None


def _candidate_digest_dirs() -> list[Path]:
    return [
        Path("digests"),
        Path("npe") / "daily_podcast" / "digests",
    ]


def _find_digest_for_date(report_date: date) -> Path | None:
    filename = f"digest-{report_date:%Y%m%d}.md"
    for base in _candidate_digest_dirs():
        path = base / filename
        if path.exists():
            return path
    return None


def _build_report_title(now: datetime) -> str:
    return f"Daily Podcast Briefing - {now:%Y-%m-%d}"


def run_daily_podcast_digest() -> DailyPodcastRunResult:
    """Run the existing daily_podcast module and collect the latest digest markdown."""
    now = datetime.now(timezone.utc)
    report_date = now.date()
    title = _build_report_title(now)

    try:
        module = importlib.import_module("npe.daily_podcast.daily_pods")
        module.main()
    except Exception as exc:
        msg = f"daily_podcast execution failed: {exc}"
        log.exception("daily_podcast_run_failed", error=str(exc))
        return DailyPodcastRunResult(
            report_date=report_date,
            status="error",
            title=title,
            report_md=f"# {title}\n\nDaily podcast run failed.\n\nError: {exc}",
            error_message=msg[:2000],
            meta={"runner": "npe.daily_podcast.daily_pods.main"},
        )

    digest_path = _find_digest_for_date(report_date)
    if digest_path is None:
        msg = f"daily_podcast completed but no digest markdown file was found for {report_date.isoformat()}"
        log.warning("daily_podcast_digest_not_found", report_date=report_date.isoformat())
        return DailyPodcastRunResult(
            report_date=report_date,
            status="error",
            title=title,
            report_md=f"# {title}\n\nDaily podcast run completed but no digest file was found for {report_date.isoformat()}.",
            error_message=msg,
            meta={"runner": "npe.daily_podcast.daily_pods.main"},
        )

    report_md = digest_path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(report_md.encode("utf-8")).hexdigest()
    return DailyPodcastRunResult(
        report_date=report_date,
        status="completed",
        title=title,
        report_md=report_md,
        source_path=str(digest_path),
        source_hash=source_hash,
        meta={"runner": "npe.daily_podcast.daily_pods.main"},
    )
