from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.auth import require_api_key
from app.db.session import db_session
from app.integrations.google_sheets import SheetsConfigurationError, SheetsRequestError
from app.models.artifact import Artifact
from app.models.run import Run
from outreach_app.gtm_service.api.routes import _lead_read, _reply_read
from outreach_app.gtm_service.db.models import Company as GtmCompany
from outreach_app.gtm_service.db.models import Lead as GtmLead
from outreach_app.gtm_service.db.models import OutreachMessage as GtmOutreachMessage
from outreach_app.gtm_service.db.models import ReplyEvent as GtmReplyEvent
from outreach_app.gtm_service.db.session import AsyncSessionLocal
from outreach_app.gtm_service.schemas.lead import CandidateIngestRequest, LeadRead, PipelineResult, ReplyEventRead
from outreach_app.gtm_service.schemas.telemetry import (
    AttributionPerformanceRead,
    FunnelMetricsRead,
    LeadTelemetryRead,
    MetricsDashboardRead,
    SequencePerformanceRead,
    StepPerformanceRead,
)
from app.models.task import Task
from app.orchestrator.planner import Planner
from app.orchestrator.service import Orchestrator
from app.schemas.agent import AgentToolCallRequest, AgentExecuteRequest, AgentExecutionResponse, ToolSpec
from app.schemas.run import ApprovalRequestOut, RunOut
from app.schemas.task import TaskOut
from app.tools.factory import build_registry
from app.utils.id import new_id

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_api_key)])

_tools = build_registry()
_planner = Planner(_tools)
_orchestrator = Orchestrator(_tools, _planner)


@router.get("/tools", response_model=list[ToolSpec])
def list_tools():
    return [ToolSpec(**spec) for spec in _tools.specs()]


@router.post("/tool_call", response_model=AgentExecutionResponse)
def tool_call(req: AgentToolCallRequest):
    title = req.title or f"Agent tool call: {req.tool}"
    steps = [{"id": "tool_call", "name": title, "tool": req.tool, "args": req.args}]
    with db_session() as db:
        t = Task(
            id=new_id("TSK"),
            title=title,
            domain=req.domain,
            priority=req.priority,
            owner_agent="router",
            status="queued",
            due_at=None,
            payload_json={"steps": steps},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(t)
        db.flush()
        try:
            run, challenge = _orchestrator.start_run(db=db, task=t, requested_by=req.requested_by, force_agent=None, dry_run=req.dry_run)
        except SheetsConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SheetsRequestError as exc:
            status_code = exc.status_code if exc.status_code < 500 else 502
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        if challenge is not None:
            return AgentExecutionResponse(
                task=TaskOut.model_validate(t),
                run=None,
                approval=ApprovalRequestOut(run_id=run.id, approval_id=challenge.approval.id, scope=challenge.approval.scope, expires_at=challenge.approval.expires_at, token=challenge.token, reason=challenge.reason),
            )
        return AgentExecutionResponse(task=TaskOut.model_validate(t), run=RunOut.model_validate(run), approval=None)


@router.post("/execute", response_model=AgentExecutionResponse)
def execute(req: AgentExecuteRequest):
    with db_session() as db:
        t = Task(
            id=new_id("TSK"),
            title=req.title,
            domain=req.domain,
            priority=req.priority,
            owner_agent="router",
            status="queued",
            due_at=None,
            payload_json={"steps": req.steps},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(t)
        db.flush()
        try:
            run, challenge = _orchestrator.start_run(db=db, task=t, requested_by=req.requested_by, force_agent=None, dry_run=req.dry_run)
        except SheetsConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SheetsRequestError as exc:
            status_code = exc.status_code if exc.status_code < 500 else 502
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        if challenge is not None:
            return AgentExecutionResponse(
                task=TaskOut.model_validate(t),
                run=None,
                approval=ApprovalRequestOut(run_id=run.id, approval_id=challenge.approval.id, scope=challenge.approval.scope, expires_at=challenge.approval.expires_at, token=challenge.token, reason=challenge.reason),
            )
        return AgentExecutionResponse(task=TaskOut.model_validate(t), run=RunOut.model_validate(run), approval=None)


@router.get("/crm/leads", response_model=list[LeadRead])
async def list_crm_leads(limit: int = Query(default=50, ge=1, le=200)):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(GtmLead)
            .order_by(GtmLead.updated_at.desc())
            .limit(limit)
            .options(
                selectinload(GtmLead.company).selectinload(GtmCompany.signals),
                selectinload(GtmLead.contact),
                selectinload(GtmLead.scores),
            )
        )
        leads = list((await session.execute(stmt)).scalars().unique().all())
    return [_lead_read(lead) for lead in leads]


@router.get("/crm/leads/{lead_id}", response_model=LeadRead)
async def get_crm_lead(lead_id: str):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(GtmLead)
            .where(GtmLead.id == lead_id)
            .options(
                selectinload(GtmLead.company).selectinload(GtmCompany.signals),
                selectinload(GtmLead.contact),
                selectinload(GtmLead.scores),
            )
        )
        lead = (await session.execute(stmt)).scalars().unique().one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    return _lead_read(lead)


@router.get("/crm/replies", response_model=list[ReplyEventRead])
async def list_crm_replies(limit: int = Query(default=100, ge=1, le=500)):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(GtmReplyEvent)
            .order_by(GtmReplyEvent.created_at.desc())
            .limit(limit)
            .options(
                selectinload(GtmReplyEvent.lead).selectinload(GtmLead.company),
                selectinload(GtmReplyEvent.lead).selectinload(GtmLead.contact),
                selectinload(GtmReplyEvent.outreach_message).selectinload(GtmOutreachMessage.sequence),
            )
        )
        replies = list((await session.execute(stmt)).scalars().all())
    return [_reply_read(reply) for reply in replies]


