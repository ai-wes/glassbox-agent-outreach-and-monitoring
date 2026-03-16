"""FastAPI entry point for the outreach service.

This module creates the FastAPI app, registers API routes and
initialises database tables on startup.  Routes are grouped by
resource under a common ``/api`` prefix.  Celery tasks are triggered
via POST endpoints and run asynchronously in the worker.
"""

from __future__ import annotations

import asyncio
from typing import List

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.ext.asyncio import AsyncSession

from .database import Base, engine, get_async_session
from . import crud
from .models import LeadStatus, Lead
from .celery_app import celery_app

app = FastAPI(title="Glassbox Outreach Service", version="0.1.0")


# Allow all origins for simplicity; restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    """Create database tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/api/leads", response_model=List[dict])
async def list_leads(
    status: LeadStatus | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_async_session),
) -> List[dict]:
    """Retrieve leads optionally filtered by status.

    Args:
        status: Optional status to filter by.
        limit: Maximum number of leads to return.
    Returns:
        A list of dictionaries representing leads.
    """
    query = select(Lead)
    if status:
        query = query.where(Lead.status == status)
    query = query.limit(limit)
    result = await session.execute(query)
    leads = result.scalars().all()
    # Build simple serialisable dicts
    return [
        {
            "id": str(lead.id),
            "company": lead.company.name,
            "contact": lead.contact.full_name if lead.contact else None,
            "email": lead.contact.email if lead.contact else None,
            "status": lead.status.value,
            "fit_score": lead.fit_score,
            "email_confidence": lead.email_confidence,
        }
        for lead in leads
    ]


@app.post("/api/discovery")
async def trigger_discovery(domains: List[str]) -> dict:
    """Trigger a discovery job for the provided domains.

    The list of domains should contain bare domains without protocol.
    Returns a job acknowledgement.
    """
    if not domains:
        raise HTTPException(status_code=400, detail="Domains list cannot be empty")
    # Fire off Celery task
    celery_app.send_task("tasks.discovery_from_domains", args=[domains])
    return {"status": "queued", "task": "discovery", "domains": domains}


@app.post("/api/enrich")
async def trigger_enrichment() -> dict:
    """Trigger an enrichment job for discovered leads."""
    celery_app.send_task("tasks.enrich_leads")
    return {"status": "queued", "task": "enrichment"}


@app.post("/api/verify")
async def trigger_verification() -> dict:
    """Trigger a verification job for enriched leads."""
    celery_app.send_task("tasks.verify_leads")
    return {"status": "queued", "task": "verification"}


@app.post("/api/score")
async def trigger_scoring() -> dict:
    """Trigger a scoring job for verified leads."""
    celery_app.send_task("tasks.score_leads")
    return {"status": "queued", "task": "scoring"}


@app.post("/api/sync")
async def trigger_sync() -> dict:
    """Trigger a sync of leads to Google Sheets."""
    celery_app.send_task("tasks.sync_leads_to_sheet")
    return {"status": "queued", "task": "sync"}
