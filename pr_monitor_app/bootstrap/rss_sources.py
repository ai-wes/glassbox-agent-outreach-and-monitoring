from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.models import Source, SourceType

MANAGED_BY = "env_rss_feeds"

_FEED_ALIASES: dict[str, str] = {
    "https://rss.art19.com/hard-fork": "https://feeds.simplecast.com/l2i9YnTd",
    "https://rss.art19.com/all-in": "https://rss.libsyn.com/shows/254861/destinations/1928300.xml",
    "https://latent.space/rss.xml": "https://www.latent.space/feed",
}


@dataclass(frozen=True)
class FeedMetadata:
    name: str
    source_type: SourceType
    authority_score: float
    category: str


_KNOWN_FEEDS: dict[str, FeedMetadata] = {
    "https://feeds.megaphone.fm/pivot": FeedMetadata("Pivot", SourceType.blog, 0.6, "podcast"),
    "https://feeds.simplecast.com/l2i9YnTd": FeedMetadata("Hard Fork", SourceType.blog, 0.65, "podcast"),
    "https://feeds.megaphone.fm/vergecast": FeedMetadata("The Vergecast", SourceType.blog, 0.6, "podcast"),
    "https://rss.libsyn.com/shows/254861/destinations/1928300.xml": FeedMetadata(
        "All-In Podcast", SourceType.blog, 0.55, "podcast"
    ),
    "https://feeds.soundcloud.com/users/soundcloud:users:232716163/sounds.rss": FeedMetadata(
        "Eye on AI", SourceType.blog, 0.6, "podcast"
    ),
    "https://lexfridman.com/feed/podcast/": FeedMetadata(
        "Lex Fridman Podcast", SourceType.blog, 0.65, "podcast"
    ),
    "https://www.latent.space/feed": FeedMetadata("Latent Space", SourceType.blog, 0.72, "newsletter"),
    "https://changelog.com/practicalai/feed": FeedMetadata("Practical AI", SourceType.blog, 0.67, "podcast"),
    "https://feeds.acast.com/public/shows/eye-on-ai": FeedMetadata(
        "Eye on AI", SourceType.blog, 0.6, "podcast"
    ),
    "https://feeds.acast.com/public/shows/deepmind-the-podcast": FeedMetadata(
        "DeepMind: The Podcast", SourceType.blog, 0.7, "podcast"
    ),
    "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml": FeedMetadata(
        "Futurehouse Newsletter", SourceType.blog, 0.7, "newsletter"
    ),
    "https://bensbites.beehiiv.com/feed": FeedMetadata("Ben's Bites", SourceType.blog, 0.76, "newsletter"),
    "https://blog.bytebytego.com/feed": FeedMetadata("ByteByteGo", SourceType.blog, 0.8, "engineering"),
    "https://fiercebiotech.com/rss/biotech": FeedMetadata("Fierce Biotech", SourceType.news, 0.92, "biotech"),
    "https://www.biopharmadive.com/feeds/news": FeedMetadata("BioPharma Dive", SourceType.news, 0.9, "biotech"),
    "https://feeds.feedburner.com/GenGeneticEngineeringNews": FeedMetadata(
        "GEN", SourceType.news, 0.88, "biotech"
    ),
    "https://www.newscientist.com/feed/home/": FeedMetadata("New Scientist", SourceType.news, 0.88, "science"),
    "https://rss.sciam.com/ScientificAmerican": FeedMetadata(
        "Scientific American", SourceType.news, 0.88, "science"
    ),
    "https://www.sciencedaily.com/rss": FeedMetadata("ScienceDaily", SourceType.news, 0.84, "science"),
    "https://techcrunch.com/feed/": FeedMetadata("TechCrunch", SourceType.news, 0.85, "technology"),
    "https://www.theverge.com/rss/index.xml": FeedMetadata("The Verge", SourceType.news, 0.82, "technology"),
    "https://feeds.arstechnica.com/arstechnica/index": FeedMetadata("Ars Technica", SourceType.news, 0.86, "technology"),
    "https://a16z.com/feed/": FeedMetadata("a16z", SourceType.blog, 0.78, "venture"),
}


def _fallback_metadata(url: str) -> FeedMetadata:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "") or "RSS Feed"
    label = host.split(":")[0].replace(".", " ").title()
    return FeedMetadata(label, SourceType.blog, 0.6, "rss")


def canonicalize_feed_url(url: str) -> str:
    return _FEED_ALIASES.get(url, url)


def managed_feed_urls() -> list[str]:
    return [canonicalize_feed_url(url) for url in settings.rss_feeds]


async def sync_rss_sources(session: AsyncSession) -> dict[str, object]:
    feeds = settings.rss_feeds
    if not feeds:
        return {"enabled": bool(settings.rss_source_bootstrap_enabled), "configured_feeds": 0, "created": 0, "updated": 0, "unchanged": 0}

    canonical_feeds = managed_feed_urls()
    existing_lookup_urls = sorted(set(feeds) | set(canonical_feeds))
    existing_rows = (await session.execute(select(Source).where(Source.url.in_(existing_lookup_urls)))).scalars().all()
    existing_by_url = {row.url: row for row in existing_rows}

    created = 0
    updated = 0
    unchanged = 0

    for feed_url in feeds:
        canonical_url = canonicalize_feed_url(feed_url)
        metadata = _KNOWN_FEEDS.get(canonical_url, _fallback_metadata(canonical_url))
        config = {
            "rss_url": canonical_url,
            "max_items": int(settings.rss_source_default_max_items),
            "managed_by": MANAGED_BY,
            "feed_category": metadata.category,
            "configured_url": feed_url,
        }
        existing = existing_by_url.get(canonical_url) or existing_by_url.get(feed_url)
        if existing is None:
            session.add(
                Source(
                    source_type=metadata.source_type,
                    name=metadata.name,
                    url=canonical_url,
                    authority_score=metadata.authority_score,
                    config=config,
                    active=True,
                )
            )
            created += 1
            continue

        changed = False
        if existing.source_type != metadata.source_type:
            existing.source_type = metadata.source_type
            changed = True
        if existing.name != metadata.name:
            existing.name = metadata.name
            changed = True
        if existing.url != canonical_url:
            existing.url = canonical_url
            changed = True
        if float(existing.authority_score) != float(metadata.authority_score):
            existing.authority_score = metadata.authority_score
            changed = True
        merged_config = dict(existing.config or {})
        if merged_config != {**merged_config, **config}:
            merged_config.update(config)
            existing.config = merged_config
            changed = True
        if not existing.active:
            existing.active = True
            changed = True
        if changed:
            updated += 1
        else:
            unchanged += 1

    await session.flush()
    return {
        "enabled": bool(settings.rss_source_bootstrap_enabled),
        "configured_feeds": len(feeds),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
    }
