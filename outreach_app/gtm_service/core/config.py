from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Glassbox GTM Automation", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8080, alias="API_PORT")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./glassbox_gtm.db",
        validation_alias=AliasChoices("GTM_DATABASE_URL", "DATABASE_URL"),
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")

    llm_enabled: bool = Field(default=True, alias="LLM_ENABLED")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=45, alias="LLM_TIMEOUT_SECONDS")

    allow_auto_send: bool = Field(default=True, alias="ALLOW_AUTO_SEND")
    only_queue_ab_grades: bool = Field(default=True, alias="ONLY_QUEUE_AB_GRADES")
    sequence_timezone: str = Field(default="America/Los_Angeles", alias="SEQUENCE_TIMEZONE")

    smtp_from_name: str = Field(default="Glassbox Bio", alias="SMTP_FROM_NAME")
    smtp_from_email: str = Field(
        default="founder@example.com",
        validation_alias=AliasChoices("SMTP_FROM_EMAIL", "GMAIL_ADDRESS"),
    )
    smtp_reply_to: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_REPLY_TO", "GMAIL_ADDRESS"),
    )
    smtp_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_HOST", "SERVER_ADDRESS"),
    )
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_USERNAME", "GMAIL_ADDRESS"),
    )
    smtp_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_PASSWORD", "GMAIL_APP_PASSWORD"),
    )
    outbox_dir: str = Field(default="./outbox", alias="OUTBOX_DIR")

    google_sheets_service_account_json: str | None = Field(default=None, alias="GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    google_sheets_scopes: str = Field(
        default="https://www.googleapis.com/auth/spreadsheets",
        alias="GOOGLE_SHEETS_SCOPES",
    )
    crm_sheet_spreadsheet_id: str | None = Field(default=None, alias="GTM_CRM_SPREADSHEET_ID")
    crm_sheet_range_a1: str = Field(default="Leads!A:Z", alias="GTM_CRM_RANGE_A1")
    crm_sheet_replies_range_a1: str = Field(default="crm_replies!A:Z", alias="GTM_CRM_REPLIES_RANGE_A1")
    crm_sheet_delivery_events_range_a1: str = Field(
        default="crm_delivery_events!A:Z",
        alias="GTM_CRM_DELIVERY_EVENTS_RANGE_A1",
    )
    crm_sheet_conversion_events_range_a1: str = Field(
        default="crm_conversions!A:Z",
        alias="GTM_CRM_CONVERSION_EVENTS_RANGE_A1",
    )
    crm_sheet_metrics_range_a1: str = Field(default="crm_metrics!A:C", alias="GTM_CRM_METRICS_RANGE_A1")
    crm_sheet_accounts_range_a1: str = Field(default="Accounts!A:P", alias="GTM_CRM_ACCOUNTS_RANGE_A1")
    crm_sheet_contacts_range_a1: str = Field(default="Contacts!A:K", alias="GTM_CRM_CONTACTS_RANGE_A1")
    crm_sheet_activities_range_a1: str = Field(default="Activities!A:M", alias="GTM_CRM_ACTIVITIES_RANGE_A1")
    crm_sheet_deals_range_a1: str = Field(default="Deals!A:U", alias="GTM_CRM_DEALS_RANGE_A1")
    linkedin_webhook_url: str | None = Field(default=None, alias="LINKEDIN_WEBHOOK_URL")
    linkedin_webhook_secret: str | None = Field(default=None, alias="LINKEDIN_WEBHOOK_SECRET")

    default_rss_lookback_hours: int = Field(default=168, alias="DEFAULT_RSS_LOOKBACK_HOURS")
    http_timeout_seconds: int = Field(default=20, alias="HTTP_TIMEOUT_SECONDS")
    max_scrape_text_chars: int = Field(default=12000, alias="MAX_SCRAPE_TEXT_CHARS")
    max_signal_snippets: int = Field(default=16, alias="MAX_SIGNAL_SNIPPETS")

    grade_a_min: int = Field(default=75, alias="GRADE_A_MIN")
    grade_b_min: int = Field(default=60, alias="GRADE_B_MIN")
    grade_c_min: int = Field(default=40, alias="GRADE_C_MIN")
    qc_target_per_day: int = Field(default=4, alias="QC_TARGET_PER_DAY")

    approved_proof_snippets: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="APPROVED_PROOF_SNIPPETS",
    )
    private_offer_catalog: dict[str, Any] = Field(default_factory=dict, alias="PRIVATE_OFFER_CATALOG_JSON")
    rss_feeds: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="RSS_FEEDS")

    @field_validator("approved_proof_snippets", mode="before")
    @classmethod
    def parse_proof_snippets(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split("|") if item.strip()]

    @field_validator("private_offer_catalog", mode="before")
    @classmethod
    def parse_offer_catalog(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return json.loads(str(value))

    @field_validator("rss_feeds", mode="before")
    @classmethod
    def parse_rss_feeds(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @field_validator(
        "smtp_from_email",
        "smtp_reply_to",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        mode="before",
    )
    @classmethod
    def strip_quoted_strings(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:-1].strip()
        return cleaned

    @property
    def outbox_path(self) -> Path:
        return Path(self.outbox_dir).resolve()

    @property
    def smtp_ready(self) -> bool:
        return all([self.smtp_host, self.smtp_username, self.smtp_password, self.smtp_from_email])

    @property
    def llm_ready(self) -> bool:
        return self.llm_enabled and bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def crm_sync_ready(self) -> bool:
        return bool(self.crm_sheet_spreadsheet_id)

    def sheets_scopes(self) -> list[str]:
        return [scope.strip() for scope in self.google_sheets_scopes.split(",") if scope.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
