from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.task import Task
from app.orchestrator.planner import Plan, Planner


class BaseAgent:
    def __init__(self, planner: Planner):
        self._planner = planner

    def build_plan(self, *, task: Task, agent: str, domain: str) -> Plan:
        return self._planner.make_plan(
            agent=agent,
            domain=domain,
            task_title=task.title,
            payload=task.payload_json or {},
        )

    def postprocess(self, *, db: Session, run: Run, task: Task) -> None:
        _ = (db, run, task)
