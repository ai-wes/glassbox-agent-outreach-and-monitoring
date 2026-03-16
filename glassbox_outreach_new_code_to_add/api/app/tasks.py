"""Background tasks orchestrated by Celery.

Each task in this module runs asynchronously within a Celery worker
process.  Tasks interact with the database through the CRUD layer
and call out to the scraper and Google Sheets utilities where
appropriate.  Jobs are recorded in the ``jobs`` table to track
progress, counts and status.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from .celery_app import celery_app
from .database import async_session_factory
from . import crud
from .models import LeadStatus, JobStatus, JobType
from . import scraper
from . import google_sheets


logger = logging.getLogger(__name__)


async def _get_session() -> AsyncSession:
    """Helper to obtain an async session outside of FastAPI context."""
    return async_session_factory()


@celery_app.task(name="tasks.discovery_from_domains")
def discovery_from_domains(domains: List[str]) -> None:
    """Discover companies and create initial leads from a list of domains.

    This synchronous Celery task delegates to an inner async function to
    handle database and scraping operations.  It creates a single job
    record and updates it as progress is made.

    Args:
        domains: List of company domain strings (without protocol).
    """
    asyncio.run(_discovery(domains))


async def _discovery(domains: List[str]) -> None:
    async with async_session_factory() as session:
        # Create job record
        job = await crud.create_job(session, JobType.DISCOVERY)
        await session.commit()
        job_id = job.id
        logger.info("Started discovery job %s with %d domains", job_id, len(domains))
        await crud.update_job_status(session, job_id, JobStatus.RUNNING)
        await session.commit()
        success_count = 0
        for domain in domains:
            try:
                info = await scraper.scrape_company(domain)
                company = await crud.get_or_create_company(
                    session,
                    name=info.get("name") or domain,
                    domain=domain,
                    website=info.get("website"),
                    industry=None,
                )
                # Create a new lead in DISCOVERED state
                await crud.create_lead(session, company=company, status=LeadStatus.DISCOVERED)
                await session.flush()
                # Evidence for company name / description
                if info.get("description"):
                    await crud.create_evidence(
                        session,
                        entity_type="company",
                        entity_id=company.id,
                        source_url=info.get("website") or f"https://{domain}",
                        selector="meta[name=description]",
                        extracted_value=info.get("description"),
                    )
                success_count += 1
            except Exception as exc:
                logger.exception("Failed to discover domain %s: %s", domain, exc)
                # Continue with other domains without raising
        # Update job as completed
        failure_count = len(domains) - success_count
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.COMPLETED,
            row_count=len(domains),
            success_count=success_count,
            failure_count=failure_count,
        )
        await session.commit()
        logger.info("Discovery job %s completed: %d successes, %d failures", job_id, success_count, failure_count)


@celery_app.task(name="tasks.enrich_leads")
def enrich_leads() -> None:
    """Enrich leads by discovering contacts and updating records.

    Fetches leads in DISCOVERED state, scrapes their company domains
    for contact emails, and creates contact/lead associations.
    """
    asyncio.run(_enrich())


async def _enrich() -> None:
    async with async_session_factory() as session:
        job = await crud.create_job(session, JobType.ENRICHMENT)
        await session.commit()
        job_id = job.id
        await crud.update_job_status(session, job_id, JobStatus.RUNNING)
        await session.commit()
        leads = await crud.get_leads_by_status(session, LeadStatus.DISCOVERED, limit=100)
        success_count = 0
        for lead in leads:
            try:
                company = lead.company
                domain = company.domain
                if not domain:
                    logger.warning("Lead %s has no company domain; skipping", lead.id)
                    continue
                contacts = await scraper.discover_contacts(domain)
                if not contacts:
                    # mark as enriched with no contacts
                    await crud.update_lead_status(session, lead.id, LeadStatus.ENRICHED)
                    await session.flush()
                    continue
                for contact_data in contacts:
                    email = contact_data.get("email")
                    if not email:
                        continue
                    # Create or retrieve contact by email
                    existing = await crud.get_contact_by_email(session, email)
                    if existing:
                        contact = existing
                    else:
                        contact = await crud.create_contact(
                            session,
                            company=company,
                            full_name=contact_data.get("full_name"),
                            first_name=contact_data.get("first_name"),
                            last_name=contact_data.get("last_name"),
                            title=None,
                            email=email,
                        )
                    # Update lead with contact and mark as ENRICHED
                    await crud.update_lead_status(session, lead.id, LeadStatus.ENRICHED)
                    lead.contact_id = contact.id
                    success_count += 1
                    await session.flush()
            except Exception as exc:
                logger.exception("Failed to enrich lead %s: %s", lead.id, exc)
        # Complete job
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.COMPLETED,
            row_count=len(leads),
            success_count=success_count,
            failure_count=(len(leads) - success_count),
        )
        await session.commit()
        logger.info("Enrichment job %s completed", job_id)


@celery_app.task(name="tasks.verify_leads")
def verify_leads() -> None:
    """Verify email addresses for leads in ENRICHED state.

    Performs syntax and MX checks on the contact's email and updates
    lead status accordingly.
    """
    asyncio.run(_verify())


async def _verify() -> None:
    async with async_session_factory() as session:
        job = await crud.create_job(session, JobType.VERIFICATION)
        await session.commit()
        job_id = job.id
        await crud.update_job_status(session, job_id, JobStatus.RUNNING)
        await session.commit()
        leads = await crud.get_leads_by_status(session, LeadStatus.ENRICHED, limit=100)
        success_count = 0
        for lead in leads:
            try:
                contact = lead.contact
                email = contact.email if contact else None
                if not email:
                    logger.warning("Lead %s has no email for verification", lead.id)
                    await crud.update_lead_status(session, lead.id, LeadStatus.FAILED)
                    await session.flush()
                    continue
                # verify using local checks
                valid = scraper.verify_email_locally(email)
                contact.email_verified = valid
                lead.email_confidence = 100 if valid else 0
                # update lead status
                await crud.update_lead_status(
                    session,
                    lead.id,
                    LeadStatus.VERIFIED if valid else LeadStatus.FAILED,
                )
                await session.flush()
                if valid:
                    success_count += 1
            except Exception as exc:
                logger.exception("Verification error for lead %s: %s", lead.id, exc)
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.COMPLETED,
            row_count=len(leads),
            success_count=success_count,
            failure_count=(len(leads) - success_count),
        )
        await session.commit()
        logger.info("Verification job %s completed", job_id)


@celery_app.task(name="tasks.score_leads")
def score_leads() -> None:
    """Score leads and move them to READY_FOR_REVIEW.

    A deterministic scoring formula evaluates fit, email confidence and
    other heuristics to prioritise leads.  Scores are stored on the
    lead record for later use in sequencing.
    """
    asyncio.run(_score())


async def _score() -> None:
    async with async_session_factory() as session:
        job = await crud.create_job(session, JobType.SCORING)
        await session.commit()
        job_id = job.id
        await crud.update_job_status(session, job_id, JobStatus.RUNNING)
        await session.commit()
        leads = await crud.get_leads_by_status(session, LeadStatus.VERIFIED, limit=100)
        success_count = 0
        for lead in leads:
            try:
                # simple scoring formula: base on email confidence and placeholder
                fit_score = (lead.email_confidence or 0) * 0.5 + 50  # base 50 points + email weight
                lead.fit_score = int(fit_score)
                await crud.update_lead_status(session, lead.id, LeadStatus.READY_FOR_REVIEW)
                await session.flush()
                success_count += 1
            except Exception as exc:
                logger.exception("Scoring error for lead %s: %s", lead.id, exc)
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.COMPLETED,
            row_count=len(leads),
            success_count=success_count,
            failure_count=(len(leads) - success_count),
        )
        await session.commit()
        logger.info("Scoring job %s completed", job_id)


@celery_app.task(name="tasks.sync_leads_to_sheet")
def sync_leads_to_sheet() -> None:
    """Export leads to the configured Google Sheet.

    All leads are fetched and appended to the ``Leads`` sheet.  A
    clear-range operation ensures idempotence across runs.
    """
    asyncio.run(_sync_leads_to_sheet())


async def _sync_leads_to_sheet() -> None:
    async with async_session_factory() as session:
        # For simplicity, select all leads
        from .models import Lead  # import locally to avoid circular import
        result = await session.execute(select(Lead))
        leads = result.scalars().all()
        # Prepare rows for Sheets
        rows = []
        for lead in leads:
            company = lead.company
            contact = lead.contact
            rows.append([
                str(lead.id),
                company.name,
                company.domain or "",
                contact.full_name if contact else "",
                contact.email if contact else "",
                lead.status.value,
                lead.fit_score if lead.fit_score is not None else "",
                lead.email_confidence if lead.email_confidence is not None else "",
                lead.why_now or "",
            ])
        # Clear and update the sheet
        sheet_range = "Leads!A2:I"
        google_sheets.clear_range(sheet_range)
        if rows:
            google_sheets.append_rows(sheet_range, rows)
        logger.info("Synced %d leads to Google Sheets", len(rows))
