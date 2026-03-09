from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from pr_monitor_app.db import session_scope
from pr_monitor_app.models import Client, Source, SourceType, TopicLens

log = structlog.get_logger(__name__)


async def _seed() -> None:
    async with session_scope() as session:
        # Only seed if empty
        existing = (await session.execute(select(Client).limit(1))).scalar_one_or_none()
        if existing:
            log.info("seed_skipped_existing_data")
            return

        client = Client(
            name="DemoClient",
            messaging_pillars=["AI governance", "Product velocity", "Trust & safety"],
            risk_keywords=["lawsuit", "breach", "regulator", "illegal"],
            audience_profile={"roles": ["CTO", "Head of Product"], "segments": ["B2B SaaS"], "pain_points": ["compliance", "time-to-value"]},
            brand_voice_profile={"avoid": ["hype", "guaranteed"], "required_words": ["practical"]},
            competitors=["CompetitorCo", "RivalAI"],
            signal_recipient=None,
            telegram_recipient=None,
            whatsapp_recipient=None,
        )
        session.add(client)
        await session.flush()

        topics = [
            TopicLens(client_id=client.id, name="AI Regulation", description="Policy, compliance, liability, governance", keywords=["AI Act", "liability", "compliance"]),
            TopicLens(client_id=client.id, name="Enterprise AI", description="Operationalizing AI in large orgs", keywords=["enterprise", "security", "deployment"]),
            TopicLens(client_id=client.id, name="Model Risk", description="Safety, monitoring, evals", keywords=["safety", "alignment", "monitoring"]),
            TopicLens(client_id=client.id, name="Product Strategy", description="Go-to-market, product leadership, differentiation", keywords=["product", "strategy", "positioning"]),
            TopicLens(client_id=client.id, name="Data & Privacy", description="Privacy, data governance, security", keywords=["privacy", "GDPR", "data"]),
            TopicLens(client_id=client.id, name="Competitive Moves", description="Competitor positioning and narrative moves", keywords=["competitor", "market", "launch"]),
        ]
        for t in topics:
            session.add(t)

        # Example sources (RSS)
        session.add(
            Source(
                source_type=SourceType.news,
                name="Google News AI RSS",
                url="https://news.google.com/rss/search?q=AI%20regulation",
                authority_score=0.7,
                config={"rss_url": "https://news.google.com/rss/search?q=AI%20regulation&hl=en-US&gl=US&ceid=US:en", "max_items": 30},
                active=True,
            )
        )
        session.add(
            Source(
                source_type=SourceType.blog,
                name="Example Blog",
                url="https://example.com/blog",
                authority_score=0.4,
                config={"html_url": "https://example.com"},
                active=False,
            )
        )

        log.info("seed_done")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
