from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.db.models import Company, Contact, Lead, LeadStatus, Signal
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput
from outreach_app.gtm_service.services.crm import SheetsCRMService
from outreach_app.gtm_service.services.lead_sources import SourceIngestionService
from outreach_app.gtm_service.services.metrics import MetricsService
from outreach_app.gtm_service.services.orchestrator import PipelineOrchestrator
from outreach_app.gtm_service.services.research import ResearchAgent
from outreach_app.gtm_service.services.router import LeadRouter
from outreach_app.gtm_service.services.scoring import LeadScoringService
from outreach_app.gtm_service.services.scraper import ProspectingScraper
from outreach_app.gtm_service.services.sequencer import SequenceService
from outreach_app.gtm_service.services.text_utils import normalize_domain


class ProspectingRunResult(BaseModel):
    task: str
    processed: int
    success_count: int
    failure_count: int
    lead_ids: list[str] = Field(default_factory=list)
    contact_ids: list[str] = Field(default_factory=list)
    synced: dict[str, int] | None = None


class ProspectingService:
    def __init__(
        self,
        *,
        settings: Settings,
        source_service: SourceIngestionService,
        scraper: ProspectingScraper,
        research_agent: ResearchAgent,
        scoring_service: LeadScoringService,
        router: LeadRouter,
        sequence_service: SequenceService,
        crm_sync_service: SheetsCRMService,
        metrics_service: MetricsService,
    ) -> None:
        self.settings = settings
        self.source_service = source_service
        self.scraper = scraper
        self.research_agent = research_agent
        self.scoring_service = scoring_service
        self.router = router
        self.sequence_service = sequence_service
        self.crm_sync_service = crm_sync_service
        self.metrics_service = metrics_service

    async def discover_from_domains(self, session: AsyncSession, domains: Sequence[str]) -> ProspectingRunResult:
        lead_ids: list[str] = []
        success_count = 0
        failure_count = 0
        cleaned_domains = [domain for domain in (normalize_domain(item) for item in domains) if domain]

        for domain in cleaned_domains:
            try:
                snapshot = await self.scraper.scrape_company(domain)
                company = await self._upsert_company(
                    session,
                    name=snapshot.title or domain,
                    domain=domain,
                    website=snapshot.website,
                )
                if snapshot.description:
                    await self._upsert_signal(
                        session,
                        company=company,
                        source_url=snapshot.website,
                        raw_text=snapshot.description,
                    )
                lead = await self._get_or_create_lead(session, company=company)
                lead_ids.append(lead.id)
                await session.commit()
                success_count += 1
            except Exception:
                await session.rollback()
                failure_count += 1

        return ProspectingRunResult(
            task="discovery",
            processed=len(cleaned_domains),
            success_count=success_count,
            failure_count=failure_count,
            lead_ids=lead_ids,
        )

    async def enrich_leads(self, session: AsyncSession, *, limit: int = 100) -> ProspectingRunResult:
        stmt = (
            select(Lead)
            .join(Lead.company)
            .outerjoin(Lead.contact)
            .where(
                Company.domain.is_not(None),
                or_(Lead.contact_id.is_(None), Contact.email.is_(None)),
            )
            .order_by(Lead.updated_at.desc())
            .limit(limit)
            .options(selectinload(Lead.company), selectinload(Lead.contact))
        )
        leads = list((await session.execute(stmt)).scalars().unique().all())
        lead_ids: list[str] = []
        contact_ids: list[str] = []
        success_count = 0
        failure_count = 0

        for lead in leads:
            if lead.company is None or not lead.company.domain:
                failure_count += 1
                continue
            try:
                contacts = await self.scraper.discover_contacts(lead.company.domain)
                if not contacts:
                    failure_count += 1
                    continue
                selected_contact: Contact | None = None
                for index, candidate in enumerate(contacts):
                    contact = await self._get_or_create_contact(
                        session,
                        company=lead.company,
                        candidate=CandidateContactInput(
                            first_name=candidate.first_name,
                            last_name=candidate.last_name,
                            full_name=candidate.full_name,
                            email=candidate.email,
                            email_verified=False,
                        ),
                    )
                    if index == 0:
                        selected_contact = contact
                    contact_ids.append(contact.id)
                if selected_contact is not None:
                    lead.contact_id = selected_contact.id
                    if lead.status == LeadStatus.NEW:
                        lead.status = LeadStatus.RESEARCHED
                    lead_ids.append(lead.id)
                await session.commit()
                success_count += 1
            except Exception:
                await session.rollback()
                failure_count += 1

        return ProspectingRunResult(
            task="enrichment",
            processed=len(leads),
            success_count=success_count,
            failure_count=failure_count,
            lead_ids=lead_ids,
            contact_ids=contact_ids,
        )

    async def verify_leads(self, session: AsyncSession, *, limit: int = 100) -> ProspectingRunResult:
        stmt = (
            select(Lead)
            .join(Lead.company)
            .join(Lead.contact)
            .where(Contact.email.is_not(None), Contact.email_verified.is_(False))
            .order_by(Lead.updated_at.desc())
            .limit(limit)
            .options(selectinload(Lead.company), selectinload(Lead.contact))
        )
        leads = list((await session.execute(stmt)).scalars().unique().all())
        lead_ids: list[str] = []
        contact_ids: list[str] = []
        success_count = 0
        failure_count = 0

        for lead in leads:
            if lead.contact is None:
                failure_count += 1
                continue
            is_valid = self.scraper.verify_email(
                lead.contact.email,
                company_domain=lead.company.domain if lead.company else None,
            )
            lead.contact.email_verified = is_valid
            if is_valid:
                if lead.status == LeadStatus.NEW:
                    lead.status = LeadStatus.RESEARCHED
                success_count += 1
            else:
                failure_count += 1
            lead_ids.append(lead.id)
            contact_ids.append(lead.contact.id)
            await session.commit()

        return ProspectingRunResult(
            task="verification",
            processed=len(leads),
            success_count=success_count,
            failure_count=failure_count,
            lead_ids=lead_ids,
            contact_ids=contact_ids,
        )

    async def score_leads(self, session: AsyncSession, *, limit: int = 100) -> ProspectingRunResult:
        stmt = (
            select(Lead)
            .where(Lead.contact_id.is_not(None))
            .order_by(Lead.updated_at.desc())
            .limit(limit)
            .options(
                selectinload(Lead.company).selectinload(Company.signals),
                selectinload(Lead.contact),
                selectinload(Lead.scores),
            )
        )
        leads = list((await session.execute(stmt)).scalars().unique().all())
        orchestrator = PipelineOrchestrator(
            settings=self.settings,
            session=session,
            source_service=self.source_service,
            research_agent=self.research_agent,
            scoring_service=self.scoring_service,
            router=self.router,
            sequence_service=self.sequence_service,
            crm_sync_service=self.crm_sync_service,
        )

        lead_ids: list[str] = []
        success_count = 0
        failure_count = 0
        for lead in leads:
            try:
                await orchestrator.rescore_lead(lead.id)
                lead_ids.append(lead.id)
                success_count += 1
            except Exception:
                await session.rollback()
                failure_count += 1

        return ProspectingRunResult(
            task="scoring",
            processed=len(leads),
            success_count=success_count,
            failure_count=failure_count,
            lead_ids=lead_ids,
        )

    async def sync_to_crm(self, session: AsyncSession) -> ProspectingRunResult:
        if not self.crm_sync_service.enabled:
            return ProspectingRunResult(
                task="sync",
                processed=0,
                success_count=0,
                failure_count=1,
            )
        sync_result = await self.crm_sync_service.full_sync(
            session=session,
            metrics_service=self.metrics_service,
        )
        processed = sum(
            int(sync_result.get(key, 0))
            for key in [
                "lead_rows",
                "account_rows",
                "contact_rows",
                "activity_rows",
                "deal_rows",
                "reply_rows",
                "delivery_rows",
                "conversion_rows",
            ]
        )
        return ProspectingRunResult(
            task="sync",
            processed=processed,
            success_count=1,
            failure_count=0,
            synced={key: int(value) for key, value in sync_result.items() if isinstance(value, int)},
        )

    async def _upsert_company(
        self,
        session: AsyncSession,
        *,
        name: str,
        domain: str,
        website: str | None,
    ) -> Company:
        company = (
            await session.execute(select(Company).where(Company.domain == domain))
        ).scalars().one_or_none()
        if company is not None:
            company.name = name or company.name
            company.website = website or company.website
            await session.flush()
            return company
        company = Company(name=name, domain=domain, website=website)
        session.add(company)
        await session.flush()
        return company

    async def _upsert_signal(
        self,
        session: AsyncSession,
        *,
        company: Company,
        source_url: str,
        raw_text: str,
    ) -> Signal:
        existing = (
            await session.execute(
                select(Signal).where(
                    Signal.company_id == company.id,
                    Signal.source == "website",
                    Signal.source_url == source_url,
                    Signal.raw_text == raw_text,
                )
            )
        ).scalars().one_or_none()
        if existing is not None:
            return existing
        signal = Signal(
            company_id=company.id,
            type="website_summary",
            source="website",
            source_url=source_url,
            raw_text=raw_text,
            extracted_summary=raw_text[:500],
            confidence=0.6,
            recency_score=0.4,
        )
        session.add(signal)
        await session.flush()
        return signal

    async def _get_or_create_lead(self, session: AsyncSession, *, company: Company) -> Lead:
        lead = (
            await session.execute(
                select(Lead).where(Lead.company_id == company.id, Lead.contact_id.is_(None))
            )
        ).scalars().one_or_none()
        if lead is not None:
            return lead
        lead = Lead(company_id=company.id, status=LeadStatus.NEW)
        session.add(lead)
        await session.flush()
        return lead

    async def _get_or_create_contact(
        self,
        session: AsyncSession,
        *,
        company: Company,
        candidate: CandidateContactInput,
    ) -> Contact:
        email = candidate.email
        existing = None
        if email:
            existing = (
                await session.execute(select(Contact).where(Contact.email == email.lower()))
            ).scalars().one_or_none()
        elif candidate.full_name:
            existing = (
                await session.execute(
                    select(Contact).where(
                        Contact.company_id == company.id,
                        Contact.full_name == candidate.full_name,
                    )
                )
            ).scalars().one_or_none()
        if existing is not None:
            existing.company_id = company.id
            existing.first_name = candidate.first_name or existing.first_name
            existing.last_name = candidate.last_name or existing.last_name
            existing.full_name = candidate.full_name or existing.full_name
            existing.email = email.lower() if email else existing.email
            await session.flush()
            return existing
        contact = Contact(
            company_id=company.id,
            first_name=candidate.first_name,
            last_name=candidate.last_name,
            full_name=candidate.full_name,
            email=email.lower() if email else None,
            email_verified=candidate.email_verified,
        )
        session.add(contact)
        await session.flush()
        return contact
