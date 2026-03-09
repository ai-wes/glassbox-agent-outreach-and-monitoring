from __future__ import annotations

import json
from dataclasses import dataclass

from app.llm.base import LLMClient
from app.llm.rule_based import RuleBasedLLM
from app.orchestrator.policy import RiskTier
from app.tools.registry import ToolRegistry


@dataclass
class Plan:
    steps: list[dict]
    meta: dict


class Planner:
    """
    Planner emits an explicit tool-call plan.

    If payload includes `steps`, those are used directly after validation.
    """

    def __init__(self, tools: ToolRegistry, llm: LLMClient | None = None):
        self.tools = tools
        self.llm = llm or RuleBasedLLM()

    def make_plan(self, *, agent: str, domain: str, task_title: str, payload: dict) -> Plan:
        if "steps" in payload:
            steps = payload["steps"]
            self._validate_steps(steps)
            return Plan(steps=steps, meta={"source": "payload", "agent": agent, "domain": domain})

        # Templates
        if domain == "exec":
            steps = [
                {
                    "id": "draft_exec_memo",
                    "name": "Draft executive memo",
                    "tool": "fs.write_text",
                    "args": {
                        "rel_path": "exec/memo.md",
                        "content": f"# Exec memo\n\nTask: {task_title}\n\nPayload:\n```json\n{json.dumps(payload, indent=2)}\n```\n",
                    },
                    "risk_tier": int(RiskTier.TIER1_INTERNAL_WRITE),
                    "external_effect": False,
                }
            ]
            self._validate_steps(steps)
            return Plan(steps=steps, meta={"source": "template", "agent": agent, "domain": domain})

        if domain == "narrative":
            steps = []
            url = payload.get("url")
            if url:
                steps.append(
                    {
                        "id": "fetch_url",
                        "name": "Fetch URL for analysis",
                        "tool": "http.get",
                        "args": {"url": url},
                        "risk_tier": int(RiskTier.TIER0_READONLY),
                        "external_effect": False,
                    }
                )
            steps.append(
                {
                    "id": "draft_post",
                    "name": "Draft LinkedIn post copy",
                    "tool": "fs.write_text",
                    "args": {"rel_path": "narrative/linkedin_post.txt", "content": payload.get("draft", f"Draft post about: {task_title}\n")},
                    "risk_tier": int(RiskTier.TIER1_INTERNAL_WRITE),
                    "external_effect": False,
                }
            )
            self._validate_steps(steps)
            return Plan(steps=steps, meta={"source": "template", "agent": agent, "domain": domain})

        if domain == "ops":
            steps = [
                {
                    "id": "create_ops_note",
                    "name": "Create ops note",
                    "tool": "fs.write_text",
                    "args": {"rel_path": "ops/note.md", "content": f"# Ops note\n\nTask: {task_title}\n\nPayload:\n```json\n{json.dumps(payload, indent=2)}\n```\n"},
                    "risk_tier": int(RiskTier.TIER1_INTERNAL_WRITE),
                    "external_effect": False,
                }
            ]
            self._validate_steps(steps)
            return Plan(steps=steps, meta={"source": "template", "agent": agent, "domain": domain})

        if domain == "gtm":
            steps = []
            to = payload.get("email_to")
            subject = payload.get("email_subject", f"Quick question re: {payload.get('topic', task_title)}")
            body = payload.get("email_body", "Hi —\n\nWanted to reach out with a quick idea.\n\nBest,\n")
            steps.append(
                {
                    "id": "draft_email",
                    "name": "Draft outreach email",
                    "tool": "fs.write_text",
                    "args": {"rel_path": "gtm/email_draft.txt", "content": f"TO: {to or ''}\nSUBJECT: {subject}\n\n{body}\n"},
                    "risk_tier": int(RiskTier.TIER1_INTERNAL_WRITE),
                    "external_effect": False,
                }
            )
            if payload.get("linkedin_profile_url"):
                steps.append(
                    {
                        "id": "linkedin_manual",
                        "name": "Manual LinkedIn connection + message",
                        "tool": "linkedin.manual_action",
                        "args": {
                            "profile_url": payload["linkedin_profile_url"],
                            "action": payload.get("linkedin_action", "connect_and_message"),
                            "message": payload.get("linkedin_message", ""),
                            "notes": payload.get("linkedin_notes", ""),
                        },
                        "risk_tier": int(RiskTier.TIER2_EXTERNAL_IMPACT),
                        "external_effect": True,
                    }
                )
            if payload.get("send_email") and to:
                steps.append(
                    {
                        "id": "send_email",
                        "name": "Send outreach email via SMTP",
                        "tool": "email.send_smtp",
                        "args": {"to": to, "subject": subject, "body": body},
                        "risk_tier": int(RiskTier.TIER2_EXTERNAL_IMPACT),
                        "external_effect": True,
                    }
                )
            self._validate_steps(steps)
            return Plan(steps=steps, meta={"source": "template", "agent": agent, "domain": domain})

        steps = [
            {
                "id": "note",
                "name": "Write note",
                "tool": "fs.write_text",
                "args": {"rel_path": "misc/note.txt", "content": f"{task_title}\n{json.dumps(payload)}\n"},
                "risk_tier": int(RiskTier.TIER1_INTERNAL_WRITE),
                "external_effect": False,
            }
        ]
        self._validate_steps(steps)
        return Plan(steps=steps, meta={"source": "template", "agent": agent, "domain": domain})

    def _validate_steps(self, steps: list[dict]) -> None:
        if not isinstance(steps, list) or not steps:
            raise ValueError("Plan must contain at least one step.")
        ids = set()
        for s in steps:
            for k in ("id", "name", "tool", "args"):
                if k not in s:
                    raise ValueError(f"Step missing '{k}': {s}")
            if s["id"] in ids:
                raise ValueError(f"Duplicate step id: {s['id']}")
            ids.add(s["id"])
            tool = self.tools.get(s["tool"])
            if "risk_tier" not in s:
                s["risk_tier"] = int(getattr(tool, "risk_tier", 0))
            if "external_effect" not in s:
                s["external_effect"] = bool(int(s["risk_tier"]) >= int(RiskTier.TIER2_EXTERNAL_IMPACT))
