from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.approval import Approval
from app.models.artifact import Artifact
from app.models.event import Event
from app.models.run import Run
from app.orchestrator.evidence import EvidencePack, ToolCallRecord
from app.orchestrator.policy import PolicyEngine
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry
from app.utils.crypto import sha256_hex
from app.utils.id import new_id

logger = logging.getLogger(__name__)


@dataclass
class ApprovalChallenge:
    approval: Approval
    token: str
    reason: str


class WorkflowEngine:
    def __init__(self, tools: ToolRegistry):
        self.tools = tools
        self.policy = PolicyEngine()

    def execute(
        self,
        *,
        db: Session,
        run: Run,
        task_payload: dict,
        requested_by: str,
        dry_run: bool,
    ) -> ApprovalChallenge | None:
        evidence = EvidencePack(run.id)

        run.started_at = run.started_at or datetime.utcnow()
        run.status = "running"
        run.evidence_uri = evidence.uri
        db.add(run)
        db.flush()

        steps = run.plan_json.get("steps", []) or []
        run.max_risk_tier = self.policy.max_risk(steps)

        scratch: dict[str, Any] = {"task_payload": task_payload}
        external_actions = 0

        for step in steps:
            step_id = step["id"]
            completed = run.plan_json.get("_completed_steps", []) or []
            if step_id in completed:
                continue

            tool = self.tools.get(step["tool"])
            risk_tier = int(step.get("risk_tier", getattr(tool, "risk_tier", 0)))
            external_effect = bool(step.get("external_effect", False))

            decision = self.policy.evaluate_step(risk_tier, external_effect, dry_run=dry_run)
            if not decision.allowed:
                self._log_event(db, run.id, "policy_block", {"step_id": step_id, "reason": decision.reason})
                run.status = "blocked"
                run.finished_at = datetime.utcnow()
                run.summary = f"Blocked by policy at step {step_id}: {decision.reason}"
                evidence.write_manifest({"status": run.status, "summary": run.summary})
                db.add(run)
                db.flush()
                return None

            if decision.requires_approval and not self._is_step_approved(db, run.id, step_id):
                challenge = self._create_approval(db, run.id, scope=f"step:{step_id}", reason=decision.reason, requested_by=requested_by)
                run.status = "needs_approval"
                run.summary = f"Paused for approval at step {step_id}: {decision.reason}"
                evidence.write_manifest({"status": run.status, "summary": run.summary, "pending_step": step_id})
                db.add(run)
                db.flush()
                return challenge

            if external_effect:
                external_actions += 1
                if external_actions > settings.max_external_actions_per_run:
                    run.status = "blocked"
                    run.finished_at = datetime.utcnow()
                    run.summary = "Blocked: exceeded max_external_actions_per_run threshold."
                    evidence.write_manifest({"status": run.status, "summary": run.summary})
                    db.add(run)
                    db.flush()
                    return None

            ctx = ToolContext(
                run_id=run.id,
                task_id=run.task_id,
                requested_by=requested_by,
                evidence=evidence,
                dry_run=dry_run,
                db=db,
                scratch=scratch,
            )

            record = ToolCallRecord(
                ts=datetime.utcnow().isoformat() + "Z",
                tool=tool.name,
                input=dict(step.get("args") or {}),
                output=None,
                error=None,
                risk_tier=risk_tier,
                external_effect=external_effect,
                evidence_ids=[],
            )

            try:
                result = tool.call(ctx, **(step.get("args") or {}))
                record.output = result.output
                record.evidence_ids = result.evidence_ids
                record.external_effect = record.external_effect or result.external_effect
                self._persist_artifacts(db, run.id, result.output)
                self._log_event(db, run.id, "tool_call", {"step_id": step_id, "tool": tool.name, "risk_tier": risk_tier, "external_effect": record.external_effect, "evidence_ids": record.evidence_ids})
            except Exception as e:
                record.error = f"{type(e).__name__}: {e}"
                self._log_event(db, run.id, "tool_error", {"step_id": step_id, "tool": tool.name, "error": record.error})
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                run.summary = f"Failed at step {step_id} ({tool.name}): {record.error}"
                evidence.append_tool_call(record)
                evidence.write_manifest({"status": run.status, "summary": run.summary, "failed_step": step_id})
                db.add(run)
                db.flush()
                raise

            evidence.append_tool_call(record)
            completed = run.plan_json.get("_completed_steps", []) or []
            completed.append(step_id)
            run.plan_json["_completed_steps"] = completed
            db.add(run)
            db.flush()

        run.status = "succeeded"
        run.finished_at = datetime.utcnow()
        run.summary = run.summary or "Completed."
        evidence.write_manifest({"status": run.status, "summary": run.summary, "completed_steps": run.plan_json.get("_completed_steps", [])})
        db.add(run)
        db.flush()
        return None

    def _persist_artifacts(self, db: Session, run_id: str, output: dict | None) -> None:
        if not output or "artifacts" not in output:
            return
        artifacts = output.get("artifacts") or []
        if not isinstance(artifacts, list):
            return
        for a in artifacts:
            try:
                evidence_id = str(a.get("evidence_id") or "")
                typ = str(a.get("type") or "artifact")
                uri = str(a.get("path") or a.get("uri") or "")
                sha = str(a.get("sha256") or "")
                if not (evidence_id and uri and sha):
                    continue
                existing = db.query(Artifact).filter(Artifact.run_id == run_id, Artifact.uri == uri, Artifact.sha256 == sha).first()
                if existing:
                    continue
                db.add(Artifact(id=new_id("ART"), run_id=run_id, type=typ, uri=uri, sha256=sha, metadata_json={"evidence_id": evidence_id}))
                db.flush()
            except Exception:
                logger.exception("Failed persisting artifact row")

    def _log_event(self, db: Session, run_id: str, kind: str, payload: dict) -> None:
        db.add(Event(id=new_id("EVT"), run_id=run_id, kind=kind, payload_json=payload))
        db.flush()

    def _create_approval(self, db: Session, run_id: str, scope: str, reason: str, requested_by: str) -> ApprovalChallenge:
        token = new_id("APR", nbytes=16)
        token_hash = sha256_hex(token.encode("utf-8"))
        expires = datetime.utcnow() + timedelta(minutes=settings.approval_ttl_minutes)
        approval = Approval(
            id=new_id("APP"),
            run_id=run_id,
            scope=scope,
            requested_by=requested_by,
            approved_by=None,
            status="pending",
            decision_at=None,
            expires_at=expires,
            token_sha256=token_hash,
            notes=None,
            context_json={"reason": reason},
        )
        db.add(approval)
        db.flush()
        return ApprovalChallenge(approval=approval, token=token, reason=reason)

    def _is_step_approved(self, db: Session, run_id: str, step_id: str) -> bool:
        row = db.query(Approval).filter(Approval.run_id == run_id, Approval.scope == f"step:{step_id}", Approval.status == "approved").first()
        return row is not None
