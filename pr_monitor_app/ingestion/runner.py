from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from npe.config import settings
from npe.ingestion.facebook import FacebookConnector
from npe.ingestion.html_diff import HTMLDiffConnector
from npe.ingestion.linkedin import LinkedInUGCPostsConnector
from npe.ingestion.news_api import NewsAPIConnector
from npe.ingestion.reddit import RedditConnector
from npe.ingestion.rss import RSSConnector
from npe.ingestion.twitter import TwitterConnector
from npe.ingestion.youtube import YouTubeConnector
from npe.models import RawEvent, Source, SourceType
from npe.state import StateStore
from npe.utils.time import utcnow

log = structlog.get_logger(__name__)


async def ingest_sources(session: AsyncSession) -> dict[str, Any]:
    """
    Fetch new items from all active sources and persist as RawEvent.
    Returns counters.
    """
    state = StateStore.from_settings()
    result = {"sources": 0, "fetched_items": 0, "new_raw_events": 0, "duplicates": 0, "errors": 0}

    sources = (await session.execute(select(Source).where(Source.active.is_(True)))).scalars().all()
    result["sources"] = len(sources)

    for src in sources:
        try:
            connector = _build_connector(src, state)
            if connector is None:
                log.debug("ingest_source_skipped", source_id=str(src.id), reason="internal_source")
                continue
            items = await connector.fetch()
            result["fetched_items"] += len(items)

            for item in items:
                payload = {
                    "external_id": item.external_id,
                    "source_type": item.source_type.value,
                    "title": item.title,
                    "url": item.url,
                    "author": item.author,
                    "published_at": item.published_at.isoformat(),
                    "raw_text": item.raw_text,
                    "engagement_stats": item.engagement_stats,
                    "fetched_at": utcnow().isoformat(),
                }
                stmt = (
                    insert(RawEvent)
                    .values(
                        source_id=src.id,
                        external_id=item.external_id,
                        payload=payload,
                    )
                    .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
                    .returning(RawEvent.id)
                )
                inserted = (await session.execute(stmt)).scalar_one_or_none()
                if inserted is None:
                    result["duplicates"] += 1
                else:
                    result["new_raw_events"] += 1

            log.info("ingest_source_ok", source_id=str(src.id), fetched=len(items))
        except Exception as e:
            result["errors"] += 1
            log.exception("ingest_source_failed", source_id=str(src.id), error=str(e))

    return result


def _build_connector(src: Source, state: StateStore):
    cfg = src.config or {}
    if cfg.get("subscription_ingestion"):
        return None
    if src.source_type in (SourceType.news, SourceType.blog) and "rss_url" in cfg:
        return RSSConnector(
            rss_url=str(cfg["rss_url"]),
            source_type=src.source_type,
            default_author=str(cfg.get("default_author") or ""),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
            max_items=int(cfg.get("max_items") or 50),
        )

    if src.source_type == SourceType.blog and "html_url" in cfg:
        return HTMLDiffConnector(
            page_url=str(cfg["html_url"]),
            source_type=SourceType.blog,
            state=state,
            state_key=f"npe:html:last_hash:{src.id}",
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    if src.source_type == SourceType.linkedin:
        access_token = str(cfg.get("access_token") or "")
        author_urn = str(cfg.get("author_urn") or "")
        if not access_token or not author_urn:
            raise ValueError(f"LinkedIn source {src.id} missing required config: access_token, author_urn")

        return LinkedInUGCPostsConnector(
            access_token=access_token,
            author_urn=author_urn,
            count=int(cfg.get("count") or 20),
            sort_by=str(cfg.get("sort_by") or "LAST_MODIFIED"),
            linkedin_version=str(cfg.get("linkedin_version") or "202602"),
            fetch_social_metadata=bool(cfg.get("fetch_social_metadata", True)),
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    if src.source_type == SourceType.twitter:
        bearer_token = str(cfg.get("bearer_token") or settings.twitter_bearer_token or "")
        if not bearer_token:
            raise ValueError(f"Twitter source {src.id} missing required config: bearer_token (or TWITTER_BEARER_TOKEN)")
        return TwitterConnector(
            bearer_token=bearer_token,
            user_id=str(cfg.get("user_id") or "") or None,
            username=str(cfg.get("username") or "").strip() or None,
            query=str(cfg.get("query") or "").strip() or None,
            max_results=int(cfg.get("max_results") or 50),
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    if src.source_type == SourceType.reddit:
        client_id = str(cfg.get("client_id") or settings.reddit_client_id or "")
        client_secret = str(cfg.get("client_secret") or settings.reddit_client_secret or "")
        user_agent = str(cfg.get("user_agent") or "NPE/1.0")
        if not client_id or not client_secret:
            raise ValueError(f"Reddit source {src.id} missing required config: client_id, client_secret (or REDDIT_*)")
        return RedditConnector(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            subreddit=str(cfg.get("subreddit") or "").strip() or None,
            username=str(cfg.get("username") or "").strip() or None,
            sort=str(cfg.get("sort") or "hot"),
            limit=int(cfg.get("limit") or 50),
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
        )

    if src.source_type == SourceType.news_api:
        api_key = str(cfg.get("api_key") or settings.news_api_key or "")
        query = str(cfg.get("query") or "").strip()
        if not api_key or not query:
            raise ValueError(f"News API source {src.id} missing required config: api_key, query (or NEWS_API_KEY)")
        return NewsAPIConnector(
            api_key=api_key,
            query=query,
            from_days=int(cfg.get("from_days") or 7),
            page_size=int(cfg.get("page_size") or 50),
            sort_by=str(cfg.get("sort_by") or "publishedAt"),
            language=str(cfg.get("language") or "en") or None,
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    if src.source_type == SourceType.youtube:
        api_key = str(cfg.get("api_key") or settings.youtube_api_key or "")
        query = str(cfg.get("query") or "").strip() or None
        channel_id = str(cfg.get("channel_id") or "").strip() or None
        if not api_key or (not query and not channel_id):
            raise ValueError(f"YouTube source {src.id} missing required config: api_key, and (query or channel_id) (or YOUTUBE_API_KEY)")
        return YouTubeConnector(
            api_key=api_key,
            query=query,
            channel_id=channel_id,
            max_results=int(cfg.get("max_results") or 50),
            order=str(cfg.get("order") or "date"),
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    if src.source_type == SourceType.facebook:
        access_token = str(cfg.get("access_token") or settings.facebook_access_token or "")
        page_id = str(cfg.get("page_id") or "").strip()
        if not access_token or not page_id:
            raise ValueError(f"Facebook source {src.id} missing required config: access_token, page_id (or FACEBOOK_ACCESS_TOKEN)")
        return FacebookConnector(
            access_token=access_token,
            page_id=page_id,
            limit=int(cfg.get("limit") or 50),
            timeout_seconds=int(cfg.get("timeout_seconds") or 20),
            user_agent=str(cfg.get("user_agent") or "NPE/1.0"),
        )

    raise ValueError(f"Unsupported source config for source_id={src.id}, type={src.source_type}, config_keys={list(cfg.keys())}")
