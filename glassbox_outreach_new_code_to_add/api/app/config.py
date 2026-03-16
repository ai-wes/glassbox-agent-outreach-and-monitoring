"""Configuration management using pydantic settings.

This module centralizes the environment variables and defaults used across
the application.  By using `BaseSettings` all values are automatically
validated and parsed.  The resulting `settings` object can be imported
throughout the codebase for a single source of truth.
"""

from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        database_url: SQLAlchemy URL for connecting to the Postgres database.
        redis_broker_url: URL for the Redis broker used by Celery.
        google_sheets_spreadsheet_id: ID of the Google Sheet used for syncing.
        google_service_account_file: Path to the JSON credentials for the
            Google service account.
    """

    database_url: str = Field(..., env="DATABASE_URL")
    redis_broker_url: str = Field(..., env="REDIS_BROKER_URL")
    google_sheets_spreadsheet_id: str = Field(..., env="GOOGLE_SHEETS_SPREADSHEET_ID")
    google_service_account_file: str = Field(..., env="GOOGLE_SERVICE_ACCOUNT_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached instance of the application settings.

    Using an LRU cache ensures that settings are only parsed once,
    regardless of how many times `get_settings` is called.
    """

    return Settings()  # type: ignore[arg-type]


settings = get_settings()
