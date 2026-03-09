from __future__ import annotations

import json
import logging

import typer

from app.core.logging import configure_logging
from app.db.session import db_session
from app.models.task import Task
from app.orchestrator.planner import Planner
from app.orchestrator.service import Orchestrator
from app.scheduler import run_scheduled_tasks_once
from app.tools.factory import build_registry
from app.utils.id import new_id

app = typer.Typer(help="Glassbox Operator CLI")


def _configure_cli_logging(verbose: bool) -> str:
    configure_logging()
    level = "DEBUG" if verbose else "INFO"
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    return level


@app.command()
def create_task(
    title: str,
    domain: str = "ops",
    priority: int = 50,
    payload_json: str = "{}",
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    level = _configure_cli_logging(verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    payload = json.loads(payload_json)
    with db_session() as db:
        t = Task(
            id=new_id("TSK"),
            title=title,
            domain=domain,
            priority=priority,
            owner_agent="router",
            status="queued",
            payload_json=payload,
        )
        db.add(t)
        db.flush()
        typer.echo(
            " ".join(
                [
                    "TASK_CREATED",
                    f"task_id={t.id}",
                    f"domain={t.domain}",
                    f"priority={t.priority}",
                    f"status={t.status}",
                ]
            )
        )


@app.command()
def run_task(
    task_id: str,
    requested_by: str = "cli",
    dry_run: bool = False,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    level = _configure_cli_logging(verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    tools = build_registry()
    planner = Planner(tools)
    orch = Orchestrator(tools, planner)

    typer.echo(f"RUN_TASK_START task_id={task_id} requested_by={requested_by} dry_run={str(dry_run).lower()}")
    with db_session() as db:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            raise typer.BadParameter("Task not found")

        typer.echo(
            " ".join(
                [
                    "TASK_CONTEXT",
                    f"id={t.id}",
                    f"domain={t.domain}",
                    f"status={t.status}",
                    f"priority={t.priority}",
                    f"due_at={t.due_at.isoformat() if t.due_at else 'none'}",
                    f"title={json.dumps(t.title)}",
                ]
            )
        )

        route = orch.router.route(t)
        agent = orch.agents[route.agent]
        plan = agent.build_plan(task=t, agent=route.agent, domain=route.domain)
        typer.echo(
            " ".join(
                [
                    "PLAN_CONTEXT",
                    f"domain={route.domain}",
                    f"agent={route.agent}",
                    f"source={plan.meta.get('source', 'unknown')}",
                    f"steps={len(plan.steps)}",
                ]
            )
        )
        for index, step in enumerate(plan.steps, start=1):
            typer.echo(
                " ".join(
                    [
                        "PLAN_STEP",
                        f"n={index}",
                        f"id={step.get('id', '')}",
                        f"tool={step.get('tool', '')}",
                        f"risk={step.get('risk_tier', 0)}",
                        f"external={str(bool(step.get('external_effect', False))).lower()}",
                    ]
                )
            )

        typer.echo("RUN_EXECUTE_START")
        run, challenge = orch.start_run(db=db, task=t, requested_by=requested_by, force_agent=None, dry_run=dry_run)
        completed_steps = list(run.plan_json.get("_completed_steps", []) or [])
        total_steps = len(list(run.plan_json.get("steps", []) or []))

        if challenge:
            typer.echo(
                " ".join(
                    [
                        "RUN_NEEDS_APPROVAL",
                        f"run_id={run.id}",
                        f"status={run.status}",
                        f"completed_steps={len(completed_steps)}/{total_steps}",
                        f"scope={challenge.approval.scope}",
                        f"token={challenge.token}",
                    ]
                )
            )
        else:
            typer.echo(
                " ".join(
                    [
                        "RUN_COMPLETE",
                        f"run_id={run.id}",
                        f"status={run.status}",
                        f"completed_steps={len(completed_steps)}/{total_steps}",
                        f"evidence={run.evidence_uri or 'none'}",
                    ]
                )
            )


@app.command()
def list_tasks(
    limit: int = 20,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    level = _configure_cli_logging(verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    with db_session() as db:
        rows = db.query(Task).order_by(Task.created_at.desc()).limit(limit).all()
        typer.echo(f"TASK_LIST count={len(rows)} limit={limit}")
        for r in rows:
            typer.echo(
                " ".join(
                    [
                        "TASK",
                        f"id={r.id}",
                        f"domain={r.domain}",
                        f"status={r.status}",
                        f"priority={r.priority}",
                        f"due_at={r.due_at.isoformat() if r.due_at else 'none'}",
                        f"title={json.dumps(r.title)}",
                    ]
                )
            )


@app.command()
def run_queue_once(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    level = _configure_cli_logging(verbose)
    typer.echo(f"CLI_LOG_LEVEL level={level}")
    typer.echo("SCHEDULER_TICK_START")
    summary = run_scheduled_tasks_once()
    typer.echo(
        " ".join(
            [
                "SCHEDULER_TICK_DONE",
                f"processed={int(summary.get('processed', 0))}",
                f"challenges={int(summary.get('challenges', 0))}",
                f"failures={int(summary.get('failures', 0))}",
            ]
        )
    )
