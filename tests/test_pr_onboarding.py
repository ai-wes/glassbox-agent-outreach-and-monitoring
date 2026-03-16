from __future__ import annotations

import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pr_monitor_app.models import Base, BrandConfigDB, Client, Subscription, TopicLens
import pr_monitor_app.models_agent as _agent_models  # noqa: F401
import pr_monitor_app.models_onboarding as _onboarding_models  # noqa: F401
from pr_monitor_app.models_onboarding import (
    CategoryProposalStatus,
    CompanyResolutionCandidate,
    MonitoringBlueprintProposal,
    OnboardingSession,
    OnboardingStatus,
    ResolvedCompanyProfile,
)
from pr_monitor_app.onboarding_schemas import BlueprintReviewDecisionIn, MaterializeBlueprintIn, OnboardingIntakeIn
from pr_monitor_app.onboarding_service import (
    create_onboarding_session,
    generate_onboarding_blueprint,
    materialize_onboarding_session,
    review_onboarding_blueprint,
)


class OnboardingFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_blueprint_generation_creates_strategic_categories(self) -> None:
        async with self.session_factory() as session:
            detail = await create_onboarding_session(
                session,
                OnboardingIntakeIn(
                    company_name="Acme Bio",
                    notes="Prioritize reputation monitoring and thought leadership.",
                    competitors=["Beta Therapeutics"],
                    executives=["Jane Doe"],
                    products=["OncoMap"],
                    monitoring_goals=["brand visibility", "thought leadership"],
                ),
            )
            row = await session.get(OnboardingSession, detail.session.id)
            candidate = CompanyResolutionCandidate(
                onboarding_session_id=row.id,
                display_name="Acme Bio",
                canonical_name="Acme Bio, Inc.",
                website="https://acmebio.example",
                linkedin_url="https://www.linkedin.com/company/acmebio",
                summary="Biotech company focused on AI-enabled oncology discovery.",
                confidence_score=0.93,
                source_evidence_json={"source": "test"},
                is_selected=True,
                rationale="Strong test candidate.",
            )
            session.add(candidate)
            session.add(
                ResolvedCompanyProfile(
                    onboarding_session_id=row.id,
                    canonical_name="Acme Bio, Inc.",
                    website="https://acmebio.example",
                    linkedin_url="https://www.linkedin.com/company/acmebio",
                    summary="Biotech company focused on AI-enabled oncology discovery.",
                    industry="Biotech",
                    subindustry="Life Sciences",
                    products_json=["OncoMap"],
                    executives_json=["Jane Doe"],
                    competitors_json=["Beta Therapeutics"],
                    channels_json={
                        "official_pages": [
                            "https://acmebio.example",
                            "https://acmebio.example/about",
                            "https://acmebio.example/products",
                        ],
                        "press_pages": ["https://acmebio.example/news"],
                        "blog_pages": ["https://acmebio.example/blog"],
                        "social_profiles": ["https://www.linkedin.com/company/acmebio"],
                        "trade_publications": ["https://example-trade.com/biotech"],
                        "competitor_urls": ["https://betatherapeutics.example"],
                    },
                    themes_json=["oncology narrative", "thought leadership"],
                    risk_themes_json=["regulatory scrutiny", "clinical setbacks"],
                    opportunity_themes_json=["scientific credibility", "category thought leadership"],
                    source_evidence_json={"source": "test"},
                    confidence_json={"resolution_confidence": 0.93},
                )
            )
            await session.commit()

            detail = await generate_onboarding_blueprint(session, row.id)
            self.assertEqual(detail.session.status, OnboardingStatus.awaiting_user_review.value)
            self.assertIsNotNone(detail.blueprint)
            titles = [category.title for category in detail.blueprint.categories]
            self.assertIn("Direct Company Signals", titles)
            self.assertIn("Executive Visibility", titles)
            self.assertIn("Reputation & Risk", titles)

    async def test_materialization_creates_client_topics_and_subscriptions(self) -> None:
        async with self.session_factory() as session:
            detail = await create_onboarding_session(
                session,
                OnboardingIntakeIn(
                    company_name="Acme Bio",
                    competitors=["Beta Therapeutics"],
                    executives=["Jane Doe"],
                    products=["OncoMap"],
                ),
            )
            row = await session.get(OnboardingSession, detail.session.id)
            session.add(
                CompanyResolutionCandidate(
                    onboarding_session_id=row.id,
                    display_name="Acme Bio",
                    canonical_name="Acme Bio, Inc.",
                    website="https://acmebio.example",
                    linkedin_url="https://www.linkedin.com/company/acmebio",
                    summary="Biotech company focused on AI-enabled oncology discovery.",
                    confidence_score=0.95,
                    source_evidence_json={"source": "test"},
                    is_selected=True,
                    rationale="Strong test candidate.",
                )
            )
            session.add(
                ResolvedCompanyProfile(
                    onboarding_session_id=row.id,
                    canonical_name="Acme Bio, Inc.",
                    website="https://acmebio.example",
                    linkedin_url="https://www.linkedin.com/company/acmebio",
                    summary="Biotech company focused on AI-enabled oncology discovery.",
                    industry="Biotech",
                    subindustry="Life Sciences",
                    products_json=["OncoMap"],
                    executives_json=["Jane Doe"],
                    competitors_json=["Beta Therapeutics"],
                    channels_json={
                        "official_pages": [
                            "https://acmebio.example",
                            "https://acmebio.example/team",
                            "https://acmebio.example/products",
                        ],
                        "press_pages": ["https://acmebio.example/news"],
                        "blog_pages": ["https://acmebio.example/blog"],
                        "social_profiles": ["https://www.linkedin.com/company/acmebio"],
                        "trade_publications": ["https://example-trade.com/biotech"],
                        "competitor_urls": ["https://betatherapeutics.example"],
                    },
                    themes_json=["oncology narrative", "product narrative"],
                    risk_themes_json=["regulatory scrutiny", "clinical setbacks"],
                    opportunity_themes_json=["scientific credibility", "category thought leadership"],
                    source_evidence_json={"source": "test"},
                    confidence_json={"resolution_confidence": 0.95},
                )
            )
            await session.commit()

            await generate_onboarding_blueprint(session, row.id)
            await review_onboarding_blueprint(
                session,
                row.id,
                BlueprintReviewDecisionIn(
                    action_type="approve_all",
                    target_type="blueprint",
                    created_by="test",
                ),
            )
            result = await materialize_onboarding_session(
                session,
                row.id,
                MaterializeBlueprintIn(created_by="test", signal_routes=[]),
            )

            self.assertEqual(result.client_name, "Acme Bio, Inc.")
            self.assertGreater(len(result.topic_ids), 0)
            self.assertGreater(len(result.subscription_ids), 0)

            clients = (await session.execute(select(Client))).scalars().all()
            topics = (await session.execute(select(TopicLens))).scalars().all()
            subscriptions = (await session.execute(select(Subscription))).scalars().all()
            brand_configs = (await session.execute(select(BrandConfigDB))).scalars().all()

            self.assertEqual(len(clients), 1)
            self.assertGreaterEqual(len(topics), 4)
            self.assertGreaterEqual(len(subscriptions), 4)
            self.assertEqual(len(brand_configs), 1)

            approved_categories = (
                await session.execute(
                    select(_onboarding_models.MonitoringCategoryProposal).where(
                        _onboarding_models.MonitoringCategoryProposal.status
                        == CategoryProposalStatus.approved.value
                    )
                )
            ).scalars().all()
            self.assertGreater(len(approved_categories), 0)

    async def test_request_revision_creates_new_blueprint_version_and_waits_for_final_approval(self) -> None:
        async with self.session_factory() as session:
            detail = await create_onboarding_session(
                session,
                OnboardingIntakeIn(
                    company_name="Acme Bio",
                    competitors=["Beta Therapeutics"],
                    executives=["Jane Doe"],
                    products=["OncoMap"],
                ),
            )
            row = await session.get(OnboardingSession, detail.session.id)
            session.add(
                CompanyResolutionCandidate(
                    onboarding_session_id=row.id,
                    display_name="Acme Bio",
                    canonical_name="Acme Bio, Inc.",
                    website="https://acmebio.example",
                    linkedin_url="https://www.linkedin.com/company/acmebio",
                    summary="Biotech company focused on AI-enabled oncology discovery.",
                    confidence_score=0.95,
                    source_evidence_json={"source": "test"},
                    is_selected=True,
                    rationale="Strong test candidate.",
                )
            )
            session.add(
                ResolvedCompanyProfile(
                    onboarding_session_id=row.id,
                    canonical_name="Acme Bio, Inc.",
                    website="https://acmebio.example",
                    linkedin_url="https://www.linkedin.com/company/acmebio",
                    summary="Biotech company focused on AI-enabled oncology discovery.",
                    industry="Biotech",
                    subindustry="Life Sciences",
                    products_json=["OncoMap"],
                    executives_json=["Jane Doe"],
                    competitors_json=["Beta Therapeutics"],
                    channels_json={
                        "official_pages": ["https://acmebio.example"],
                        "press_pages": ["https://acmebio.example/news"],
                        "blog_pages": ["https://acmebio.example/blog"],
                        "social_profiles": ["https://www.linkedin.com/company/acmebio"],
                        "trade_publications": ["https://example-trade.com/biotech"],
                        "competitor_urls": ["https://betatherapeutics.example"],
                    },
                    themes_json=["oncology narrative", "product narrative"],
                    risk_themes_json=["regulatory scrutiny"],
                    opportunity_themes_json=["scientific credibility"],
                    source_evidence_json={"source": "test"},
                    confidence_json={"resolution_confidence": 0.95},
                )
            )
            await session.commit()

            detail = await generate_onboarding_blueprint(session, row.id)
            original_blueprint_id = detail.blueprint.id
            detail = await review_onboarding_blueprint(
                session,
                row.id,
                BlueprintReviewDecisionIn(
                    action_type="request_revision",
                    target_type="blueprint",
                    notes="Tighten the risk coverage and emphasize executive visibility.",
                    created_by="test",
                    diff_json={
                        "summary": "Refined operator summary",
                        "company_profile": {"summary": "Updated operator summary"},
                        "categories": [
                            {
                                **detail.blueprint.categories[0].model_dump(),
                                "title": "Direct Company Signals",
                                "status": "proposed",
                            }
                        ],
                    },
                ),
            )

            self.assertEqual(detail.session.status, OnboardingStatus.awaiting_final_approval.value)
            self.assertIsNotNone(detail.blueprint)
            self.assertNotEqual(detail.blueprint.id, original_blueprint_id)
            self.assertEqual(detail.blueprint.proposal_version, 2)

            blueprints = (
                await session.execute(
                    select(MonitoringBlueprintProposal).where(
                        MonitoringBlueprintProposal.onboarding_session_id == row.id
                    )
                )
            ).scalars().all()
            self.assertEqual(len(blueprints), 2)


if __name__ == "__main__":
    unittest.main()
