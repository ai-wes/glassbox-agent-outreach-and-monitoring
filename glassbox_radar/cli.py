from __future__ import annotations

import argparse
import asyncio
import json

from glassbox_radar.core.config import get_settings
from glassbox_radar.core.logging import configure_logging
from glassbox_radar.db import SessionLocal, init_db
from glassbox_radar.models import Company, Contact, Opportunity, Program
from glassbox_radar.services.pipeline import RadarPipeline
from glassbox_radar.services.watchlist_sync import sync_watchlist
from glassbox_radar.watchlist import load_watchlist
from sqlalchemy import select


async def bootstrap_db() -> None:
    await init_db()
    print("Database initialized.")


async def run_watchlist_sync() -> None:
    settings = get_settings()
    companies = load_watchlist(settings.watchlist_path)
    async with SessionLocal() as session:
        summary = await sync_watchlist(session, companies)
    print(json.dumps(summary, indent=2))


async def run_pipeline_once() -> None:
    pipeline = RadarPipeline(SessionLocal)
    summary = await pipeline.run()
    print(json.dumps(summary, indent=2, default=str))


async def generate_dossiers(min_score: float | None) -> None:
    settings = get_settings()
    threshold = min_score if min_score is not None else settings.min_score_for_dossier
    async with SessionLocal() as session:
        result = await session.execute(select(Opportunity).where(Opportunity.radar_score >= threshold))
        opportunities = result.scalars().all()
    print(f"{len(opportunities)} opportunities already meet dossier threshold {threshold}.")


async def export_sheets(min_score: float | None) -> None:
    settings = get_settings()
    settings.export_to_sheets = True
    if min_score is not None:
        settings.min_score_for_sheet_export = min_score
    pipeline = RadarPipeline(SessionLocal)
    summary = await pipeline.run()
    print(json.dumps(summary, indent=2, default=str))


async def print_stats() -> None:
    async with SessionLocal() as session:
        company_count = len((await session.execute(select(Company))).scalars().all())
        program_count = len((await session.execute(select(Program))).scalars().all())
        contact_count = len((await session.execute(select(Contact))).scalars().all())
        opportunity_count = len((await session.execute(select(Opportunity))).scalars().all())
    print(
        json.dumps(
            {
                "companies": company_count,
                "programs": program_count,
                "contacts": contact_count,
                "opportunities": opportunity_count,
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Glassbox Radar CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bootstrap-db")
    subparsers.add_parser("sync-watchlist")
    subparsers.add_parser("run-once")
    dossiers_parser = subparsers.add_parser("generate-dossiers")
    dossiers_parser.add_argument("--min-score", type=float, default=None)
    sheets_parser = subparsers.add_parser("export-sheets")
    sheets_parser.add_argument("--min-score", type=float, default=None)
    subparsers.add_parser("stats")
    return parser


async def dispatch(args: argparse.Namespace) -> None:
    if args.command == "bootstrap-db":
        await bootstrap_db()
    elif args.command == "sync-watchlist":
        await run_watchlist_sync()
    elif args.command == "run-once":
        await run_pipeline_once()
    elif args.command == "generate-dossiers":
        await generate_dossiers(args.min_score)
    elif args.command == "export-sheets":
        await export_sheets(args.min_score)
    elif args.command == "stats":
        await print_stats()
    else:
        raise ValueError(f"Unknown command {args.command}")


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(dispatch(args))


if __name__ == "__main__":
    main()
