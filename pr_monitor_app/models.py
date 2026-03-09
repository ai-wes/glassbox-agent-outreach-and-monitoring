from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pr_monitor_app.sqltypes import ARRAY, JSONB, UUID


class Base(DeclarativeBase):
    pass


class SourceType(str, enum.Enum):
    linkedin = "linkedin"
    news = "news"
    blog = "blog"
    twitter = "twitter"
    reddit = "reddit"
    news_api = "news_api"
    youtube = "youtube"
    facebook = "facebook"


class SubscriptionType(str, enum.Enum):
    rss = "rss"
    web_page_diff = "web_page_diff"
    web_link_discovery = "web_link_discovery"
    webhook = "webhook"


class EventSourceType(str, enum.Enum):
    rss = "rss"
    web = "web"
    webhook = "webhook"


class IngestionStatus(str, enum.Enum):
    success = "success"
    no_change = "no_change"
    error = "error"


class AlertTier(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class EngagementMode(str, enum.Enum):
    comment = "comment"
    independent_post = "independent_post"
    thread = "thread"
    journalist_outreach = "journalist_outreach"
    stay_silent = "stay_silent"


class NotificationChannel(str, enum.Enum):
    signal = "signal"
    telegram = "telegram"
    whatsapp = "whatsapp"
    email = "email"


class EmailDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)

    messaging_pillars: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    audience_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    brand_voice_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    competitors: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    signal_recipient: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    telegram_recipient: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    whatsapp_recipient: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    email_recipient: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    topics: Mapped[list["TopicLens"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class TopicLens(Base):
    __tablename__ = "topic_lenses"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_topic_client_name"),
        Index("ix_topic_client", "client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    competitor_overrides: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    opportunity_tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Embedding stored as float[] for portability (pgvector recommended in future)
    embedding: Mapped[Optional[list[float]]] = mapped_column(ARRAY(Float), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    client: Mapped["Client"] = relationship(back_populates="topics")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )

    @property
    def query_json(self) -> dict[str, Any]:
        """Analytics-compatible query config built from TopicLens fields."""
        return {
            "description": self.description or "",
            "keywords": list(self.keywords or []),
            "phrases": list(self.keywords or []),
        }


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    topic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_lenses.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[SubscriptionType] = mapped_column(Enum(SubscriptionType), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)

    etag: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    last_modified: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)

    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    fetch_full_content: Mapped[bool] = mapped_column(Boolean, default=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    client: Mapped[Optional["Client"]] = relationship(back_populates="subscriptions")
    topic: Mapped[Optional["TopicLens"]] = relationship(back_populates="subscriptions")

    event_links: Mapped[list["EventSubscription"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_subscriptions_enabled", "enabled"),
        Index("ix_subscriptions_type", "type"),
    )


class IngestionEvent(Base):
    """Layer 1 normalized ingestion event (dedup by canonical_url)."""

    __tablename__ = "ingestion_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    source_type: Mapped[EventSourceType] = mapped_column(Enum(EventSourceType), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    subscriptions: Mapped[list["EventSubscription"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_ingestion_events_dedup_key"),
        Index("ix_ingestion_events_fetched_at", "fetched_at"),
    )


class EventSubscription(Base):
    __tablename__ = "event_subscriptions"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_events.id", ondelete="CASCADE"), primary_key=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), primary_key=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    event: Mapped["IngestionEvent"] = relationship(back_populates="subscriptions")
    subscription: Mapped["Subscription"] = relationship(back_populates="event_links")


class DiscoveredLink(Base):
    __tablename__ = "discovered_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("subscription_id", "url_hash", name="uq_discovered_links_sub_url_hash"),
        Index("ix_discovered_links_sub", "subscription_id"),
    )


class IngestionAttempt(Base):
    __tablename__ = "ingestion_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    status: Mapped[IngestionStatus] = mapped_column(Enum(IngestionStatus), nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    events_created: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subscription_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subscription_url: Mapped[str] = mapped_column(Text, nullable=False)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_source_type_active", "source_type", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # 0..1 authority score configured by operator
    authority_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    # Connector-specific configuration, e.g. {"rss_url": "..."} or {"html_url": "..."} or LinkedIn settings
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),
        Index("ix_raw_fetched_at", "fetched_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_event_published_at", "published_at"),
        Index("ix_event_source_type", "source_type"),
        Index("ix_event_url", "url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    raw_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_events.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)

    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    author: Mapped[str] = mapped_column(String(250), default="", nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    engagement_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    detected_entities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    embedding: Mapped[Optional[list[float]]] = mapped_column(ARRAY(Float), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class EventCluster(Base):
    __tablename__ = "event_clusters"
    __table_args__ = (
        Index("ix_cluster_window", "window_start", "window_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # centroid embedding used for dedupe within window
    centroid_embedding: Mapped[Optional[list[float]]] = mapped_column(ARRAY(Float), nullable=True)

    representative_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))
    cluster_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class EventClusterMap(Base):
    __tablename__ = "event_cluster_map"
    __table_args__ = (
        UniqueConstraint("event_id", "cluster_id", name="uq_event_cluster"),
        Index("ix_event_cluster_event", "event_id"),
        Index("ix_event_cluster_cluster", "cluster_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("event_clusters.id", ondelete="CASCADE"))


class ClientEvent(Base):
    __tablename__ = "client_events"
    __table_args__ = (
        UniqueConstraint("client_id", "event_id", "topic_id", name="uq_client_event_topic"),
        Index("ix_client_events_client", "client_id"),
        Index("ix_client_events_tier", "tier"),
        CheckConstraint("composite_score >= 0.0 AND composite_score <= 1.0", name="ck_composite_0_1"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topic_lenses.id", ondelete="CASCADE"))

    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[AlertTier] = mapped_column(Enum(AlertTier), nullable=False)

    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class StrategicBrief(Base):
    __tablename__ = "strategic_briefs"
    __table_args__ = (
        UniqueConstraint("client_event_id", name="uq_brief_client_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_events.id", ondelete="CASCADE"))

    event_summary: Mapped[str] = mapped_column(Text, nullable=False)
    strategic_analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    engagement_mode: Mapped[EngagementMode] = mapped_column(Enum(EngagementMode), nullable=False)

    confidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class CreativeDraftSet(Base):
    __tablename__ = "creative_draft_sets"
    __table_args__ = (
        UniqueConstraint("brief_id", name="uq_drafts_brief"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategic_briefs.id", ondelete="CASCADE"))

    linkedin_comments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    independent_posts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    guardrail_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_sent_at", "sent_at"),
        Index("ix_alert_tier", "tier"),
        Index("ix_alert_channel", "channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_events.id", ondelete="CASCADE"))

    tier: Mapped[AlertTier] = mapped_column(Enum(AlertTier), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)

    signal_recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel, name="notificationchannel"), nullable=False, default=NotificationChannel.signal)
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class EngagementFeedback(Base):
    """
    Feedback loop (future phase):
    record what the PR team actually engaged with and the outcome signal.
    """
    __tablename__ = "engagement_feedback"
    __table_args__ = (
        Index("ix_feedback_client", "client_id"),
        Index("ix_feedback_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))
    client_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_events.id", ondelete="SET NULL"), nullable=True)

    action_taken: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "commented", "posted", "ignored"
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class BrandConfigDB(Base):
    """Stored brand config for AI PR measurement. Agent can CRUD via API."""

    __tablename__ = "brand_configs"
    __table_args__ = (
        UniqueConstraint("brand_name", name="uq_brand_configs_name"),
        Index("ix_brand_configs_name", "brand_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_domains: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    brand_aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    key_claims: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    competitors: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    executive_names: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    official_website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    social_profiles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EmailMessage(Base):
    """Inbound/outbound email records used by email channel + agent actions."""

    __tablename__ = "email_messages"
    __table_args__ = (
        Index("ix_email_messages_client", "client_id"),
        Index("ix_email_messages_direction", "direction"),
        Index("ix_email_messages_received", "received_at"),
        Index("ix_email_messages_thread", "thread_id"),
        UniqueConstraint("provider", "message_id", name="uq_email_provider_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[EmailDirection] = mapped_column(Enum(EmailDirection, name="emaildirection"), nullable=False)

    provider: Mapped[str] = mapped_column(String(32), default="sendgrid", nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    in_reply_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(998), nullable=True)
    text_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class DailyPodcastReport(Base):
    """Persisted daily digest generated by the podcast pipeline."""

    __tablename__ = "daily_podcast_reports"
    __table_args__ = (
        Index("ix_daily_podcast_reports_created", "created_at"),
        Index("ix_daily_podcast_reports_report_date", "report_date"),
        UniqueConstraint("report_date", name="uq_daily_podcast_reports_report_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
