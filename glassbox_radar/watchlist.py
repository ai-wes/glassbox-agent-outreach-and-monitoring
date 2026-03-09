from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dateutil import parser as date_parser


@dataclass(slots=True)
class WatchlistContact:
    name: str
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    role: str | None = None
    warm_intro_strength: float | None = None
    is_primary: bool = False


@dataclass(slots=True)
class WatchlistProgram:
    asset_name: str | None = None
    target: str | None = None
    mechanism: str | None = None
    modality: str | None = None
    indication: str | None = None
    stage: str | None = None
    key_terms: list[str] = field(default_factory=list)
    lead_program_flag: bool = False


@dataclass(slots=True)
class WatchlistCompany:
    name: str
    domain: str | None = None
    aliases: list[str] = field(default_factory=list)
    hq: str | None = None
    stage: str | None = None
    last_raise_date: date | None = None
    last_raise_amount: float | None = None
    runway_months: int | None = None
    lead_investors: list[str] = field(default_factory=list)
    board_members: list[str] = field(default_factory=list)
    therapeutic_areas: list[str] = field(default_factory=list)
    warm_intro_paths: list[str] = field(default_factory=list)
    rss_feeds: list[str] = field(default_factory=list)
    contacts: list[WatchlistContact] = field(default_factory=list)
    programs: list[WatchlistProgram] = field(default_factory=list)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date_parser.parse(str(value)).date()


def load_watchlist(path: Path) -> list[WatchlistCompany]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    companies_data = raw.get("companies", [])
    companies: list[WatchlistCompany] = []

    for company_data in companies_data:
        contacts = [
            WatchlistContact(
                name=contact["name"],
                title=contact.get("title"),
                email=contact.get("email"),
                phone=contact.get("phone"),
                linkedin_url=contact.get("linkedin_url"),
                role=contact.get("role"),
                warm_intro_strength=contact.get("warm_intro_strength"),
                is_primary=bool(contact.get("is_primary", False)),
            )
            for contact in company_data.get("contacts", [])
        ]

        programs = [
            WatchlistProgram(
                asset_name=program.get("asset_name"),
                target=program.get("target"),
                mechanism=program.get("mechanism"),
                modality=program.get("modality"),
                indication=program.get("indication"),
                stage=program.get("stage"),
                key_terms=list(program.get("key_terms", [])),
                lead_program_flag=bool(program.get("lead_program_flag", False)),
            )
            for program in company_data.get("programs", [])
        ]

        companies.append(
            WatchlistCompany(
                name=company_data["name"],
                domain=company_data.get("domain"),
                aliases=list(company_data.get("aliases", [])),
                hq=company_data.get("hq"),
                stage=company_data.get("stage"),
                last_raise_date=_parse_date(company_data.get("last_raise_date")),
                last_raise_amount=company_data.get("last_raise_amount"),
                runway_months=company_data.get("runway_months"),
                lead_investors=list(company_data.get("lead_investors", [])),
                board_members=list(company_data.get("board_members", [])),
                therapeutic_areas=list(company_data.get("therapeutic_areas", [])),
                warm_intro_paths=list(company_data.get("warm_intro_paths", [])),
                rss_feeds=list(company_data.get("rss_feeds", [])),
                contacts=contacts,
                programs=programs,
            )
        )
    return companies
