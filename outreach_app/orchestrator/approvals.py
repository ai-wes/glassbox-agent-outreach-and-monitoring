from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.approval import Approval
from app.models.run import Run
from app.orchestrator.workflow import WorkflowEngine, ApprovalChallenge
from app.tools.registry import ToolRegistry
from app.utils.crypto import sha256_hex


class ApprovalService:
    def __init__(self, tools: ToolRegistry):
        self.workflow = WorkflowEngine(tools)

    def approve(
        self,
        *,
        db: Session,
        run: Run,
        token: str,
        approved_by: str,
        notes: str | None,
        dry_run: bool,
    ) -> tuple[Run, ApprovalChallenge | None]:
        token_hash = sha256_hex(token.encode("utf-8"))
        approval = db.query(Approval).filter(Approval.run_id == run.id, Approval.status == "pending", Approval.token_sha256 == token_hash).first()
        if not approval:
            raise PermissionError("Invalid approval token.")
        if approval.expires_at < datetime.utcnow():
            approval.status = "expired"
            approval.decision_at = datetime.utcnow()
            db.add(approval)
            db.flush()
            raise PermissionError("Approval token expired.")

        approval.status = "approved"
        approval.approved_by = approved_by
        approval.decision_at = datetime.utcnow()
        approval.notes = notes
        db.add(approval)
        db.flush()

        challenge = self.workflow.execute(db=db, run=run, task_payload=run.task.payload_json, requested_by=approved_by, dry_run=dry_run)
        db.add(run)
        db.flush()
        return run, challenge
