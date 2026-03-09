from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Glassbox Radar"
    env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./radar.db"
    dossiers_dir: Path = Path("./data/dossiers")
    watchlist_path: Path = Path("./watchlists/sample_watchlist.yaml")
    api_token: str | None = None
    auto_create_tables: bool = True
    export_to_sheets: bool = False
    enable_embedded_scheduler: bool = False

    ingest_interval_minutes: int = 360
    preprint_days_lookback: int = 30
    pubmed_days_lookback: int = 120
    clinical_trials_max_rank: int = 10
    request_timeout_seconds: int = 20
    max_connector_concurrency: int = 8
    min_score_for_dossier: float = 70.0
    min_score_for_sheet_export: float = 75.0
    default_owner: str = "glassbox-founder"

    pubmed_tool: str = "glassbox_radar"
    pubmed_email: str = "ops@example.com"
    pubmed_api_key: str | None = None

    google_sheets_service_account_json: str | None = None
    google_sheets_scopes: str = "https://www.googleapis.com/auth/spreadsheets"
    opportunities_sheet_spreadsheet_id: str | None = None
    opportunities_sheet_range_a1: str = "radar_opportunities!A:Z"

    sql_echo: bool = False
    user_agent: str = "GlassboxRadar/0.1"

    model_config = SettingsConfigDict(
        env_prefix="RADAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("dossiers_dir", "watchlist_path", mode="before")
    @classmethod
    def normalize_path(cls, value: Any) -> Path:
        return Path(value)

    @property
    def sheet_export_ready(self) -> bool:
        return bool(self.export_to_sheets and self.opportunities_sheet_spreadsheet_id)

    def sheets_scopes(self) -> list[str]:
        return [scope.strip() for scope in self.google_sheets_scopes.split(",") if scope.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.dossiers_dir.mkdir(parents=True, exist_ok=True)
    return settings
