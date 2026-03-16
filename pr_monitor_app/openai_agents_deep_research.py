from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from pr_monitor_app.config import settings

try:  # pragma: no cover - optional dependency at runtime
    from agents import Agent, Runner, WebSearchTool, function_tool, set_default_openai_client, set_tracing_disabled
    from agents.run_context import RunContextWrapper
    from openai import AsyncOpenAI

    AGENTS_SDK_AVAILABLE = True
    AGENTS_SDK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import failure is environment-specific
    Agent = None  # type: ignore[assignment]
    Runner = None  # type: ignore[assignment]
    WebSearchTool = None  # type: ignore[assignment]
    function_tool = None  # type: ignore[assignment]
    RunContextWrapper = Any  # type: ignore[assignment]
    AsyncOpenAI = None  # type: ignore[assignment]
    set_default_openai_client = None  # type: ignore[assignment]
    set_tracing_disabled = None  # type: ignore[assignment]
    AGENTS_SDK_AVAILABLE = False
    AGENTS_SDK_IMPORT_ERROR = exc


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    url: str
    why_it_matters: str = ""
    source_type: Literal["primary", "secondary", "expert", "news", "reference"] = "reference"
    credibility: float = Field(default=0.5, ge=0.0, le=1.0)
    published_at: Optional[str] = None


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    research_questions: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class InitialInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_concepts: list[str] = Field(default_factory=list)
    preliminary_findings: list[str] = Field(default_factory=list)
    prioritized_sources: list[Source] = Field(default_factory=list)
    gaps_to_investigate: list[str] = Field(default_factory=list)


class DeepDiveSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    quotations_or_facts: list[str] = Field(default_factory=list)
    credibility_notes: list[str] = Field(default_factory=list)


class CrossReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    agreement_level: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""


class DeepDive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detailed_content: list[DeepDiveSource] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    expert_sources: list[Source] = Field(default_factory=list)
    comparative_analysis: list[str] = Field(default_factory=list)


class VerifiedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    verified: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    supporting_sources: list[str] = Field(default_factory=list)
    notes: str = ""


class BiasAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_bias_risk: Literal["low", "medium", "high"] = "medium"
    notes: list[str] = Field(default_factory=list)


class ConfidenceLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    verified_claims: list[VerifiedClaim] = Field(default_factory=list)
    bias_assessment: BiasAssessment = Field(default_factory=BiasAssessment)
    confidence_levels: list[ConfidenceLevel] = Field(default_factory=list)


class ReportFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    finding: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class SourceEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    average_credibility: float = Field(default=0.0, ge=0.0, le=1.0)
    source_diversity: Literal["poor", "fair", "good", "excellent"] = "fair"
    strongest_sources: list[str] = Field(default_factory=list)
    weakest_sources: list[str] = Field(default_factory=list)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = ""
    detailed_findings: list[ReportFinding] = Field(default_factory=list)
    source_evaluation: SourceEvaluation = Field(default_factory=SourceEvaluation)
    remaining_questions: list[str] = Field(default_factory=list)
    research_methodology: list[str] = Field(default_factory=list)


