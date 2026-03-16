from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from pr_monitor_app.config import settings
from pr_monitor_app.models_onboarding import (
    CategoryProposalStatus,
    CompanyResolutionCandidate,
    MonitoringBlueprintProposal,
    OnboardingSession,
    ResolvedCompanyProfile,
)
from pr_monitor_app.openai_agents_deep_research import (
    AGENTS_SDK_AVAILABLE,
    Agent,
    OpenAIAgentsDeepResearch,
    Runner,
    WebSearchTool,
    openai_agents_ready,
)


_SPACE_RE = re.compile(r"\s+")
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|inc\.|llc|l\.l\.c\.|corp|corp\.|corporation|company|co\.|ltd|ltd\.|plc|gmbh|s\.a\.|ag)\b",
    re.IGNORECASE,
)
_COMMON_NEGATIVE_KEYWORDS = ["jobs", "careers", "wiki", "wikipedia", "meaning", "definition", "stock"]
_SOURCE_PRIORITY = {
    "official_website": 0,
    "press": 1,
    "blog": 2,
    "linkedin": 3,
    "news": 4,
    "trade_publications": 5,
    "competitor_channels": 6,
}


class ResolutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    url: Optional[str] = None
    snippet: str = ""
    why_it_matters: str = ""


class AgentResolutionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    canonical_name: str
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: Optional[str] = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    evidence: list[ResolutionEvidence] = Field(default_factory=list)


class CompanyResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranked_candidates: list[AgentResolutionCandidate] = Field(default_factory=list)
    recommended_index: int = 0
    confidence_level: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class AgentResolvedCompanyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: str = ""
    industry: Optional[str] = None
    subindustry: Optional[str] = None
    products: list[str] = Field(default_factory=list)
    executives: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    official_pages: list[str] = Field(default_factory=list)
    press_pages: list[str] = Field(default_factory=list)
    blog_pages: list[str] = Field(default_factory=list)
    social_profiles: list[str] = Field(default_factory=list)
    trade_publications: list[str] = Field(default_factory=list)
    competitor_urls: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    opportunity_themes: list[str] = Field(default_factory=list)
    confidence: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class AgentBlueprintCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: str = ""
    sensitivity: Literal["high", "medium", "low", "digest_only"] = "medium"
    recommended_sources: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    sample_queries: list[str] = Field(default_factory=list)
    noise_risks: list[str] = Field(default_factory=list)
    human_refinement_notes: list[str] = Field(default_factory=list)


class AgentMonitoringBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    rationale: str = ""
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    categories: list[AgentBlueprintCategory] = Field(default_factory=list)
    suggested_sources: dict[str, Any] = Field(default_factory=dict)
    risks_and_ambiguities: list[str] = Field(default_factory=list)


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = _SPACE_RE.sub(" ", str(value)).strip()
    return cleaned or None


