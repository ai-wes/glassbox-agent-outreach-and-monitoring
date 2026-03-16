from __future__ import annotations

from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    env: str = Field(default="dev", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Storage
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/pr_monitor.db",
        validation_alias=AliasChoices("PR_DATABASE_URL", "DATABASE_URL"),
    )

    # Redis / Celery
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("PR_REDIS_URL", "REDIS_URL"),
    )
    celery_broker_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("PR_CELERY_BROKER_URL", "CELERY_BROKER_URL"),
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1",
        validation_alias=AliasChoices("PR_CELERY_RESULT_BACKEND", "CELERY_RESULT_BACKEND"),
    )

    # Embeddings
    embedding_model_name: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL_NAME")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")

    # Scoring thresholds
    p0_threshold: float = Field(default=0.82, alias="P0_THRESHOLD")
    p1_threshold: float = Field(default=0.65, alias="P1_THRESHOLD")
    p2_threshold: float = Field(default=0.45, alias="P2_THRESHOLD")

    # Alert throttling
    alert_max_per_client_per_hour: int = Field(default=4, alias="ALERT_MAX_PER_CLIENT_PER_HOUR")
    alert_dedup_window_minutes: int = Field(default=120, alias="ALERT_DEDUP_WINDOW_MINUTES")

    # Signal
    signal_sender_mode: str = Field(default="cli", alias="SIGNAL_SENDER_MODE")  # cli | rest
    signal_sender_account: str | None = Field(default=None, alias="SIGNAL_SENDER_ACCOUNT")
    signal_cli_path: str = Field(default="/usr/bin/signal-cli", alias="SIGNAL_CLI_PATH")
    signal_cli_config_dir: str = Field(default="/var/lib/signal-cli", alias="SIGNAL_CLI_CONFIG_DIR")
    signal_rest_url: str | None = Field(default=None, alias="SIGNAL_REST_URL")
    signal_recipient_default: str | None = Field(default=None, alias="SIGNAL_RECIPIENT_DEFAULT")

    # Telegram
    telegram_api_base: str = Field(default="https://api.telegram.org", alias="TELEGRAM_API_BASE")
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_recipient_default: str | None = Field(default=None, alias="TELEGRAM_RECIPIENT_DEFAULT")

    # WhatsApp (Meta Cloud API)
    whatsapp_api_base: str = Field(default="https://graph.facebook.com", alias="WHATSAPP_API_BASE")
    whatsapp_api_version: str = Field(default="v20.0", alias="WHATSAPP_API_VERSION")
    whatsapp_access_token: str | None = Field(default=None, alias="WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id: str | None = Field(default=None, alias="WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_recipient_default: str | None = Field(default=None, alias="WHATSAPP_RECIPIENT_DEFAULT")

    # Email
    email_provider: str = Field(default="sendgrid", alias="EMAIL_PROVIDER")
    email_api_base: str = Field(default="https://api.sendgrid.com/v3", alias="EMAIL_API_BASE")
    email_api_key: str | None = Field(default=None, alias="EMAIL_API_KEY")
    email_from: str | None = Field(default=None, alias="EMAIL_FROM")
    email_reply_to: str | None = Field(default=None, alias="EMAIL_REPLY_TO")
    email_recipient_default: str | None = Field(default=None, alias="EMAIL_RECIPIENT_DEFAULT")
    email_inbound_secret: str | None = Field(default=None, alias="EMAIL_INBOUND_SECRET")
    email_smtp_host: str | None = Field(default=None, alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=587, alias="EMAIL_SMTP_PORT")
    email_smtp_username: str | None = Field(default=None, alias="EMAIL_SMTP_USERNAME")
    email_smtp_password: str | None = Field(default=None, alias="EMAIL_SMTP_PASSWORD")
    email_smtp_use_tls: bool = Field(default=True, alias="EMAIL_SMTP_USE_TLS")

    # Dashboard link builder
    dashboard_base_url: str = Field(default="http://localhost:8000", alias="DASHBOARD_BASE_URL")

    # Social / API monitoring (optional env fallbacks for Source config)
    rss_feeds: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="RSS_FEEDS")
    rss_source_bootstrap_enabled: bool = Field(default=True, alias="RSS_SOURCE_BOOTSTRAP_ENABLED")
    rss_source_default_max_items: int = Field(default=50, alias="RSS_SOURCE_DEFAULT_MAX_ITEMS")
    twitter_bearer_token: str | None = Field(default=None, alias="TWITTER_BEARER_TOKEN")
    reddit_client_id: str | None = Field(default=None, alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str | None = Field(default=None, alias="REDDIT_CLIENT_SECRET")
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    facebook_access_token: str | None = Field(default=None, alias="FACEBOOK_ACCESS_TOKEN")

    # LLM (optional)
    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    llm_provider: str = Field(default="openai_compat", alias="LLM_PROVIDER")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4.1-mini", alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=45, alias="LLM_TIMEOUT_SECONDS")

    # Clustering / windows
    cluster_window_hours: int = Field(default=24, alias="CLUSTER_WINDOW_HOURS")
    cluster_similarity_threshold: float = Field(default=0.82, alias="CLUSTER_SIMILARITY_THRESHOLD")
    recent_history_days: int = Field(default=30, alias="RECENT_HISTORY_DAYS")

    # Layer 1 subscription ingestion
    db_auto_create: bool = Field(default=False, alias="DB_AUTO_CREATE")
    ingest_enable_scheduler: bool = Field(
        default=False,
        validation_alias=AliasChoices("PR_INGEST_ENABLE_SCHEDULER", "INGEST_ENABLE_SCHEDULER"),
    )
    ingest_tick_seconds: int = Field(default=60, alias="INGEST_TICK_SECONDS")
    ingest_max_subscriptions_per_tick: int = Field(default=25, alias="INGEST_MAX_SUBSCRIPTIONS_PER_TICK")
    ingest_min_text_length: int = Field(default=200, alias="INGEST_MIN_TEXT_LENGTH")
    http_timeout_seconds: float = Field(default=20.0, alias="HTTP_TIMEOUT_SECONDS")
    http_user_agent: str = Field(
        default="NPE/1.0 (+https://example.com)",
        alias="HTTP_USER_AGENT",
    )
    respect_robots_txt: bool = Field(default=True, alias="RESPECT_ROBOTS_TXT")
    max_content_chars: int = Field(default=200_000, alias="MAX_CONTENT_CHARS")
    max_summary_chars: int = Field(default=10_000, alias="MAX_SUMMARY_CHARS")

    # Layer 2 analytics
    analytics_batch_size: int = Field(default=50, alias="ANALYTICS_BATCH_SIZE")
    analytics_tick_seconds: int = Field(default=60, alias="ANALYTICS_TICK_SECONDS")
    analytics_analysis_version: int = Field(default=1, alias="ANALYTICS_ANALYSIS_VERSION")
    analytics_min_event_text_chars: int = Field(default=50, alias="ANALYTICS_MIN_EVENT_TEXT_CHARS")
    analytics_max_event_text_chars: int = Field(default=50_000, alias="ANALYTICS_MAX_EVENT_TEXT_CHARS")
    analytics_max_event_age_days: int = Field(default=30, alias="ANALYTICS_MAX_EVENT_AGE_DAYS")
    analytics_compute_daily_metrics: bool = Field(default=True, alias="ANALYTICS_COMPUTE_DAILY_METRICS")
    analytics_daily_metrics_lookback_days: int = Field(default=14, alias="ANALYTICS_DAILY_METRICS_LOOKBACK_DAYS")
    analytics_keyword_weight: float = Field(default=0.6, alias="ANALYTICS_KEYWORD_WEIGHT")
    analytics_embedding_weight: float = Field(default=0.4, alias="ANALYTICS_EMBEDDING_WEIGHT")
    analytics_recompute_topic_embeddings_hours: int = Field(default=168, alias="ANALYTICS_RECOMPUTE_TOPIC_EMBEDDINGS_HOURS")
    analytics_embedding_provider: str | None = Field(default=None, alias="ANALYTICS_EMBEDDING_PROVIDER")
    analytics_embedding_model: str = Field(default="text-embedding-3-small", alias="ANALYTICS_EMBEDDING_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    # AI PR measurement (optional module set from pr_monitor_app/new_modules.md integration)
    ai_pr_measurement_enabled: bool = Field(default=True, alias="AI_PR_MEASUREMENT_ENABLED")
    ai_pr_measurement_db_path: str = Field(default="ai_pr_measurement.db", alias="AI_PR_MEASUREMENT_DB_PATH")
    ai_pr_measurement_output_dir: str = Field(default="output", alias="AI_PR_MEASUREMENT_OUTPUT_DIR")
    ai_pr_measurement_serp_delay: float = Field(default=2.0, alias="AI_PR_MEASUREMENT_SERP_DELAY")
    ai_pr_measurement_prompt_delay: float = Field(default=1.5, alias="AI_PR_MEASUREMENT_PROMPT_DELAY")
    ai_pr_measurement_trends_timeframe: str = Field(default="today 3-m", alias="AI_PR_MEASUREMENT_TRENDS_TIMEFRAME")
    ai_pr_measurement_ga4_days_back: int = Field(default=30, alias="AI_PR_MEASUREMENT_GA4_DAYS_BACK")

    # Daily podcast digest
    daily_podcast_enabled: bool = Field(default=True, alias="DAILY_PODCAST_ENABLED")
    daily_podcast_hour_utc: int = Field(default=13, alias="DAILY_PODCAST_HOUR_UTC")
    daily_podcast_minute_utc: int = Field(default=0, alias="DAILY_PODCAST_MINUTE_UTC")
    daily_podcast_context_max_chars: int = Field(default=8000, alias="DAILY_PODCAST_CONTEXT_MAX_CHARS")

    # Layer 3 agent / OpenClaw integration
    agent_version: int = Field(default=1, alias="AGENT_VERSION")
    agent_batch_size: int = Field(default=25, alias="AGENT_BATCH_SIZE")
    agent_tick_seconds: int = Field(default=30, alias="AGENT_TICK_SECONDS")
    agent_min_relevance_score: float = Field(default=0.45, alias="AGENT_MIN_RELEVANCE_SCORE")
    agent_max_event_age_days: int = Field(default=14, alias="AGENT_MAX_EVENT_AGE_DAYS")
    agent_candidate_limit: int = Field(default=300, alias="AGENT_CANDIDATE_LIMIT")
    agent_openclaw_mode: bool = Field(default=True, alias="AGENT_OPENCLAW_MODE")

    @field_validator("rss_feeds", mode="before")
    @classmethod
    def parse_rss_feeds(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]


settings = Settings()
