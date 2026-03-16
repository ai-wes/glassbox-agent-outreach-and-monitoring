from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from glassbox_radar.connectors.clinical_trials import ClinicalTrialsCollector
from glassbox_radar.connectors.funding import FundingCollector
from glassbox_radar.connectors.preprints import PreprintCollector
from glassbox_radar.connectors.pubmed import PubMedCollector
from glassbox_radar.connectors.rss import RSSCollector
from glassbox_radar.contracts import CollectionContext, ContactSnapshot
from glassbox_radar.core.config import get_settings
from glassbox_radar.enums import EvidenceType, OpportunityStatus, PipelineRunStatus
from glassbox_radar.models import Company, Contact, EvidenceNode, Opportunity, PipelineRun, Program, Signal
from glassbox_radar.services.classifier import classify_signal
from glassbox_radar.services.dossiers import write_dossier
from glassbox_radar.services.evidence import human_relevance_for_evidence, publication_status_for_source
from glassbox_radar.services.inference import infer_milestone
from glassbox_radar.services.scoring import score_program
from glassbox_radar.services.sheets_export import OpportunitySheetsExporter
from glassbox_radar.services.watchlist_sync import sync_watchlist
from glassbox_radar.utils import make_content_hash, utcnow
from glassbox_radar.watchlist import load_watchlist

logger = logging.getLogger(__name__)


