from __future__ import annotations

import subprocess

import typer
import uvicorn

from pr_monitor_app.config import settings
from pr_monitor_app.db_sync import ENGINE_SYNC
from pr_monitor_app.logging import configure_logging
from pr_monitor_app.models import Base

app = typer.Typer(add_completion=False)


def _cli_level(*, verbose: bool, fallback: str | None = None) -> str:
    if verbose:
        return "DEBUG"
    return str(fallback or settings.log_level).upper()


@app.command()
def create_db(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Create database tables (for initial bring-up)."""
    level = _cli_level(verbose=verbose)
    configure_logging(level)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    Base.metadata.create_all(bind=ENGINE_SYNC)
    typer.echo("Database tables created.")


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the main NPE FastAPI service."""
    level = _cli_level(verbose=verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    typer.echo(
        f"API_START host={host} port={port} reload={str(reload).lower()} "
        f"ingest_scheduler={str(settings.ingest_enable_scheduler).lower()}"
    )
    uvicorn.run(
        "npe.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=level.lower(),
    )


@app.command()
def layer1_api(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the Layer 1+2 API (subscriptions, ingestion, analytics)."""
    level = _cli_level(verbose=verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    typer.echo(
        f"LAYER1_API_START host={host} port={port} reload={str(reload).lower()} "
        f"ingest_scheduler={str(settings.ingest_enable_scheduler).lower()}"
    )
    uvicorn.run(
        "npe.layer1_api:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level=level.lower(),
    )


@app.command()
def analytics_run_once(
    batch_size: int = typer.Option(None, "--batch-size", min=1, max=500),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run Layer 2 analytics on a single batch of pending events."""
    level = _cli_level(verbose=verbose)
    configure_logging(level)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    if settings.db_auto_create:
        Base.metadata.create_all(bind=ENGINE_SYNC)
    from pr_monitor_app.analytics.runner import AnalyticsProcessor

    p = AnalyticsProcessor()
    try:
        res = p.run_once(batch_size=batch_size)
        typer.echo(
            f"processed={res.events_processed} failed={res.events_failed} "
            f"topic_scores={res.topic_scores_written} daily_metrics={res.daily_metrics_written}"
        )
    finally:
        p.close()


@app.command()
def analytics_worker(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Run Layer 2 analytics worker loop (continuous)."""
    level = _cli_level(verbose=verbose)
    configure_logging(level)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    if settings.db_auto_create:
        Base.metadata.create_all(bind=ENGINE_SYNC)
    from pr_monitor_app.analytics.runner import AnalyticsProcessor

    p = AnalyticsProcessor()
    typer.echo(f"ANALYTICS_WORKER_START tick_seconds={settings.analytics_tick_seconds}")
    p.worker_loop()


@app.command()
def celery_worker(
    log_level: str = typer.Option("INFO", "--log-level"),
    with_events: bool = typer.Option(True, "--with-events/--no-events"),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run Celery worker for scheduled ingestion/pipeline tasks."""
    effective_level = _cli_level(verbose=verbose, fallback=log_level)
    typer.echo(f"CLI_LOG_LEVEL level={effective_level}")
    cmd = [
        "celery",
        "-A",
        "pr_monitor_app.tasks.celery_app:celery_app",
        "worker",
        "-l",
        effective_level,
    ]
    if with_events:
        cmd.append("-E")
    if concurrency is not None:
        cmd.extend(["--concurrency", str(concurrency)])

    typer.echo(f"CELERY_WORKER_START cmd={' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as e:
        raise typer.BadParameter("Celery executable not found. Install dependencies first.") from e


@app.command()
def celery_beat(
    log_level: str = typer.Option("INFO", "--log-level"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run Celery beat scheduler for periodic task dispatch."""
    effective_level = _cli_level(verbose=verbose, fallback=log_level)
    typer.echo(f"CLI_LOG_LEVEL level={effective_level}")
    cmd = [
        "celery",
        "-A",
        "pr_monitor_app.tasks.celery_app:celery_app",
        "beat",
        "-l",
        effective_level,
    ]
    typer.echo(f"CELERY_BEAT_START cmd={' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as e:
        raise typer.BadParameter("Celery executable not found. Install dependencies first.") from e


@app.command()
def ai_pr_measurement_run(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Run integrated AI PR measurement modules once."""
    level = _cli_level(verbose=verbose)
    configure_logging(level)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    from pr_monitor_app.analytics.ai_pr_measurement import run_ai_pr_measurement_from_settings

    res = run_ai_pr_measurement_from_settings()
    typer.echo(res)


@app.command()
def ai_pr_report(
    output_dir: str = typer.Option("output", "--output-dir", help="Directory containing run output JSON/CSV files"),
    filename: str = typer.Option("report.html", "--filename", help="Output HTML filename"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Generate an HTML report from a previous AI PR measurement run."""
    level = _cli_level(verbose=verbose)
    configure_logging(level)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    from pr_monitor_app.ai_pr_measurement.report_compiler import compile_report_from_output_dir

    path = compile_report_from_output_dir(output_dir, report_filename=filename)
    typer.echo(f"Report generated: {path}")