class DeepResearchPhases(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase1: InitialInvestigation
    phase2: DeepDive
    phase3: Synthesis


class DeepResearchMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: str
    fetched_urls: list[str] = Field(default_factory=list)


class DeepResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    research_plan: ResearchPlan
    findings: DeepResearchPhases
    report: Report
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: DeepResearchMetadata


@dataclass(slots=True)
class DeepResearchContext:
    topic: str
    requested_questions: list[str]
    started_at: str
    fetched_urls: list[str] = field(default_factory=list)


_DEFAULT_TIMEOUT = 20.0
_HTML_SPACE_RE = re.compile(r"\s+")
_OPENAI_AGENTS_CONFIGURED = False


def openai_agents_ready() -> tuple[bool, Optional[str]]:
    if not settings.onboarding_agent_enabled:
        return False, "disabled"
    if not AGENTS_SDK_AVAILABLE:
        detail = str(AGENTS_SDK_IMPORT_ERROR) if AGENTS_SDK_IMPORT_ERROR else "agents sdk unavailable"
        return False, detail
    api_key = settings.openai_api_key or settings.llm_api_key
    if not api_key:
        return False, "missing openai api key"
    return True, None


def _configure_openai_agents() -> None:
    global _OPENAI_AGENTS_CONFIGURED
    ready, reason = openai_agents_ready()
    if not ready:
        raise RuntimeError(reason or "OpenAI Agents SDK is not ready")
    if _OPENAI_AGENTS_CONFIGURED:
        return

    api_key = settings.openai_api_key or settings.llm_api_key or ""
    base_url = settings.openai_base_url or settings.llm_base_url
    os.environ.setdefault("OPENAI_API_KEY", api_key)
    if base_url:
        os.environ.setdefault("OPENAI_BASE_URL", base_url)
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")

    if AsyncOpenAI is None or set_default_openai_client is None:
        raise RuntimeError("OpenAI Agents SDK imports are incomplete")

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)

    try:
        set_default_openai_client(client, use_for_tracing=False)
    except TypeError:  # pragma: no cover - version-specific signature
        set_default_openai_client(client)
    if set_tracing_disabled is not None:
        try:
            set_tracing_disabled(True)
        except Exception:  # pragma: no cover - tracing settings vary by SDK version
            pass

    _OPENAI_AGENTS_CONFIGURED = True


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _calculate_confidence(synthesis: Synthesis) -> float:
    claim_confidence = _average([item.confidence for item in synthesis.verified_claims])
    area_confidence = _average([item.confidence for item in synthesis.confidence_levels])
    contradiction_penalty = min(len(synthesis.contradictions) * 0.03, 0.15)
    score = (claim_confidence * 0.65) + (area_confidence * 0.35) - contradiction_penalty
    return max(0.0, min(1.0, score))


def _html_to_text(html: str, max_chars: int) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return _HTML_SPACE_RE.sub(" ", text).strip()[:max_chars]


if AGENTS_SDK_AVAILABLE:

    @function_tool
    async def fetch_page_text(
        ctx: RunContextWrapper[DeepResearchContext],
        url: str,
        max_chars: int = 12_000,
    ) -> dict[str, Any]:
        """
        Fetch a public web page and return compact readable text.
        """
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "user-agent": settings.http_user_agent,
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        text = _html_to_text(html, max_chars=max_chars)
        if getattr(ctx, "context", None) is not None:
            ctx.context.fetched_urls.append(str(response.url))
        return {"url": str(response.url), "text": text, "char_count": len(text)}