def _clean_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    return candidate.rstrip("/")


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _extract_domain(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    return parsed.netloc.lower().removeprefix("www.")


def _build_aliases(canonical_name: Optional[str], website: Optional[str]) -> list[str]:
    if not canonical_name:
        return []
    cleaned = _COMPANY_SUFFIX_RE.sub("", canonical_name).strip(" ,")
    aliases = [canonical_name.strip()]
    if cleaned and cleaned.lower() != canonical_name.strip().lower():
        aliases.append(cleaned)
    words = [word for word in re.split(r"[^A-Za-z0-9]+", cleaned) if word]
    if len(words) >= 2:
        aliases.append("".join(word[0].upper() for word in words[:5]))
    domain = _extract_domain(website or "")
    if domain:
        aliases.append(domain.split(".")[0])
    return _dedupe_strings(aliases)


def _sort_sources(values: list[str]) -> list[str]:
    return sorted(_dedupe_strings(values), key=lambda item: _SOURCE_PRIORITY.get(item, 99))


def _sample_queries(phrases: list[str], extras: list[str]) -> list[str]:
    queries: list[str] = []
    for phrase in _dedupe_strings(phrases):
        queries.append(f"\"{phrase}\"")
        for extra in extras:
            if extra:
                queries.append(f"\"{phrase}\" AND \"{extra}\"")
                break
        if len(queries) >= 5:
            break
    return _dedupe_strings(queries)[:5]


def _default_negative_keywords(company_name: str) -> list[str]:
    negatives = list(_COMMON_NEGATIVE_KEYWORDS)
    if len(company_name.split()) <= 1:
        negatives.extend(["song", "movie", "dictionary"])
    return _dedupe_strings(negatives)


class OnboardingResearchAgent:
    def __init__(self, *, model: Optional[str] = None, max_sources: Optional[int] = None) -> None:
        self.model = model or settings.onboarding_agent_model
        self.max_sources = max_sources or settings.onboarding_agent_max_sources
        self.deep_research = OpenAIAgentsDeepResearch(max_sources=self.max_sources, model=self.model)

    @staticmethod
    def ready() -> tuple[bool, Optional[str]]:
        return openai_agents_ready()

    def _require_ready(self) -> None:
        ready, reason = self.ready()
        if not ready:
            raise RuntimeError(reason or "Onboarding agent is not available")
        if not AGENTS_SDK_AVAILABLE or Agent is None or Runner is None or WebSearchTool is None:
            raise RuntimeError("OpenAI Agents SDK classes are unavailable")

    async def resolve_company(self, row: OnboardingSession) -> list[dict[str, Any]]:
        self._require_ready()
        intake = row.raw_intake_json or {}
        resolver_agent = Agent(
            name="Layer 0 Company Resolver",
            model=self.model,
            instructions=(
                "Resolve the intended company identity from public web evidence. "
                "Search for the likely company website, LinkedIn company page, and public summary. "
                "Return ranked candidates with confidence scores, rationale, and evidence. "
                "Be conservative when the company name is broad or ambiguous."
            ),
            tools=[WebSearchTool()],
            output_type=CompanyResolutionResult,
        )
        result = await Runner.run(
            resolver_agent,
            input=json.dumps(
                {
                    "company_name": row.company_name_input,
                    "website_hint": row.website_input,
                    "linkedin_url_hint": row.linkedin_url_input,
                    "short_description": row.short_description_input,
                    "notes": row.notes_input,
                    "known_competitors": intake.get("competitors") or [],
                    "known_executives": intake.get("executives") or [],
                    "known_products": intake.get("products") or [],
                    "industry_hint": intake.get("industry"),
                    "monitoring_goals": intake.get("monitoring_goals") or [],
                },
                ensure_ascii=False,
            ),
        )
        output = result.final_output
        candidates: list[dict[str, Any]] = []
        recommended_index = max(0, min(output.recommended_index, len(output.ranked_candidates) - 1)) if output.ranked_candidates else 0
        for index, candidate in enumerate(output.ranked_candidates[:6]):
            evidence = [
                item.model_dump(mode="json")
                for item in candidate.evidence
                if item.url or item.title or item.snippet
            ]
            candidates.append(
                {
                    "display_name": _clean_text(candidate.display_name) or row.company_name_input,
                    "canonical_name": _clean_text(candidate.canonical_name) or row.company_name_input,
                    "website": _clean_url(candidate.website) or row.website_input,
                    "linkedin_url": _clean_url(candidate.linkedin_url) or row.linkedin_url_input,
                    "summary": _clean_text(candidate.summary) or row.short_description_input,
                    "confidence_score": round(float(candidate.confidence_score), 2),
                    "source_evidence_json": {
                        "agent": "openai_agents_sdk",
                        "resolution_rationale": output.rationale,
                        "evidence": evidence,
                    },
                    "is_selected": len(output.ranked_candidates) == 1 and index == recommended_index and candidate.confidence_score >= 0.85,
                    "rationale": _clean_text(candidate.rationale) or output.rationale,
                }
            )
        return candidates

    async def enrich_company(
        self,
        *,
        row: OnboardingSession,
        candidate: CompanyResolutionCandidate,
        intake: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_ready()
        research = await self.deep_research.conduct_research(
            topic=(
                f"{candidate.canonical_name} company profile, products, executives, competitors, "
                "public channels, reputational risks, and PR opportunities"
            ),
            research_questions=[
                "What does the company do and how does it describe itself publicly?",
                "What products or services should be monitored?",
                "Which executives or spokespeople are publicly visible?",
                "Which competitors or adjacent companies are most relevant?",
                "Which reputational risks and thought-leadership opportunities matter most for PR monitoring?",
            ],
        )
        profile_agent = Agent(
            name="Layer 0 Company Profile Builder",
            model=self.model,
            instructions=(
                "Turn the research output into a structured company profile for PR monitoring. "
                "Prefer official public sources. Do not invent executives, products, or competitors. "
                "Only include channels and source URLs that are directly supported by the supplied evidence."
            ),
            output_type=AgentResolvedCompanyProfile,
        )
        result = await Runner.run(
            profile_agent,
            input=json.dumps(
                {
                    "company_name": row.company_name_input,
                    "selected_candidate": {
                        "display_name": candidate.display_name,
                        "canonical_name": candidate.canonical_name,
                        "website": candidate.website,
                        "linkedin_url": candidate.linkedin_url,
                        "summary": candidate.summary,
                    },
                    "operator_intake": intake,
                    "research": research.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
        )
        profile = result.final_output
        channels_json = {
            "official_pages": _dedupe_strings(list(profile.official_pages) + ([candidate.website] if candidate.website else []))[:6],
            "press_pages": _dedupe_strings(profile.press_pages)[:6],
            "blog_pages": _dedupe_strings(profile.blog_pages)[:6],
            "social_profiles": _dedupe_strings(
                list(profile.social_profiles) + ([candidate.linkedin_url] if candidate.linkedin_url else [])
            )[:8],
            "trade_publications": _dedupe_strings(profile.trade_publications)[:8],
            "competitor_urls": _dedupe_strings(profile.competitor_urls)[:8],
        }
        confidence_json = dict(profile.confidence)
        confidence_json.update(
            {
                "agent_enabled": True,
                "agent_research_confidence": research.confidence,
                "resolution_confidence": candidate.confidence_score,
                "source_count": len(research.findings.phase1.prioritized_sources),
            }
        )
        return {
            "canonical_name": _clean_text(profile.canonical_name) or candidate.canonical_name,
            "website": _clean_url(profile.website) or candidate.website or row.website_input,
            "linkedin_url": _clean_url(profile.linkedin_url) or candidate.linkedin_url or row.linkedin_url_input,
            "summary": _clean_text(profile.summary) or _clean_text(candidate.summary) or row.short_description_input or "",
            "industry": _clean_text(profile.industry),
            "subindustry": _clean_text(profile.subindustry),
            "products_json": _dedupe_strings(profile.products),
            "executives_json": _dedupe_strings(profile.executives + list(intake.get("executives") or [])),
            "competitors_json": _dedupe_strings(profile.competitors + list(intake.get("competitors") or [])),
            "channels_json": channels_json,
            "themes_json": _dedupe_strings(profile.themes + list(intake.get("monitoring_goals") or [])),
            "risk_themes_json": _dedupe_strings(profile.risk_themes),
            "opportunity_themes_json": _dedupe_strings(profile.opportunity_themes + list(intake.get("monitoring_goals") or [])),
            "source_evidence_json": {
                "agent": "openai_agents_sdk",
                "profile_rationale": profile.rationale,
                "agent_research": research.model_dump(mode="json"),
            },
            "confidence_json": confidence_json,
        }

    def _normalize_blueprint_output(
        self,
        *,
        row: OnboardingSession,
        profile: ResolvedCompanyProfile,
        intake: dict[str, Any],
        blueprint: AgentMonitoringBlueprint,
    ) -> dict[str, Any]:
        aliases = _build_aliases(profile.canonical_name, profile.website)
        company_entities = _dedupe_strings([profile.canonical_name, row.company_name_input] + aliases)
        category_payloads: list[dict[str, Any]] = []
        for category in blueprint.categories:
            keywords = _dedupe_strings(category.keywords)
            negative_keywords = _dedupe_strings(category.negative_keywords)
            if category.title.lower().startswith("direct") and not negative_keywords:
                negative_keywords = _default_negative_keywords(row.company_name_input)
            entities = _dedupe_strings(category.entities or company_entities[:3])
            extras = [profile.canonical_name, profile.industry or ""]
            sample_queries = category.sample_queries or _sample_queries(entities or keywords, extras=extras)
            category_payloads.append(
                {
                    "title": _clean_text(category.title) or "Monitoring Category",
                    "description": _clean_text(category.description) or "",
                    "priority": category.priority,
                    "rationale": _clean_text(category.rationale) or "",
                    "sensitivity": category.sensitivity,
                    "recommended_sources_json": _sort_sources(category.recommended_sources),
                    "entities_json": entities,
                    "keywords_json": keywords,
                    "negative_keywords_json": negative_keywords,
                    "sample_queries_json": _dedupe_strings(sample_queries)[:5],
                    "status": CategoryProposalStatus.proposed.value,
                }
            )
        if not category_payloads:
            raise RuntimeError("Blueprint agent returned no categories")

        derived_sources = _sort_sources(
            [source for category in category_payloads for source in category["recommended_sources_json"]]
        )
        proposal_json = {
            "company_identity": {
                "who_we_believe_the_company_is": profile.canonical_name,
                "website": profile.website,
                "linkedin_url": profile.linkedin_url,
                "category": profile.industry,
                "confidence": profile.confidence_json,
                "summary": profile.summary,
            },
            "recommended_monitoring_strategy": {
                "summary": _clean_text(blueprint.summary) or "",
                "rationale": _clean_text(blueprint.rationale) or "",
                "categories": [
                    {"title": category["title"], "priority": category["priority"], "why": category["rationale"]}
                    for category in category_payloads
                ],
            },
            "suggested_things_to_track": {
                "company_names_and_aliases": company_entities,
                "executives": list(profile.executives_json),
                "products": list(profile.products_json),
                "competitors": list(profile.competitors_json),
                "topic_terms": list(profile.themes_json),
                "risk_terms": list(profile.risk_themes_json),
            },
            "suggested_sources": {
                "channels": derived_sources,
                "official_pages": list(profile.channels_json.get("official_pages", [])),
                "press_pages": list(profile.channels_json.get("press_pages", [])),
                "blog_pages": list(profile.channels_json.get("blog_pages", [])),
                "trade_publications": list(profile.channels_json.get("trade_publications", [])),
                **blueprint.suggested_sources,
            },
            "suggested_alert_sensitivity": {
                "high_sensitivity": [category["title"] for category in category_payloads if category["sensitivity"] == "high"],
                "medium_sensitivity": [category["title"] for category in category_payloads if category["sensitivity"] == "medium"],
                "low_sensitivity": [category["title"] for category in category_payloads if category["sensitivity"] == "low"],
                "digest_only": [category["title"] for category in category_payloads if category["sensitivity"] == "digest_only"],
            },
            "risks_and_ambiguities": _dedupe_strings(blueprint.risks_and_ambiguities),
            "review_actions": [
                "approve all",
                "request revision",
                "reject blueprint",
            ],
            "operator_notes": intake.get("notes") or row.notes_input,
            "overall_confidence": round(float(blueprint.overall_confidence), 3),
        }
        return {
            "category_payloads": category_payloads,
            "proposal_json": proposal_json,
            "summary": _clean_text(blueprint.summary) or proposal_json["recommended_monitoring_strategy"]["summary"],
            "rationale": _clean_text(blueprint.rationale) or proposal_json["recommended_monitoring_strategy"]["rationale"],
            "overall_confidence": round(float(blueprint.overall_confidence), 3),
        }

    async def generate_blueprint(
        self,
        *,
        row: OnboardingSession,
        profile: ResolvedCompanyProfile,
        intake: dict[str, Any],
        current_blueprint: Optional[MonitoringBlueprintProposal] = None,
        current_categories: Optional[list[dict[str, Any]]] = None,
        operator_feedback: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._require_ready()
        blueprint_agent = Agent(
            name="Layer 0 Monitoring Blueprint Strategist",
            model=self.model,
            instructions=(
                "Create a monitoring blueprint for PR operators. "
                "Prioritize direct company signals, executive visibility, product narrative, competitors, industry context, risk, and opportunities. "
                "Return reviewable categories with priority, sensitivity, keywords, entities, recommended sources, and sample queries. "
                "Highlight ambiguities and likely noise risks."
            ),
            output_type=AgentMonitoringBlueprint,
        )
        result = await Runner.run(
            blueprint_agent,
            input=json.dumps(
                {
                    "company_name": row.company_name_input,
                    "notes": row.notes_input,
                    "operator_intake": intake,
                    "company_profile": {
                        "canonical_name": profile.canonical_name,
                        "website": profile.website,
                        "linkedin_url": profile.linkedin_url,
                        "summary": profile.summary,
                        "industry": profile.industry,
                        "subindustry": profile.subindustry,
                        "products": profile.products_json,
                        "executives": profile.executives_json,
                        "competitors": profile.competitors_json,
                        "channels": profile.channels_json,
                        "themes": profile.themes_json,
                        "risk_themes": profile.risk_themes_json,
                        "opportunity_themes": profile.opportunity_themes_json,
                        "source_evidence": profile.source_evidence_json,
                        "confidence": profile.confidence_json,
                    },
                    "current_blueprint": (
                        {
                            "summary": current_blueprint.summary,
                            "rationale": current_blueprint.rationale,
                            "proposal_json": current_blueprint.proposal_json,
                            "categories": current_categories or [],
                        }
                        if current_blueprint is not None
                        else None
                    ),
                    "operator_feedback": operator_feedback or {},
                },
                ensure_ascii=False,
            ),
        )
        return self._normalize_blueprint_output(
            row=row,
            profile=profile,
            intake=intake,
            blueprint=result.final_output,
        )
