from __future__ import annotations

from dataclasses import dataclass

from app.models.task import Task


@dataclass(frozen=True)
class Route:
    agent: str
    domain: str


class Router:
    """
    Deterministic router. Replace with a classifier/LLM if needed.
    """

    def route(self, task: Task) -> Route:
        domain = (task.domain or "").strip().lower()
        if domain in {"exec", "gtm", "narrative", "ops"}:
            return self._domain_to_agent(domain)

        t = task.title.lower()
        if any(k in t for k in ("pipeline", "prospect", "outreach", "deal", "hubspot", "crm")):
            return self._domain_to_agent("gtm")
        if any(k in t for k in ("blog", "post", "linkedin", "narrative", "content")):
            return self._domain_to_agent("narrative")
        if any(k in t for k in ("deploy", "release", "incident", "oncall", "bug")):
            return self._domain_to_agent("ops")
        return self._domain_to_agent("exec")

    def _domain_to_agent(self, domain: str) -> Route:
        mapping = {
            "exec": "FINN",
            "gtm": "GTM_OPERATOR",
            "narrative": "NARRATIVE_OPERATOR",
            "ops": "OPS_ENGINEER",
        }
        return Route(agent=mapping[domain], domain=domain)
