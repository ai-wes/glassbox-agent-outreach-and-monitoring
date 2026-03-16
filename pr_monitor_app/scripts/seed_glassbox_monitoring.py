from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pr_monitor_app.bootstrap.rss_sources import _KNOWN_FEEDS, canonicalize_feed_url, managed_feed_urls, sync_rss_sources
from pr_monitor_app.db import session_scope
from pr_monitor_app.models import Client, Subscription, SubscriptionType, TopicLens


CLIENT_NAME = "Glassbox Bio"

TOPIC_PAYLOADS = [
    {
        "name": "AI Biotech Signals",
        "description": "AI drug discovery, computational biology, foundation models, and platform company momentum.",
        "keywords": [
            "AI drug discovery",
            "computational biology",
            "foundation model",
            "machine learning",
            "biotech platform",
            "therapeutics",
        ],
        "competitor_overrides": ["Recursion", "Isomorphic Labs", "Xaira"],
        "risk_flags": ["layoffs", "trial hold", "financing risk", "program pause"],
        "opportunity_tags": ["platform story", "data moat", "AI differentiation"],
    },
    {
        "name": "Clinical and Regulatory Catalysts",
        "description": "Trial starts, readouts, INDs, designations, approvals, and regulatory scrutiny.",
        "keywords": [
            "phase 1",
            "phase 2",
            "phase 3",
            "IND",
            "FDA",
            "regulatory",
            "clinical trial",
        ],
        "competitor_overrides": [],
        "risk_flags": ["clinical hold", "safety signal", "delay", "rejection"],
        "opportunity_tags": ["trial milestone", "regulatory window", "program update"],
    },
    {
        "name": "Capital and Market Narrative",
        "description": "Fundraising, partnerships, M&A, strategic positioning, and market category framing.",
        "keywords": [
            "Series A",
            "Series B",
            "financing",
            "partnership",
            "acquisition",
            "launch",
            "platform",
        ],
        "competitor_overrides": [],
        "risk_flags": ["cash runway", "down round", "restructuring"],
        "opportunity_tags": ["capital event", "strategic partnership", "category narrative"],
    },
]


def _subscription_name(url: str) -> str:
    metadata = _KNOWN_FEEDS.get(url)
    if metadata is not None:
        return metadata.name
    return url


async def _seed() -> None:
    async with session_scope() as session:
        await sync_rss_sources(session)

        client = (
            await session.execute(select(Client).where(Client.name == CLIENT_NAME))
        ).scalar_one_or_none()
        if client is None:
            client = Client(
                name=CLIENT_NAME,
                messaging_pillars=[
                    "Biotech narrative intelligence",
                    "AI platform positioning",
                    "Commercial relevance from scientific momentum",
                ],
                risk_keywords=[
                    "layoffs",
                    "clinical hold",
                    "financing risk",
                    "regulatory setback",
                    "program pause",
                ],
                audience_profile={
                    "segments": ["biotech", "AI drug discovery", "scientific software"],
                    "roles": ["CEO", "Chief Business Officer", "Head of Communications", "Investor Relations"],
                },
                brand_voice_profile={
                    "tone": "direct, technical, commercially literate",
                    "avoid": ["hype", "generic thought leadership"],
                },
                competitors=["Recursion", "Xaira", "Isomorphic Labs", "Generate Biomedicines"],
                email_recipient=None,
                signal_recipient=None,
                telegram_recipient=None,
                whatsapp_recipient=None,
            )
            session.add(client)
            await session.flush()

        topics_by_name = {
            topic.name: topic
            for topic in (
                await session.execute(select(TopicLens).where(TopicLens.client_id == client.id))
            ).scalars().all()
        }
        for payload in TOPIC_PAYLOADS:
            if payload["name"] in topics_by_name:
                continue
            session.add(
                TopicLens(
                    client_id=client.id,
                    name=payload["name"],
                    description=payload["description"],
                    keywords=payload["keywords"],
                    competitor_overrides=payload["competitor_overrides"],
                    risk_flags=payload["risk_flags"],
                    opportunity_tags=payload["opportunity_tags"],
                    embedding=None,
                )
            )

        existing_subscriptions = {
            row.url
            for row in (
                await session.execute(
                    select(Subscription).where(
                        Subscription.client_id == client.id,
                        Subscription.type == SubscriptionType.rss,
                    )
                )
            ).scalars().all()
        }

        for raw_url in managed_feed_urls():
            url = canonicalize_feed_url(raw_url)
            if url in existing_subscriptions:
                continue
            session.add(
                Subscription(
                    client_id=client.id,
                    topic_id=None,
                    type=SubscriptionType.rss,
                    name=_subscription_name(url),
                    url=url,
                    enabled=True,
                    poll_interval_seconds=1800,
                    fetch_full_content=True,
                    meta_json={"seeded_by": "seed_glassbox_monitoring"},
                )
            )


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
