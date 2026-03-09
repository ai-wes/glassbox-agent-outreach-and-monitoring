from __future__ import annotations

import json
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "glassbox-operator"
    environment: str = Field(default="dev", description="dev|staging|prod")
    log_level: str = Field(default="INFO", description="Python logging level")

    # DB
    database_url: str = Field(default="sqlite:///./data/operator.db", alias="DATABASE_URL")
    auto_create_db: bool = Field(default=False, alias="AUTO_CREATE_DB")
    sqlite_busy_timeout_ms: int = Field(default=30000, alias="SQLITE_BUSY_TIMEOUT_MS", ge=1000)

    # Storage
    artifacts_dir: str = Field(default="./data/artifacts", alias="ARTIFACTS_DIR")

    # Approvals
    operator_secret: str = Field(default="dev-secret-change-me", alias="OPERATOR_SECRET")
    approval_ttl_minutes: int = Field(default=60 * 24)

    # Policy
    tier2_requires_approval: bool = True
    tier3_requires_approval: bool = True
    max_external_actions_per_run: int = Field(default=25)

    # SMTP (optional)
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_pass: str | None = Field(default=None, alias="SMTP_PASS")
    smtp_from: str | None = Field(default=None, alias="SMTP_FROM")

    # Email allowlists
    email_domain_allowlist: str = Field(default="", alias="EMAIL_DOMAIN_ALLOWLIST")
    email_address_allowlist: str = Field(default="", alias="EMAIL_ADDRESS_ALLOWLIST")

    # OpenAI optional
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")

    # Agent API keys
    agent_api_keys: str = Field(default="", alias="AGENT_API_KEYS")

    # Scheduled queue runner
    schedule_enable_runner: bool = Field(default=False, alias="SCHEDULE_ENABLE_RUNNER")
    schedule_poll_seconds: int = Field(default=60, alias="SCHEDULE_POLL_SECONDS", ge=5)
    schedule_batch_size: int = Field(default=10, alias="SCHEDULE_BATCH_SIZE", ge=1)
    schedule_requested_by: str = Field(default="scheduler", alias="SCHEDULE_REQUESTED_BY")

    # RAG
    rag_embedding_dim: int = Field(default=768, alias="RAG_EMBEDDING_DIM")
    rag_chunk_words: int = Field(default=220, alias="RAG_CHUNK_WORDS")
    rag_chunk_overlap_words: int = Field(default=40, alias="RAG_CHUNK_OVERLAP_WORDS")

    # Google Sheets (optional)
    google_sheets_service_account_json: str | None = Field(default=None, alias="GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    google_sheets_scopes: str = Field(
        default="https://www.googleapis.com/auth/spreadsheets",
        alias="GOOGLE_SHEETS_SCOPES",
        description="Comma-separated OAuth scopes",
    )

    def email_domains(self) -> set[str]:
        return {d.strip().lower() for d in self.email_domain_allowlist.split(",") if d.strip()}

    def email_addresses(self) -> set[str]:
        return {e.strip().lower() for e in self.email_address_allowlist.split(",") if e.strip()}

    def agent_keys(self) -> set[str]:
        return {k.strip() for k in self.agent_api_keys.split(",") if k.strip()}

    def sheets_scopes(self) -> list[str]:
        return [s.strip() for s in self.google_sheets_scopes.split(",") if s.strip()]

    def sheets_service_account_info(self) -> dict | None:
        if not self.google_sheets_service_account_json:
            return None
        try:
            return json.loads(self.google_sheets_service_account_json)
        except Exception as e:
            raise ValueError("Invalid GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON; must be valid JSON.") from e


settings = Settings()
