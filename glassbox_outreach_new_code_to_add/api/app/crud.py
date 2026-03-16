"""CRUD operations for interacting with the database.

This module centralises all create, read, update and delete logic for
SQLAlchemy models.  Exposing a clear interface here helps maintain a
separation between database access and business logic in services and
tasks.  All functions are asynchronous and expect an active
``AsyncSession`` instance which can be provided by FastAPI's
dependency injection via ``get_async_session``.

Functions defined here perform common operations such as:

* creating or retrieving companies, contacts and leads
* updating lead and job statuses
* adding evidence records
* counting records for reporting

Errors are propagated to callers so they can handle them at the
appropriate layer.  None of these functions commit the session;
callers should control the transaction boundaries.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Company, Contact, Lead, Evidence, Job, LeadStatus, JobStatus, JobType


async def get_company_by_domain(session: AsyncSession, domain: str) -> Optional[Company]:
    """Retrieve a company by its domain name.

    Args:
        session: Active database session.
        domain: The company's domain.

    Returns:
        A ``Company`` instance or ``None`` if no company exists with the
        given domain.
    """
    if not domain:
        return None
    result = await session.execute(select(Company).where(Company.domain == domain.lower()))
    return result.scalar_one_or_none()


async def create_company(session: AsyncSession, name: str, domain: Optional[str] = None, **kwargs) -> Company:
    """Create a new company record.

    If a domain is provided, the domain is normalised to lowercase
    before insertion.  Additional keyword arguments allow callers to
    specify optional fields such as ``website``, ``headcount`` or
    ``industry``.  The caller is responsible for committing the
    transaction.

    Args:
        session: Active database session.
        name: Company name.
        domain: Optional domain for the company.
        **kwargs: Optional additional fields for the company.

    Returns:
        The newly created ``Company`` instance.
    """
    company = Company(name=name, domain=domain.lower() if domain else None, **kwargs)
    session.add(company)
    await session.flush()
    return company


async def get_or_create_company(session: AsyncSession, name: str, domain: Optional[str] = None, **kwargs) -> Company:
    """Retrieve a company by domain or create it if it does not exist.

    This helper avoids duplicate company records by first looking up
    the domain.  If the domain is not provided or no existing company
    is found, a new company is created.  Additional fields passed in
    ``kwargs`` are used only when creating a new record.

    Args:
        session: Active database session.
        name: Company name.
        domain: Optional company domain.
        **kwargs: Additional fields for company creation.

    Returns:
        A ``Company`` instance, either existing or newly created.
    """
    if domain:
        existing = await get_company_by_domain(session, domain)
        if existing:
            return existing
    return await create_company(session, name=name, domain=domain, **kwargs)


async def get_contact_by_email(session: AsyncSession, email: str) -> Optional[Contact]:
    """Retrieve a contact by email address.

    Email addresses are treated case-insensitively by lowercasing
    them before comparison.
    """
    result = await session.execute(select(Contact).where(Contact.email == email.lower()))
    return result.scalar_one_or_none()


async def create_contact(
    session: AsyncSession,
    company: Company,
    full_name: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    title: Optional[str] = None,
    email: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    seniority: Optional[str] = None,
    function: Optional[str] = None,
    inferred_buying_role: Optional[str] = None,
) -> Contact:
    """Create a contact associated with the given company.

    If an email is provided, it is normalised to lowercase.  No
    duplicate check is performed here; callers should use
    ``get_contact_by_email`` first if deduplication is desired.

    Returns:
        The newly created ``Contact`` instance.
    """
    contact = Contact(
        company_id=company.id,
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        title=title,
        email=email.lower() if email else None,
        linkedin_url=linkedin_url,
        seniority=seniority,
        function=function,
        inferred_buying_role=inferred_buying_role,
    )
    session.add(contact)
    await session.flush()
    return contact


async def create_lead(
    session: AsyncSession,
    company: Company,
    contact: Optional[Contact] = None,
    status: LeadStatus = LeadStatus.NEW,
    fit_score: Optional[int] = None,
    email_confidence: Optional[int] = None,
    icp_class: Optional[str] = None,
    persona_class: Optional[str] = None,
    recommended_sequence: Optional[str] = None,
    recommended_offer: Optional[str] = None,
    why_now: Optional[str] = None,
) -> Lead:
    """Create a new lead linking a company and optional contact.

    The caller may supply initial scoring and classification values.
    """
    lead = Lead(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        status=status,
        fit_score=fit_score,
        email_confidence=email_confidence,
        icp_class=icp_class,
        persona_class=persona_class,
        recommended_sequence=recommended_sequence,
        recommended_offer=recommended_offer,
        why_now=why_now,
    )
    session.add(lead)
    await session.flush()
    return lead


async def update_lead_status(session: AsyncSession, lead_id: uuid.UUID, status: LeadStatus) -> None:
    """Update the status of a lead.

    Args:
        session: Active database session.
        lead_id: Primary key of the lead to update.
        status: New ``LeadStatus`` value.
    """
    await session.execute(
        update(Lead).
        where(Lead.id == lead_id).
        values(status=status, updated_at=Lead.updated_at.property.default.arg())
    )


async def create_evidence(
    session: AsyncSession,
    entity_type: str,
    entity_id: uuid.UUID,
    source_url: str,
    selector: Optional[str] = None,
    extracted_value: Optional[str] = None,
    screenshot_path: Optional[str] = None,
) -> Evidence:
    """Create a new evidence record.

    Records the provenance of a data point used to populate company,
    contact or lead fields.
    """
    ev = Evidence(
        entity_type=entity_type,
        entity_id=entity_id,
        source_url=source_url,
        selector=selector,
        extracted_value=extracted_value,
        screenshot_path=screenshot_path,
    )
    session.add(ev)
    await session.flush()
    return ev


async def create_job(session: AsyncSession, job_type: JobType) -> Job:
    """Create a new background job record.

    The job starts in ``PENDING`` state and will be updated by the
    Celery tasks as it progresses.
    """
    job = Job(job_type=job_type, status=JobStatus.PENDING)
    session.add(job)
    await session.flush()
    return job


async def update_job_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    status: JobStatus,
    row_count: Optional[int] = None,
    success_count: Optional[int] = None,
    failure_count: Optional[int] = None,
) -> None:
    """Update the status and counts of a job.

    Partial updates are allowed; only provided arguments will be set on
    the record.  Timestamps for `started_at` and `finished_at` are
    automatically updated when moving to RUNNING or COMPLETED states.
    """
    values: dict[str, object] = {"status": status}
    if row_count is not None:
        values["row_count"] = row_count
    if success_count is not None:
        values["success_count"] = success_count
    if failure_count is not None:
        values["failure_count"] = failure_count
    if status == JobStatus.RUNNING:
        values["started_at"] = Job.started_at.property.default.arg()
    if status == JobStatus.COMPLETED or status == JobStatus.FAILED:
        values["finished_at"] = Job.finished_at.property.default.arg()
    await session.execute(
        update(Job).
        where(Job.id == job_id).
        values(**values)
    )


async def get_leads_by_status(session: AsyncSession, status: LeadStatus, limit: int = 100) -> list[Lead]:
    """Retrieve a batch of leads filtered by their status.

    Args:
        session: Active database session.
        status: The lead status to filter by.
        limit: Maximum number of leads to return.

    Returns:
        A list of ``Lead`` objects.
    """
    result = await session.execute(
        select(Lead).where(Lead.status == status).limit(limit)
    )
    return list(result.scalars().all())
