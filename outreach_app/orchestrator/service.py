from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.agents.finn import FinnAgent
from app.agents.gtm import GTMAgent
from app.agents.narrative import NarrativeAgent
from app.agents.ops import OpsAgent
from app.models.run import Run
from app.models.task import Task
from app.orchestrator.planner import Planner
from app.orchestrator.router import Router
from app.orchestrator.workflow import WorkflowEngine, ApprovalChallenge
from app.tools.registry import ToolRegistry
from app.utils.id import new_id


class Orchestrator:
    def __init__(self, tools: ToolRegistry, planner: Planner):
        self.tools = tools
        self.router = Router()
        self.planner = planner
        self.workflow = WorkflowEngine(tools)
        self.agents = {
            "FINN": FinnAgent(planner),
            "GTM_OPERATOR": GTMAgent(planner),
            "NARRATIVE_OPERATOR": NarrativeAgent(planner),
            "OPS_ENGINEER": OpsAgent(planner),
        }

    def start_run(
        self,
        *,
        db: Session,
        task: Task,
        requested_by: str,
        force_agent: str | None,
        dry_run: bool,
    ) -> tuple[Run, ApprovalChallenge | None]:
        route = self.router.route(task)
        agent_name = force_agent or route.agent
        domain = route.domain
        if agent_name not in self.agents:
            raise ValueError(f"Unknown agent: {agent_name}")
        agent = self.agents[agent_name]
        plan = agent.build_plan(task=task, agent=agent_name, domain=domain)

        run = Run(
            id=new_id("RUN"),
            task_id=task.id,
            agent=agent_name,
            status="created",
            started_at=None,
            finished_at=None,
            max_risk_tier=0,
            cost_estimate_usd=None,
            plan_json={"steps": plan.steps, "meta": plan.meta, "_completed_steps": []},
            summary=None,
            evidence_uri=None,
        )
        db.add(run)
        db.flush()

        challenge = self.workflow.execute(db=db, run=run, task_payload=task.payload_json, requested_by=requested_by, dry_run=dry_run)
        agent.postprocess(db=db, run=run, task=task)

        if run.status == "succeeded":
            task.status = "done"
        elif run.status in {"failed", "blocked"}:
            task.status = "needs_attention"
        elif run.status == "needs_approval":
            task.status = "waiting_approval"
        else:
            task.status = "in_progress"

        task.updated_at = datetime.utcnow()
        db.add(task)
        db.add(run)
        db.flush()
        return run, challenge