class RadarPipeline:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.settings = get_settings()
        self.session_factory = session_factory
        self.pubmed = PubMedCollector()
        self.preprints = PreprintCollector()
        self.clinical_trials = ClinicalTrialsCollector()
        self.rss = RSSCollector()
        self.funding = FundingCollector()

    async def _load_contexts(self, session: AsyncSession) -> list[tuple[Company, Program, CollectionContext]]:
        result = await session.execute(
            select(Company)
            .where(Company.is_active.is_(True))
            .options(selectinload(Company.programs), selectinload(Company.contacts))
        )
        companies = result.scalars().unique().all()
        contexts: list[tuple[Company, Program, CollectionContext]] = []
        for company in companies:
            for program in company.programs:
                context = CollectionContext(
                    company_id=company.id,
                    program_id=program.id,
                    company_name=company.name,
                    company_aliases=company.aliases,
                    domain=company.domain,
                    warm_intro_paths=company.warm_intro_paths,
                    investors=company.lead_investors,
                    board_members=company.board_members,
                    company_stage=company.stage,
                    asset_name=program.asset_name,
                    target=program.target,
                    mechanism=program.mechanism,
                    modality=program.modality,
                    indication=program.indication,
                    stage=program.stage,
                    key_terms=program.key_terms,
                    rss_feeds=company.rss_feeds,
                    contacts=[
                        ContactSnapshot(
                            name=contact.name,
                            title=contact.title,
                            email=contact.email,
                            role=contact.role,
                            warm_intro_strength=contact.warm_intro_strength,
                            is_primary=contact.is_primary,
                        )
                        for contact in company.contacts
                    ],
                )
                contexts.append((company, program, context))
        return contexts

    async def _sync_watchlist_if_present(self, session: AsyncSession) -> dict[str, int]:
        if not self.settings.watchlist_path.exists():
            logger.warning("Radar watchlist file missing: %s", self.settings.watchlist_path)
            return {"companies": 0, "programs": 0, "contacts": 0}
        companies = load_watchlist(self.settings.watchlist_path)
        if not companies:
            logger.warning("Radar watchlist is empty: %s", self.settings.watchlist_path)
        return await sync_watchlist(session, companies)

    async def _collect_for_context(
        self,
        context: CollectionContext,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> list[Any]:
        async with semaphore:
            results = await asyncio.gather(
                self.pubmed.collect(context, client),
                self.preprints.collect(context, client),
                self.clinical_trials.collect(context, client),
                self.rss.collect(context, client),
                self.funding.collect(context, client),
                return_exceptions=True,
            )

        collected = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Connector failed for program %s: %s", context.program_id, result)
                continue
            collected.extend(result)
        return collected

    async def _upsert_signals(
        self,
        session: AsyncSession,
        company: Company,
        program: Program,
        context: CollectionContext,
        collected_signals: list[Any],
    ) -> tuple[int, int]:
        created = 0
        evidence_created = 0
        for candidate in collected_signals:
            classified = classify_signal(candidate, context)
            content_hash = make_content_hash(
                company.id,
                program.id,
                classified.source_url,
                classified.title,
                classified.summary,
                classified.content,
            )
            existing_result = await session.execute(select(Signal).where(Signal.content_hash == content_hash))
            existing = existing_result.scalar_one_or_none()
            if existing is None:
                signal = Signal(
                    company_id=company.id,
                    program_id=program.id,
                    source_type=classified.source_type,
                    signal_type=classified.signal_type,
                    title=classified.title,
                    summary=classified.summary,
                    content=classified.content,
                    source_url=classified.source_url,
                    published_at=classified.published_at,
                    confidence=classified.confidence,
                    content_hash=content_hash,
                    raw_payload=classified.raw_payload,
                    evidence_tags=classified.evidence_tags,
                    milestone_tags=classified.milestone_tags,
                )
                session.add(signal)
                await session.flush()
                created += 1
            else:
                signal = existing
                signal.signal_type = classified.signal_type
                signal.summary = classified.summary
                signal.content = classified.content
                signal.published_at = classified.published_at
                signal.confidence = max(signal.confidence, classified.confidence)
                signal.evidence_tags = sorted(set(signal.evidence_tags) | set(classified.evidence_tags))
                signal.milestone_tags = sorted(set(signal.milestone_tags) | set(classified.milestone_tags))

            existing_evidence_result = await session.execute(
                select(EvidenceNode).where(EvidenceNode.source_signal_id == signal.id)
            )
            existing_evidence_types = {node.evidence_type for node in existing_evidence_result.scalars().all()}

            for evidence_tag in signal.evidence_tags:
                try:
                    evidence_type = EvidenceType(evidence_tag)
                except ValueError:
                    continue
                if evidence_type in existing_evidence_types:
                    continue
                node = EvidenceNode(
                    program_id=program.id,
                    source_signal_id=signal.id,
                    evidence_type=evidence_type,
                    model_type=evidence_tag.replace("_", " "),
                    human_relevance_score=human_relevance_for_evidence(evidence_type),
                    orthogonality_tag=evidence_type == EvidenceType.ORTHOGONAL_ASSAY,
                    replication_signal=evidence_type == EvidenceType.REPLICATION,
                    publication_status=publication_status_for_source(signal.source_type),
                    strength=signal.confidence,
                    extracted_from=signal.source_url,
                )
                session.add(node)
                evidence_created += 1
        await session.flush()
        return created, evidence_created

    async def _evaluate_program(
        self,
        session: AsyncSession,
        company: Company,
        program: Program,
        context: CollectionContext,
    ) -> Opportunity:
        signals_result = await session.execute(
            select(Signal)
            .where(Signal.program_id == program.id)
            .order_by(Signal.published_at.desc().nullslast(), Signal.created_at.desc())
        )
        signals = signals_result.scalars().all()

        evidence_result = await session.execute(
            select(EvidenceNode).where(EvidenceNode.program_id == program.id)
        )
        evidence_nodes = evidence_result.scalars().all()

        inference = infer_milestone(program, signals)
        signals_text = " ".join(
            " ".join(filter(None, [signal.title, signal.summary, signal.content]))
            for signal in signals[:20]
        )
        score = score_program(
            program=program,
            evidence_nodes=evidence_nodes,
            inference=inference,
            context=context,
            signals_text=signals_text,
        )

        opp_result = await session.execute(select(Opportunity).where(Opportunity.program_id == program.id))
        opportunity = opp_result.scalar_one_or_none()
        if opportunity is None:
            opportunity = Opportunity(company_id=company.id, program_id=program.id, status=OpportunityStatus.DETECTED)
            session.add(opportunity)

        opportunity.radar_score = score.radar_score
        opportunity.milestone_score = score.milestone_score
        opportunity.fragility_score = score.fragility_score
        opportunity.capital_score = score.capital_score
        opportunity.reachability_score = score.reachability_score
        opportunity.milestone_type = score.milestone_type
        opportunity.milestone_confidence = score.milestone_confidence
        opportunity.milestone_window_start = score.milestone_window_start
        opportunity.milestone_window_end = score.milestone_window_end
        opportunity.primary_buyer_role = score.primary_buyer_role
        opportunity.outreach_angle = score.outreach_angle
        opportunity.risk_hypothesis = score.risk_hypothesis
        opportunity.capital_exposure_band = score.capital_exposure_band
        opportunity.tier = score.tier
        opportunity.owner = opportunity.owner or self.settings.default_owner
        opportunity.last_evaluated_at = utcnow()

        program.estimated_next_milestone = score.milestone_type
        program.estimated_milestone_date = score.milestone_window_end
        program.milestone_confidence = score.milestone_confidence
        program.latest_radar_score = score.radar_score

        if score.radar_score >= self.settings.min_score_for_dossier:
            opportunity.dossier_path = write_dossier(
                company=company,
                program=program,
                context=context,
                score=score,
                inference=inference,
                signals=signals,
            )

        if self.settings.sheet_export_ready and score.radar_score >= self.settings.min_score_for_sheet_export:
            contact = await self._primary_contact(session, company.id)
            sheet_export = await OpportunitySheetsExporter().export_opportunity(
                company,
                program,
                contact,
                opportunity,
                score,
            )
            opportunity.sheet_row_reference = sheet_export.get("updated_range")
            opportunity.last_exported_to_sheet_at = datetime.now(tz=UTC)

        await session.flush()
        return opportunity

    async def _primary_contact(self, session: AsyncSession, company_id: str) -> Contact | None:
        result = await session.execute(
            select(Contact)
            .where(Contact.company_id == company_id)
            .order_by(Contact.is_primary.desc(), Contact.warm_intro_strength.desc().nullslast())
        )
        return result.scalars().first()

    async def run(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            pipeline_run = PipelineRun(status=PipelineRunStatus.STARTED)
            session.add(pipeline_run)
            await session.flush()
            stats: dict[str, Any] = {
                "watchlist_sync": {},
                "contexts": 0,
                "signals_created": 0,
                "evidence_created": 0,
                "opportunities_evaluated": 0,
                "qualified_opportunities": 0,
                "sheets_exports": 0,
            }

            try:
                stats["watchlist_sync"] = await self._sync_watchlist_if_present(session)
                contexts = await self._load_contexts(session)
                stats["contexts"] = len(contexts)
                if not contexts:
                    logger.warning("Radar pipeline has no active company/program contexts to evaluate.")

                semaphore = asyncio.Semaphore(self.settings.max_connector_concurrency)
                timeout = httpx.Timeout(self.settings.request_timeout_seconds)
                headers = {"User-Agent": self.settings.user_agent}
                async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
                    for company, program, context in contexts:
                        collected_signals = await self._collect_for_context(context, client, semaphore)
                        created, evidence_created = await self._upsert_signals(session, company, program, context, collected_signals)
                        stats["signals_created"] += created
                        stats["evidence_created"] += evidence_created

                    await session.flush()

                    for company, program, context in contexts:
                        opportunity = await self._evaluate_program(session, company, program, context)
                        stats["opportunities_evaluated"] += 1
                        if opportunity.radar_score >= self.settings.min_score_for_dossier:
                            stats["qualified_opportunities"] += 1
                        if opportunity.last_exported_to_sheet_at is not None:
                            stats["sheets_exports"] += 1

                pipeline_run.status = PipelineRunStatus.SUCCESS
                pipeline_run.ended_at = utcnow()
                pipeline_run.stats = stats
                await session.commit()
                stats["pipeline_run_id"] = pipeline_run.id
                return stats
            except Exception as exc:
                logger.exception("Radar pipeline failed")
                await session.rollback()
                async with self.session_factory() as failure_session:
                    failure_run = await failure_session.get(PipelineRun, pipeline_run.id)
                    if failure_run is not None:
                        failure_run.status = PipelineRunStatus.FAILED
                        failure_run.ended_at = utcnow()
                        failure_run.error_message = str(exc)
                        failure_run.stats = stats
                        await failure_session.commit()
                raise