@router.post("/crm/pipeline/ingest", response_model=PipelineResult)
async def agent_ingest_crm_pipeline(payload: CandidateIngestRequest, request: Request):
    async with AsyncSessionLocal() as session:
        from outreach_app.gtm_service.services.orchestrator import PipelineOrchestrator

        container = request.app.state.gtm_container
        orchestrator = PipelineOrchestrator(
            settings=container.settings,
            session=session,
            source_service=container.source_service,
            research_agent=container.research_agent,
            scoring_service=container.scoring_service,
            router=container.router,
            sequence_service=container.sequence_service,
            crm_sync_service=container.crm_sync_service,
        )
        return await orchestrator.ingest_candidate(payload)


@router.post("/crm/sequences/run-due")
async def agent_run_crm_due_messages(request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.sequence_service.run_due_messages(session)


@router.get("/crm/metrics/summary")
async def agent_crm_metrics_summary(request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.summary(session)


@router.get("/crm/metrics/sequences", response_model=list[SequencePerformanceRead])
async def agent_crm_metrics_sequences(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.sequence_performance(session, limit=limit)


@router.get("/crm/metrics/steps", response_model=list[StepPerformanceRead])
async def agent_crm_metrics_steps(request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.step_performance(session)


@router.get("/crm/metrics/attribution", response_model=list[AttributionPerformanceRead])
async def agent_crm_metrics_attribution(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.attribution_breakdown(session, limit=limit)


@router.get("/crm/metrics/funnel", response_model=FunnelMetricsRead)
async def agent_crm_metrics_funnel(request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.funnel(session)


@router.get("/crm/metrics/dashboard", response_model=MetricsDashboardRead)
async def agent_crm_metrics_dashboard(request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        return await container.metrics_service.dashboard(session)


@router.get("/crm/leads/{lead_id}/telemetry", response_model=LeadTelemetryRead)
async def agent_crm_lead_telemetry(lead_id: str, request: Request):
    container = request.app.state.gtm_container
    async with AsyncSessionLocal() as session:
        telemetry = await container.metrics_service.lead_telemetry(session, lead_id)
    if telemetry is None:
        raise HTTPException(status_code=404, detail="lead not found")
    return telemetry


@router.get("/reports/runs")
def list_agent_run_reports(limit: int = Query(default=25, ge=1, le=200)):
    with db_session() as db:
        rows = (
            db.query(Run, Task)
            .join(Task, Task.id == Run.task_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .all()
        )
        run_ids = [run.id for run, _task in rows]
        artifact_counts = {}
        if run_ids:
            artifact_counts = {
                run_id: count
                for run_id, count in (
                    db.query(Artifact.run_id, func.count(Artifact.id))
                    .filter(Artifact.run_id.in_(run_ids))
                    .group_by(Artifact.run_id)
                    .all()
                )
            }

    return [
        {
            "run_id": run.id,
            "task_id": task.id,
            "title": task.title,
            "agent": run.agent,
            "status": run.status,
            "summary": run.summary,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "evidence_uri": run.evidence_uri,
            "artifact_count": int(artifact_counts.get(run.id, 0)),
        }
        for run, task in rows
    ]


@router.get("/reports/runs/{run_id}")
def get_agent_run_report(run_id: str):
    with db_session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        task = db.query(Task).filter(Task.id == run.task_id).first()
        artifacts = db.query(Artifact).filter(Artifact.run_id == run_id).order_by(Artifact.created_at.asc()).all()

    root = Path(run.evidence_uri) if run.evidence_uri else None
    manifest = None
    evidence_index = None
    tool_calls: list[dict] = []
    if root and root.exists() and root.is_dir():
        manifest_path = root / "run_manifest.json"
        evidence_index_path = root / "evidence_index.json"
        tool_calls_path = root / "tool_calls.jsonl"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if evidence_index_path.exists():
            evidence_index = json.loads(evidence_index_path.read_text(encoding="utf-8"))
        if tool_calls_path.exists():
            tool_calls = [
                json.loads(line)
                for line in tool_calls_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    return {
        "run": RunOut.model_validate(run).model_dump(),
        "task": TaskOut.model_validate(task).model_dump() if task is not None else None,
        "manifest": manifest,
        "evidence_index": evidence_index,
        "tool_calls": tool_calls,
        "artifacts": [
            {
                "id": artifact.id,
                "type": artifact.type,
                "uri": artifact.uri,
                "sha256": artifact.sha256,
                "metadata": artifact.metadata_json,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            }
            for artifact in artifacts
        ],
    }


@router.get("/reports/runs/{run_id}/download")
def download_agent_run_report(run_id: str):
    with db_session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if not run.evidence_uri:
            raise HTTPException(status_code=404, detail="no evidence pack for this run")
        root = Path(run.evidence_uri)
        if not root.exists() or not root.is_dir():
            raise HTTPException(status_code=404, detail="evidence pack directory missing")

    import tempfile
    import zipfile

    tmpdir = Path(tempfile.gettempdir())
    zip_path = tmpdir / f"agent_report_{run_id}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(root)))

    return FileResponse(
        path=str(zip_path),
        filename=f"agent_report_{run_id}.zip",
        media_type="application/zip",
    )