class OpenAIAgentsDeepResearch:
    def __init__(self, *, max_sources: Optional[int] = None, model: Optional[str] = None) -> None:
        self.max_sources = max_sources or settings.onboarding_agent_max_sources
        self.model = model or settings.onboarding_agent_model

    @staticmethod
    def ready() -> tuple[bool, Optional[str]]:
        return openai_agents_ready()

    def _planner_agent(self) -> Any:
        return Agent(
            name="Research Planner",
            model=self.model,
            instructions=(
                "You create concise, high-quality research plans. "
                "Preserve user-supplied questions when they are useful. "
                "Generate varied search terms, verification objectives, inclusion criteria, and exclusions."
            ),
            output_type=ResearchPlan,
        )

    def _search_agent(self) -> Any:
        return Agent(
            name="Initial Investigator",
            model=self.model,
            instructions=(
                "Use web search to map the topic landscape. "
                "Prefer official websites, public filings, reputable publications, recognized experts, and reference material. "
                "Return diverse prioritized sources with calibrated credibility scores."
            ),
            tools=[WebSearchTool()],
            output_type=InitialInvestigation,
        )

    def _source_analyzer_agent(self) -> Any:
        return Agent(
            name="Source Analyzer",
            model=self.model,
            instructions=(
                "Inspect the most relevant sources in detail. "
                "Use the page fetch tool to read actual pages when possible. "
                "Extract key points, useful factual statements, and credibility notes. "
                "Compare sources and identify areas of agreement."
            ),
            tools=[fetch_page_text],
            output_type=DeepDive,
        )

    def _validator_agent(self) -> Any:
        return Agent(
            name="Validator",
            model=self.model,
            instructions=(
                "Synthesize the source analysis, identify patterns and contradictions, and validate claims conservatively. "
                "Only mark a claim verified when available evidence clearly supports it."
            ),
            output_type=Synthesis,
        )

    def _writer_agent(self) -> Any:
        return Agent(
            name="Research Writer",
            model=self.model,
            instructions=(
                "Create a structured research report based only on the prior phases. "
                "Keep the executive summary compact, findings evidence-backed, and source evaluation realistic."
            ),
            output_type=Report,
        )

    async def conduct_research(
        self,
        topic: str,
        research_questions: Optional[list[str]] = None,
    ) -> DeepResearchResult:
        _configure_openai_agents()
        questions = list(research_questions or [])
        context = DeepResearchContext(
            topic=topic,
            requested_questions=questions,
            started_at=datetime.now(UTC).isoformat(),
        )

        plan_result = await Runner.run(
            self._planner_agent(),
            input=json.dumps(
                {
                    "topic": topic,
                    "requested_questions": questions,
                    "constraints": {
                        "desired_search_terms": 6,
                        "desired_questions": len(questions) if questions else 5,
                    },
                },
                ensure_ascii=False,
            ),
            context=context,
        )
        research_plan = plan_result.final_output

        initial_result = await Runner.run(
            self._search_agent(),
            input=json.dumps(
                {
                    "topic": topic,
                    "research_plan": research_plan.model_dump(mode="json"),
                    "instruction": "Use web search to identify the best sources for the plan. Prioritize diversity and authority.",
                    "max_sources": self.max_sources,
                },
                ensure_ascii=False,
            ),
            context=context,
        )
        phase1 = initial_result.final_output

        selected_sources = phase1.prioritized_sources[: self.max_sources]
        deep_dive_result = await Runner.run(
            self._source_analyzer_agent(),
            input=json.dumps(
                {
                    "topic": topic,
                    "research_plan": research_plan.model_dump(mode="json"),
                    "selected_sources": [source.model_dump(mode="json") for source in selected_sources],
                    "instruction": "Read and analyze these sources in depth. Use the fetch tool for page text when useful.",
                },
                ensure_ascii=False,
            ),
            context=context,
        )
        phase2 = deep_dive_result.final_output

        validation_result = await Runner.run(
            self._validator_agent(),
            input=json.dumps(
                {
                    "topic": topic,
                    "research_plan": research_plan.model_dump(mode="json"),
                    "phase1": phase1.model_dump(mode="json"),
                    "phase2": phase2.model_dump(mode="json"),
                    "instruction": "Synthesize the analysis, assess contradictions, and produce calibrated confidence scores.",
                },
                ensure_ascii=False,
            ),
            context=context,
        )
        phase3 = validation_result.final_output

        report_result = await Runner.run(
            self._writer_agent(),
            input=json.dumps(
                {
                    "topic": topic,
                    "research_questions": research_plan.research_questions,
                    "objectives": research_plan.objectives,
                    "phase1": phase1.model_dump(mode="json"),
                    "phase2": phase2.model_dump(mode="json"),
                    "phase3": phase3.model_dump(mode="json"),
                    "fetched_urls": sorted(set(context.fetched_urls)),
                },
                ensure_ascii=False,
            ),
            context=context,
        )
        report = report_result.final_output

        return DeepResearchResult(
            topic=topic,
            research_plan=research_plan,
            findings=DeepResearchPhases(phase1=phase1, phase2=phase2, phase3=phase3),
            report=report,
            confidence=round(_calculate_confidence(phase3), 3),
            metadata=DeepResearchMetadata(
                started_at=context.started_at,
                fetched_urls=sorted(set(context.fetched_urls)),
            ),
        )
