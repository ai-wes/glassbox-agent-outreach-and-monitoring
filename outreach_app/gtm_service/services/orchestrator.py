from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from outreach_app.gtm_service.core.config import Settings
from outreach_app.gtm_service.db.models import Company, Contact, Lead, LeadScore, LeadStatus, Signal
from outreach_app.gtm_service.schemas.lead import CandidateCompanyInput, CandidateContactInput, CandidateIngestRequest, PipelineResult
from outreach_app.gtm_service.services.crm import SheetsCRMService
from outreach_app.gtm_service.services.lead_sources import SourceIngestionService
from outreach_app.gtm_service.services.research import ResearchAgent, ResearchOutput
from outreach_app.gtm_service.services.router import LeadRouter
from outreach_app.gtm_service.services.scoring import LeadScoringService
from outreach_app.gtm_service.services.sequencer import SequenceService
from outreach_app.gtm_service.services.text_utils import (
    compute_recency_score,
    full_name,
    infer_domain_from_email,
    normalize_domain,
)


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        session: AsyncSession,
        source_service: SourceIngestionService,
        research_agent: ResearchAgent,
        scoring_service: LeadScoringService,
        router: LeadRouter,
        sequence_service: SequenceService,
        crm_sync_service: SheetsCRMService,
    ) -> None:
        self.settings = settings
        self.session = session
        self.source_service = source_service
        self.research_agent = research_agent
        self.scoring_service = scoring_service
        self.router = router
        self.sequence_service = sequence_service
        self.crm_sync_service = crm_sync_service

    async def ingest_candidate(self, payload: CandidateIngestRequest) -> PipelineResult:
        snapshots = await self.source_service.enrich_from_urls([str(url) for url in payload.raw_page_urls])
        website_snippets = [snapshot.text for snapshot in snapshots if snapshot.text]
        company = await self._upsert_company(payload.company)
        contact = await self._upsert_contact(company, payload.contact)
        signal_records = await self._persist_signals(company=company, contact=contact, payload=payload, website_snippets=website_snippets)
        research = await self.research_agent.research(
            company=payload.company,
            contact=payload.contact,
            snippets=payload.snippets + website_snippets,
            existing_signals=[{"raw_text": signal.raw_text} for signal in signal_records],
        )
        await self._persist_research_signals(company=company, contact=contact, research=research)
        lead = await self._upsert_lead(company=company, contact=contact)
        score = await self._score_and_update_lead(lead=lead, company_model=payload.company, contact_model=payload.contact, research=research)
        route = self.router.route(
            lead_grade=score.lead_grade,
            research=research,
            has_email_or_linkedin=bool(contact and (contact.email or contact.linkedin_url)),
        )
        if route.eligible:
            lead.status = LeadStatus.QUALIFIED
        elif route.do_not_contact_reason == "Nurture only until stronger intent appears":
            lead.status = LeadStatus.NURTURE
        else:
            lead.status = LeadStatus.DISQUALIFIED
        lead.icp_class = research.icp_class
        lead.persona_class = research.persona_class
        lead.why_now = research.why_now
        lead.recommended_offer = route.offer
        lead.recommended_sequence = route.sequence_key
        lead.confidence = research.confidence
        lead.last_scored_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(lead)

        if route.eligible and payload.auto_queue:
            await self.sequence_service.queue_lead(self.session, lead_id=lead.id, start_immediately=True)
            lead.status = LeadStatus.QUEUED
            await self.session.commit()

        if contact and self.crm_sync_service.enabled:
            await self.crm_sync_service.sync(company=company, contact=contact, lead=lead, score=score)

        return PipelineResult(
            lead_id=lead.id,
            company_id=company.id,
            contact_id=contact.id if contact else None,
            score_total=score.total_score,
            lead_grade=score.lead_grade,
            status=lead.status.value,
            recommended_sequence=lead.recommended_sequence,
            recommended_offer=lead.recommended_offer,
            why_now=lead.why_now,
        )

    async def rescore_lead(self, lead_id: str) -> PipelineResult:
        lead = await self._get_lead(lead_id)
        if lead is None or lead.company is None:
            raise ValueError(f"Lead {lead_id} not found")
        company_model = CandidateCompanyInput(
            name=lead.company.name,
            domain=lead.company.domain,
            website=lead.company.website,
            headcount=lead.company.headcount,
            funding_stage=lead.company.funding_stage,
            industry=lead.company.industry,
            ai_bio_relevance=lead.company.ai_bio_relevance,
            cloud_signals=lead.company.cloud_signals,
            source_urls=lead.company.source_urls,
        )
        contact_model = None
        if lead.contact:
            contact_model = CandidateContactInput(
                first_name=lead.contact.first_name,
                last_name=lead.contact.last_name,
                full_name=lead.contact.full_name,
                title=lead.contact.title,
                linkedin_url=lead.contact.linkedin_url,
                email=lead.contact.email,
                seniority=lead.contact.seniority,
                function=lead.contact.function,
                inferred_buying_role=lead.contact.inferred_buying_role,
                email_verified=lead.contact.email_verified,
            )
        snippets = [signal.raw_text for signal in lead.company.signals[: self.settings.max_signal_snippets]]
        research = await self.research_agent.research(
            company=company_model,
            contact=contact_model,
            snippets=snippets,
            existing_signals=[{"raw_text": signal.raw_text} for signal in lead.company.signals],
        )
        score = await self._score_and_update_lead(lead=lead, company_model=company_model, contact_model=contact_model, research=research)
        route = self.router.route(
            lead_grade=score.lead_grade,
            research=research,
            has_email_or_linkedin=bool(lead.contact and (lead.contact.email or lead.contact.linkedin_url)),
        )
        lead.status = LeadStatus.QUALIFIED if route.eligible else LeadStatus.NURTURE
        lead.icp_class = research.icp_class
        lead.persona_class = research.persona_class
        lead.why_now = research.why_now
        lead.recommended_offer = route.offer
        lead.recommended_sequence = route.sequence_key
        lead.confidence = research.confidence
        lead.last_scored_at = datetime.now(timezone.utc)
        await self.session.commit()
        return PipelineResult(
            lead_id=lead.id,
            company_id=lead.company.id,
            contact_id=lead.contact.id if lead.contact else None,
            score_total=score.total_score,
            lead_grade=score.lead_grade,
            status=lead.status.value,
            recommended_sequence=lead.recommended_sequence,
            recommended_offer=lead.recommended_offer,
            why_now=lead.why_now,
        )

    async def _upsert_company(self, company_model: CandidateCompanyInput) -> Company:
        normalized_domain = normalize_domain(company_model.domain) or normalize_domain(str(company_model.website) if company_model.website else None)
        stmt = None
        if normalized_domain:
            stmt = select(Company).where(Company.domain == normalized_domain)
        else:
            stmt = select(Company).where(Company.name == company_model.name)
        existing = (await self.session.execute(stmt)).scalars().one_or_none()
        if existing:
            existing.name = company_model.name
            existing.domain = normalized_domain or existing.domain
            existing.website = str(company_model.website) if company_model.website else existing.website
            existing.headcount = company_model.headcount or existing.headcount
            existing.funding_stage = company_model.funding_stage or existing.funding_stage
            existing.industry = company_model.industry or existing.industry
            existing.ai_bio_relevance = company_model.ai_bio_relevance or existing.ai_bio_relevance
            existing.cloud_signals = {**existing.cloud_signals, **company_model.cloud_signals}
            existing.source_urls = list(dict.fromkeys((existing.source_urls or []) + company_model.source_urls))
            await self.session.flush()
            return existing
        company = Company(
            name=company_model.name,
            domain=normalized_domain,
            website=str(company_model.website) if company_model.website else None,
            headcount=company_model.headcount,
            funding_stage=company_model.funding_stage,
            industry=company_model.industry,
            ai_bio_relevance=company_model.ai_bio_relevance or 0.0,
            cloud_signals=company_model.cloud_signals,
            source_urls=company_model.source_urls,
        )
        self.session.add(company)
        await self.session.flush()
        return company

    async def _upsert_contact(self, company: Company, contact_model: CandidateContactInput | None) -> Contact | None:
        if contact_model is None:
            return None
        normalized_email_domain = infer_domain_from_email(contact_model.email) if contact_model.email else None
        combined_name = full_name(contact_model.first_name, contact_model.last_name, contact_model.full_name)
        existing = None
        if contact_model.email:
            lookup_stmt = select(Contact).where(Contact.email == str(contact_model.email))
            existing = (await self.session.execute(lookup_stmt)).scalars().first()
        elif contact_model.linkedin_url:
            lookup_stmt = select(Contact).where(Contact.linkedin_url == str(contact_model.linkedin_url), Contact.company_id == company.id)
            existing = (await self.session.execute(lookup_stmt)).scalars().first()
        elif combined_name:
            lookup_stmt = select(Contact).where(Contact.full_name == combined_name, Contact.company_id == company.id)
            existing = (await self.session.execute(lookup_stmt)).scalars().first()
        if existing:
            existing.company_id = company.id
            existing.first_name = contact_model.first_name or existing.first_name
            existing.last_name = contact_model.last_name or existing.last_name
            existing.full_name = combined_name or existing.full_name
            existing.title = contact_model.title or existing.title
            existing.linkedin_url = str(contact_model.linkedin_url) if contact_model.linkedin_url else existing.linkedin_url
            existing.email = str(contact_model.email) if contact_model.email else existing.email
            existing.seniority = contact_model.seniority or existing.seniority
            existing.function = contact_model.function or existing.function
            existing.inferred_buying_role = contact_model.inferred_buying_role or existing.inferred_buying_role
            existing.email_verified = existing.email_verified or contact_model.email_verified
            await self.session.flush()
            return existing
        contact = Contact(
            company_id=company.id,
            first_name=contact_model.first_name,
            last_name=contact_model.last_name,
            full_name=combined_name,
            title=contact_model.title,
            linkedin_url=str(contact_model.linkedin_url) if contact_model.linkedin_url else None,
            email=str(contact_model.email) if contact_model.email else None,
            seniority=contact_model.seniority,
            function=contact_model.function,
            inferred_buying_role=contact_model.inferred_buying_role or normalized_email_domain,
            email_verified=contact_model.email_verified,
        )
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def _persist_signals(self, *, company: Company, contact: Contact | None, payload: CandidateIngestRequest, website_snippets: list[str]) -> list[Signal]:
        created: list[Signal] = []
        for item in payload.signals:
            signal = Signal(
                company_id=company.id,
                contact_id=contact.id if contact else None,
                type=item.type,
                source=item.source,
                source_url=str(item.source_url) if item.source_url else None,
                occurred_at=item.occurred_at,
                raw_text=item.raw_text,
                extracted_summary=None,
                confidence=0.75,
                recency_score=compute_recency_score(item.occurred_at),
                metadata_json=item.metadata_json,
            )
            self.session.add(signal)
            created.append(signal)
        for snippet in website_snippets[:3]:
            signal = Signal(
                company_id=company.id,
                contact_id=contact.id if contact else None,
                type="website_snapshot",
                source=payload.source,
                source_url=str(payload.raw_page_urls[0]) if payload.raw_page_urls else None,
                occurred_at=None,
                raw_text=snippet,
                extracted_summary=snippet[:240],
                confidence=0.55,
                recency_score=0.4,
                metadata_json={},
            )
            self.session.add(signal)
            created.append(signal)
        await self.session.flush()
        return created

    async def _persist_research_signals(self, *, company: Company, contact: Contact | None, research: ResearchOutput) -> None:
        for extracted in research.extracted_signals:
            signal = Signal(
                company_id=company.id,
                contact_id=contact.id if contact else None,
                type=extracted.type,
                source="research_agent",
                source_url=None,
                occurred_at=extracted.occurred_at,
                raw_text=extracted.summary,
                extracted_summary=extracted.summary,
                confidence=extracted.confidence,
                recency_score=compute_recency_score(extracted.occurred_at),
                metadata_json={"generated": True},
            )
            self.session.add(signal)
        await self.session.flush()

    async def _upsert_lead(self, *, company: Company, contact: Contact | None) -> Lead:
        stmt = select(Lead).where(Lead.company_id == company.id)
        if contact:
            stmt = select(Lead).where(Lead.contact_id == contact.id)
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            return existing
        lead = Lead(company_id=company.id, contact_id=contact.id if contact else None, status=LeadStatus.NEW)
        self.session.add(lead)
        await self.session.flush()
        return lead

    async def _score_and_update_lead(self, *, lead: Lead, company_model: CandidateCompanyInput, contact_model: CandidateContactInput | None, research: ResearchOutput) -> LeadScore:
        signal_count_stmt = select(Signal).where(Signal.company_id == lead.company_id)
        signal_count = len((await self.session.execute(signal_count_stmt)).scalars().all())
        score_breakdown = await self.scoring_service.score(company=company_model, contact=contact_model, research=research, signal_count=signal_count)
        score = LeadScore(
            lead_id=lead.id,
            company_fit=score_breakdown.company_fit,
            persona_fit=score_breakdown.persona_fit,
            trigger_strength=score_breakdown.trigger_strength,
            pain_fit=score_breakdown.pain_fit,
            reachability=score_breakdown.reachability,
            total_score=score_breakdown.total_score,
            lead_grade=score_breakdown.lead_grade,
            rationale=score_breakdown.rationale,
            model_confidence=score_breakdown.model_confidence,
        )
        self.session.add(score)
        await self.session.flush()
        return score

    async def _get_lead(self, lead_id: str) -> Lead | None:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id)
            .options(
                selectinload(Lead.company).selectinload(Company.signals),
                selectinload(Lead.contact),
                selectinload(Lead.scores),
            )
        )
        return (await self.session.execute(stmt)).scalars().unique().one_or_none()
