from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db.session import db_session
from app.models.task import Task
from app.models.run import Run
from app.models.artifact import Artifact
from app.orchestrator.planner import Planner
from app.orchestrator.service import Orchestrator
from app.orchestrator.approvals import ApprovalService
from app.schemas.task import TaskCreate, TaskOut
from app.schemas.run import RunStart, RunOut, ApprovalRequestOut, ApprovalSubmit, EvidencePackOut
from app.tools.factory import build_registry
from app.utils.id import new_id

router = APIRouter()

_tools = build_registry()
_planner = Planner(_tools)
_orchestrator = Orchestrator(_tools, _planner)
_approval_service = ApprovalService(_tools)


@router.post("/tasks", response_model=TaskOut, tags=["tasks"])
def create_task(payload: TaskCreate):
    with db_session() as db:
        t = Task(
            id=new_id("TSK"),
            title=payload.title,
            domain=payload.domain,
            priority=payload.priority,
            owner_agent=payload.owner_agent,
            status="queued",
            due_at=payload.due_at,
            payload_json=payload.payload_json,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(t)
        db.flush()
        return t


@router.get("/tasks", response_model=list[TaskOut], tags=["tasks"])
def list_tasks(limit: int = 50, offset: int = 0):
    with db_session() as db:
        rows = db.query(Task).order_by(Task.priority.asc(), Task.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0)).all()
        return rows


@router.get("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def get_task(task_id: str):
    with db_session() as db:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            raise HTTPException(404, "Task not found")
        return t


@router.post("/tasks/{task_id}/run", response_model=RunOut | ApprovalRequestOut, tags=["runs"])
def run_task(task_id: str, payload: RunStart):
    with db_session() as db:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            raise HTTPException(404, "Task not found")

        run, challenge = _orchestrator.start_run(db=db, task=t, requested_by=payload.requested_by, force_agent=payload.force_agent, dry_run=payload.dry_run)
        if challenge is not None:
            return ApprovalRequestOut(run_id=run.id, approval_id=challenge.approval.id, scope=challenge.approval.scope, expires_at=challenge.approval.expires_at, token=challenge.token, reason=challenge.reason)
        return run


@router.get("/runs", response_model=list[RunOut], tags=["runs"])
def list_runs(limit: int = 50, offset: int = 0):
    with db_session() as db:
        rows = db.query(Run).order_by(Run.created_at.desc()).limit(min(limit, 200)).offset(max(offset, 0)).all()
        return rows


@router.get("/runs/{run_id}", response_model=RunOut, tags=["runs"])
def get_run(run_id: str):
    with db_session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            raise HTTPException(404, "Run not found")
        return r


@router.post("/runs/{run_id}/approve", response_model=RunOut | ApprovalRequestOut, tags=["runs"])
def approve_run(run_id: str, payload: ApprovalSubmit, dry_run: bool = False):
    with db_session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            raise HTTPException(404, "Run not found")

        try:
            updated, challenge = _approval_service.approve(db=db, run=r, token=payload.token, approved_by=payload.approved_by, notes=payload.notes, dry_run=dry_run)
        except PermissionError as e:
            raise HTTPException(403, str(e))

        if challenge is not None:
            return ApprovalRequestOut(run_id=updated.id, approval_id=challenge.approval.id, scope=challenge.approval.scope, expires_at=challenge.approval.expires_at, token=challenge.token, reason=challenge.reason)
        return updated


@router.get("/runs/{run_id}/evidence", response_model=EvidencePackOut, tags=["evidence"])
def get_evidence(run_id: str):
    with db_session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            raise HTTPException(404, "Run not found")
        if not r.evidence_uri:
            raise HTTPException(404, "No evidence pack for this run yet")
        artifacts = db.query(Artifact).filter(Artifact.run_id == run_id).all()
        return EvidencePackOut(run_id=run_id, evidence_uri=r.evidence_uri, artifacts=[{"id": a.id, "type": a.type, "uri": a.uri, "sha256": a.sha256, "metadata": a.metadata_json} for a in artifacts])


@router.get("/runs/{run_id}/evidence/download", tags=["evidence"])
def download_evidence(run_id: str):
    with db_session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            raise HTTPException(404, "Run not found")
        if not r.evidence_uri:
            raise HTTPException(404, "No evidence pack for this run yet")
        root = Path(r.evidence_uri)
        if not root.exists() or not root.is_dir():
            raise HTTPException(404, "Evidence pack directory missing")

        import tempfile
        import zipfile

        tmpdir = Path(tempfile.gettempdir())
        zip_path = tmpdir / f"evidence_{run_id}.zip"
        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in root.rglob("*"):
                if p.is_file():
                    z.write(p, arcname=str(p.relative_to(root)))

        return FileResponse(path=str(zip_path), filename=f"evidence_{run_id}.zip", media_type="application/zip")
