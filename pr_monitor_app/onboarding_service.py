from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.config import settings
from pr_monitor_app.llm.openai_compat import build_llm_client
from pr_monitor_app.models import BrandConfigDB, Client, SourceType, Subscription, SubscriptionType, TopicLens
from pr_monitor_app.models_agent import ClientProfile, ClientSignalRoute, SignalRecipientType
from pr_monitor_app.models_onboarding import (
    BlueprintReviewDecision,
    CategoryProposalStatus,
    CompanyResolutionCandidate,
    MonitoringBlueprintProposal,
    MonitoringCategoryProposal,
    OnboardingSession,
    OnboardingStatus,
    ResolvedCompanyProfile,
)
from pr_monitor_app.onboarding_schemas import (
    BlueprintReviewDecisionIn,
    CompanyResolutionCandidateOut,
    ConfirmCandidateIn,
    MaterializeBlueprintIn,
    MaterializationResultOut,
    MonitoringBlueprintProposalOut,
    MonitoringCategoryProposalPatch,
    MonitoringCategoryProposalOut,
    OnboardingAutoOut,
    OnboardingIntakeIn,
    OnboardingSessionDetailOut,
    OnboardingSessionOut,
    ResolvedCompanyProfileOut,
)

_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|inc\.|llc|l\.l\.c\.|corp|corp\.|corporation|company|co\.|ltd|ltd\.|plc|gmbh|s\.a\.|ag)\b",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_EXECUTIVE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*,\s*(CEO|Chief Executive Officer|Founder|Co-Founder|President|Chief [A-Za-z ]{1,40}|CMO|CFO|COO|CTO)\b"
)
_COMMON_NEGATIVE_KEYWORDS = ["jobs", "careers", "wiki", "wikipedia", "meaning", "definition", "stock"]
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SOURCE_PRIORITY = {
    "official_website": 0,
    "press": 1,
    "blog": 2,
    "linkedin": 3,
    "news": 4,
    "trade_publications": 5,
    "competitor_channels": 6,
}
_INDUSTRY_RULES = [
    {
        "industry": "Biotech",
        "subindustry": "Life Sciences",
        "keywords": ["biotech", "biopharma", "oncology", "therapeutics", "drug discovery", "clinical"],
    },
    {
        "industry": "Healthcare",
        "subindustry": "Health Tech",
        "keywords": ["healthcare", "health tech", "patient", "provider", "medical", "hospital"],
    },
    {
        "industry": "Cybersecurity",
        "subindustry": "Security Software",
        "keywords": ["cybersecurity", "security platform", "threat", "identity", "zero trust", "infosec"],
    },
    {
        "industry": "Fintech",
        "subindustry": "Financial Software",
        "keywords": ["fintech", "payments", "banking", "lending", "treasury", "financial services"],
    },
    {
        "industry": "AI Software",
        "subindustry": "Enterprise AI",
        "keywords": ["artificial intelligence", "machine learning", "ai platform", "llm", "automation", "copilot"],
    },
    {
        "industry": "Enterprise Software",
        "subindustry": "B2B SaaS",
        "keywords": ["saas", "workflow", "enterprise", "platform", "b2b", "software"],
    },
    {
        "industry": "Climate & Energy",
        "subindustry": "Energy Technology",
        "keywords": ["energy", "battery", "grid", "climate", "renewable", "decarbonization"],
    },
]
_INDUSTRY_RISK_THEMES = {
    "Biotech": ["clinical setbacks", "trial delays", "regulatory scrutiny", "safety signals", "funding pressure"],
    "Healthcare": ["regulatory scrutiny", "patient safety", "privacy concerns", "reimbursement pressure"],
    "Cybersecurity": ["breach claims", "outage risk", "trust erosion", "regulatory escalation"],
    "Fintech": ["compliance scrutiny", "fraud narratives", "security concerns", "market volatility"],
    "AI Software": ["model accuracy concerns", "trust and safety", "copyright risk", "regulatory scrutiny"],
    "Enterprise Software": ["outage risk", "pricing backlash", "trust erosion", "competitive displacement"],
    "Climate & Energy": ["project delays", "policy reversal", "safety issues", "capital intensity concerns"],
}
_INDUSTRY_OPPORTUNITY_THEMES = {
    "Biotech": ["scientific credibility", "pipeline differentiation", "partnership narrative", "category thought leadership"],
    "Healthcare": ["outcomes narrative", "care delivery modernization", "category education", "policy leadership"],
    "Cybersecurity": ["trust leadership", "incident response expertise", "security education", "category framing"],
    "Fintech": ["market education", "compliance leadership", "product trust", "category framing"],
    "AI Software": ["responsible AI leadership", "workflow transformation", "category definition", "earned expertise"],
    "Enterprise Software": ["efficiency narrative", "platform consolidation", "customer proof points", "thought leadership"],
    "Climate & Energy": ["policy relevance", "deployment milestones", "technology credibility", "market timing"],
}


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str


@dataclass(slots=True)
class PageSnapshot:
    url: str
    title: str
    description: str
    text_excerpt: str
    links: list[dict[str, str]]


class PublicWebResearcher:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.http_user_agent},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def search_web(self, query: str, *, limit: int = 6) -> list[SearchHit]:
        hits = await self._search_bing(query, limit=limit)
        if hits:
            return hits
        return await self._search_duckduckgo(query, limit=limit)

    async def _search_bing(self, query: str, *, limit: int) -> list[SearchHit]:
        url = f"https://www.bing.com/search?q={quote_plus(query)}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []
        for result in soup.select("li.b_algo"):
            link = result.select_one("h2 a")
            if link is None or not link.get("href"):
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            href = str(link.get("href")).strip()
            snippet_node = result.select_one(".b_caption p") or result.select_one("p")
            snippet = _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            hits.append(SearchHit(title=title, url=href, snippet=snippet, source="bing"))
            if len(hits) >= limit:
                break
        return hits

    async def _search_duckduckgo(self, query: str, *, limit: int) -> list[SearchHit]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []
        for result in soup.select(".result"):
            link = result.select_one("a.result__a")
            if link is None or not link.get("href"):
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            href = str(link.get("href")).strip()
            snippet_node = result.select_one(".result__snippet")
            snippet = _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            hits.append(SearchHit(title=title, url=href, snippet=snippet, source="duckduckgo"))
            if len(hits) >= limit:
                break
        return hits

    async def fetch_page(self, url: str) -> Optional[PageSnapshot]:
        if not url:
            return None
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "<html" not in response.text[:500].lower():
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        description = ""
        for selector in (
            {"attrs": {"name": "description"}},
            {"attrs": {"property": "og:description"}},
        ):
            meta = soup.find("meta", **selector)
            if meta and meta.get("content"):
                description = _clean_text(str(meta["content"]))
                if description:
                    break

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text_excerpt = _clean_text(soup.get_text(" ", strip=True))[:4000]
        links: list[dict[str, str]] = []
        for anchor in soup.select("a[href]"):
            href = _clean_url(anchor.get("href") or "")
            text = _clean_text(anchor.get_text(" ", strip=True))
            if not href:
                continue
            links.append({"text": text, "url": urljoin(str(response.url), href)})

        return PageSnapshot(
            url=str(response.url),
            title=title,
            description=description,
            text_excerpt=text_excerpt,
            links=_dedupe_dict_links(links),
        )


async def create_onboarding_session(
    session: AsyncSession,
    payload: OnboardingIntakeIn,
) -> OnboardingSessionDetailOut:
    row = OnboardingSession(
        company_name_input=payload.company_name.strip(),
        website_input=_clean_url(payload.website),
        linkedin_url_input=_clean_url(payload.linkedin_url),
        short_description_input=_clean_text(payload.short_description),
        notes_input=_clean_text(payload.notes),
        status=OnboardingStatus.draft.value,
        created_by=payload.created_by,
        raw_intake_json=_intake_to_json(payload),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return await get_onboarding_session_detail(session, row.id)


async def list_onboarding_sessions(session: AsyncSession, *, limit: int = 25) -> list[OnboardingSessionOut]:
    rows = (
        await session.execute(
            select(OnboardingSession).order_by(OnboardingSession.updated_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [OnboardingSessionOut.model_validate(row) for row in rows]


async def get_onboarding_session_detail(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    candidates = (
        await session.execute(
            select(CompanyResolutionCandidate)
            .where(CompanyResolutionCandidate.onboarding_session_id == onboarding_session_id)
            .order_by(CompanyResolutionCandidate.confidence_score.desc(), CompanyResolutionCandidate.created_at.asc())
        )
    ).scalars().all()
    profile = (
        await session.execute(
            select(ResolvedCompanyProfile).where(ResolvedCompanyProfile.onboarding_session_id == onboarding_session_id)
        )
    ).scalar_one_or_none()
    blueprint = await _load_latest_blueprint(session, onboarding_session_id)
    decisions: list[BlueprintReviewDecision] = []
    if blueprint is not None:
        decisions = (
            await session.execute(
                select(BlueprintReviewDecision)
                .where(BlueprintReviewDecision.blueprint_id == blueprint.id)
                .order_by(BlueprintReviewDecision.created_at.asc())
            )
        ).scalars().all()

    candidate_outs = [CompanyResolutionCandidateOut.model_validate(candidate) for candidate in candidates]
    recommended_candidate = candidate_outs[0] if candidate_outs else None
    selected_candidate = next((candidate for candidate in candidate_outs if candidate.is_selected), None)
    disambiguation_prompt = _build_disambiguation_prompt(candidate_outs)
    return OnboardingSessionDetailOut(
        session=OnboardingSessionOut.model_validate(row),
        candidates=candidate_outs,
        recommended_candidate=recommended_candidate,
        selected_candidate=selected_candidate,
        company_profile=ResolvedCompanyProfileOut.model_validate(profile) if profile else None,
        blueprint=await _blueprint_out(session, blueprint) if blueprint else None,
        review_decisions=[_decision_out(decision) for decision in decisions],
        disambiguation_prompt=disambiguation_prompt,
    )


async def resolve_onboarding_session(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    row.status = OnboardingStatus.resolving_company.value
    row.last_error = None
    await session.flush()

    intake = row.raw_intake_json or {}
    researcher = PublicWebResearcher()
    try:
        company_name = row.company_name_input
        hits = await researcher.search_web(f"{company_name} official website", limit=6)
        linkedin_hits = await researcher.search_web(f"{company_name} linkedin company", limit=4)
        candidate_payloads = _build_resolution_candidates(row=row, search_hits=hits, linkedin_hits=linkedin_hits)
    except Exception as exc:  # pragma: no cover - network failures vary
        row.status = OnboardingStatus.error.value
        row.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await researcher.close()

    await session.execute(
        delete(CompanyResolutionCandidate).where(
            CompanyResolutionCandidate.onboarding_session_id == onboarding_session_id
        )
    )

    if not candidate_payloads:
        fallback = {
            "display_name": row.company_name_input,
            "canonical_name": row.company_name_input,
            "website": row.website_input,
            "linkedin_url": row.linkedin_url_input,
            "summary": intake.get("short_description"),
            "confidence_score": 0.35,
            "source_evidence_json": {"source": "fallback"},
            "is_selected": bool(row.website_input or row.linkedin_url_input),
            "rationale": "Used operator-provided identity hints because public resolution was incomplete.",
        }
        candidate_payloads = [fallback]

    for index, payload in enumerate(candidate_payloads):
        if index == 0 and len(candidate_payloads) == 1 and payload.get("is_selected") is False:
            payload["is_selected"] = True
        session.add(CompanyResolutionCandidate(onboarding_session_id=onboarding_session_id, **payload))

    row.status = OnboardingStatus.awaiting_company_confirmation.value
    await session.commit()
    return await get_onboarding_session_detail(session, onboarding_session_id)


async def confirm_resolution_candidate(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
    payload: ConfirmCandidateIn,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    candidates = (
        await session.execute(
            select(CompanyResolutionCandidate).where(
                CompanyResolutionCandidate.onboarding_session_id == onboarding_session_id
            )
        )
    ).scalars().all()
    selected: Optional[CompanyResolutionCandidate] = None
    if payload.candidate_id is not None:
        selected = next((candidate for candidate in candidates if candidate.id == payload.candidate_id), None)
        if selected is None:
            raise ValueError("Selected candidate not found for session")
        if payload.display_name:
            selected.display_name = payload.display_name.strip()
        if payload.canonical_name:
            selected.canonical_name = payload.canonical_name.strip()
        if payload.website is not None:
            selected.website = _clean_url(payload.website)
        if payload.linkedin_url is not None:
            selected.linkedin_url = _clean_url(payload.linkedin_url)
        if payload.summary is not None:
            selected.summary = _clean_text(payload.summary)
    else:
        canonical_name = (payload.canonical_name or payload.display_name or row.company_name_input).strip()
        selected = CompanyResolutionCandidate(
            onboarding_session_id=onboarding_session_id,
            display_name=(payload.display_name or canonical_name).strip(),
            canonical_name=canonical_name,
            website=_clean_url(payload.website or row.website_input),
            linkedin_url=_clean_url(payload.linkedin_url or row.linkedin_url_input),
            summary=_clean_text(payload.summary or row.short_description_input),
            confidence_score=1.0,
            source_evidence_json={"source": "operator_confirmation"},
            is_selected=True,
            rationale="Operator supplied a custom company identity.",
        )
        session.add(selected)
        candidates.append(selected)

    for candidate in candidates:
        candidate.is_selected = bool(selected is not None and candidate.id == selected.id)

    row.status = OnboardingStatus.awaiting_company_confirmation.value
    await session.commit()
    return await get_onboarding_session_detail(session, onboarding_session_id)


async def enrich_onboarding_session(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    selected_candidate = await _load_selected_candidate(session, onboarding_session_id)
    if selected_candidate is None:
        raise ValueError("Resolve and confirm a company before enrichment")

    row.status = OnboardingStatus.enriching_company.value
    row.last_error = None
    await session.flush()

    intake = row.raw_intake_json or {}
    researcher = PublicWebResearcher()
    try:
        profile_data = await _build_resolved_company_profile(
            researcher=researcher,
            row=row,
            candidate=selected_candidate,
            intake=intake,
        )
    except Exception as exc:  # pragma: no cover - network failures vary
        row.status = OnboardingStatus.error.value
        row.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await researcher.close()

    existing = (
        await session.execute(
            select(ResolvedCompanyProfile).where(ResolvedCompanyProfile.onboarding_session_id == onboarding_session_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = ResolvedCompanyProfile(onboarding_session_id=onboarding_session_id, **profile_data)
        session.add(existing)
    else:
        for key, value in profile_data.items():
            setattr(existing, key, value)
    await session.commit()
    return await get_onboarding_session_detail(session, onboarding_session_id)


async def generate_onboarding_blueprint(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    profile = (
        await session.execute(
            select(ResolvedCompanyProfile).where(ResolvedCompanyProfile.onboarding_session_id == onboarding_session_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise ValueError("Enrich the company before generating a blueprint")

    row.status = OnboardingStatus.generating_blueprint.value
    await session.flush()

    intake = row.raw_intake_json or {}
    category_payloads = _build_category_proposals(row=row, profile=profile, intake=intake)
    proposal_json = _build_proposal_json(row=row, profile=profile, categories=category_payloads, intake=intake)
    llm_overlay = await _maybe_llm_blueprint_overlay(row=row, profile=profile, proposal_json=proposal_json)
    if llm_overlay:
        proposal_json = _merge_dicts(proposal_json, llm_overlay.get("proposal_json", {}))

    latest = await _load_latest_blueprint(session, onboarding_session_id)
    version = 1 if latest is None else latest.proposal_version + 1
    blueprint = MonitoringBlueprintProposal(
        onboarding_session_id=onboarding_session_id,
        company_profile_id=profile.id,
        proposal_version=version,
        summary=str(llm_overlay.get("summary") or proposal_json["recommended_monitoring_strategy"]["summary"]),
        overall_confidence=float(proposal_json.get("overall_confidence", 0.0)),
        rationale=str(llm_overlay.get("rationale") or proposal_json["recommended_monitoring_strategy"]["rationale"]),
        proposal_json=proposal_json,
    )
    session.add(blueprint)
    await session.flush()

    for category in category_payloads:
        session.add(MonitoringCategoryProposal(blueprint_id=blueprint.id, **category))

    row.status = OnboardingStatus.awaiting_user_review.value
    await session.commit()
    return await get_onboarding_session_detail(session, onboarding_session_id)


async def get_blueprint_for_session(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> MonitoringBlueprintProposalOut:
    blueprint = await _load_latest_blueprint(session, onboarding_session_id)
    if blueprint is None:
        raise ValueError("Blueprint not found for session")
    return await _blueprint_out(session, blueprint)


async def review_onboarding_blueprint(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
    payload: BlueprintReviewDecisionIn,
) -> OnboardingSessionDetailOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    blueprint = await _load_latest_blueprint(session, onboarding_session_id)
    if blueprint is None:
        raise ValueError("Blueprint not found for session")

    decision = BlueprintReviewDecision(
        blueprint_id=blueprint.id,
        action_type=payload.action_type.strip(),
        target_type=payload.target_type.strip(),
        target_id=payload.target_id,
        notes=payload.notes,
        diff_json=payload.diff_json or {},
        created_by=payload.created_by,
    )
    session.add(decision)

    if payload.action_type == "reject_blueprint":
        row.status = OnboardingStatus.rejected.value
    elif payload.action_type == "approve_all":
        await _set_category_statuses(session, blueprint.id, approved=True)
        row.status = OnboardingStatus.approved.value
    elif payload.action_type == "remove_category" and payload.target_id:
        await _set_single_category_status(session, payload.target_id, CategoryProposalStatus.removed.value)
    elif payload.action_type == "reject_category" and payload.target_id:
        await _set_single_category_status(session, payload.target_id, CategoryProposalStatus.rejected.value)
    elif payload.action_type == "approve_with_edits":
        await _apply_blueprint_edits(session, blueprint=blueprint, diff_json=payload.diff_json or {})
        await _set_category_statuses(session, blueprint.id, approved=True)
        row.status = OnboardingStatus.approved.value
    elif payload.action_type == "add_category":
        patch = MonitoringCategoryProposalPatch.model_validate((payload.diff_json or {}).get("category") or {})
        session.add(
            MonitoringCategoryProposal(
                blueprint_id=blueprint.id,
                title=patch.title,
                description=patch.description,
                priority=patch.priority,
                rationale=patch.rationale,
                sensitivity=patch.sensitivity,
                recommended_sources_json=patch.recommended_sources_json,
                entities_json=patch.entities_json,
                keywords_json=patch.keywords_json,
                negative_keywords_json=patch.negative_keywords_json,
                sample_queries_json=patch.sample_queries_json,
                status=patch.status,
            )
        )
    else:
        # Persist the review record even for notes-only actions.
        row.status = row.status or OnboardingStatus.awaiting_user_review.value

    await session.commit()
    return await get_onboarding_session_detail(session, onboarding_session_id)


async def materialize_onboarding_session(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
    payload: MaterializeBlueprintIn,
) -> MaterializationResultOut:
    row = await _get_session_or_raise(session, onboarding_session_id)
    if row.status != OnboardingStatus.approved.value:
        raise ValueError("Blueprint must be approved before materialization")

    profile = (
        await session.execute(
            select(ResolvedCompanyProfile).where(ResolvedCompanyProfile.onboarding_session_id == onboarding_session_id)
        )
    ).scalar_one_or_none()
    blueprint = await _load_latest_blueprint(session, onboarding_session_id)
    if profile is None or blueprint is None:
        raise ValueError("Resolved profile and blueprint are required before materialization")

    categories = (
        await session.execute(
            select(MonitoringCategoryProposal)
            .where(MonitoringCategoryProposal.blueprint_id == blueprint.id)
            .order_by(MonitoringCategoryProposal.created_at.asc())
        )
    ).scalars().all()
    approved_categories = [
        category
        for category in categories
        if category.status not in (CategoryProposalStatus.removed.value, CategoryProposalStatus.rejected.value)
    ]
    intake = row.raw_intake_json or {}

    existing_client = None
    if row.final_client_id:
        existing_client = await session.get(Client, row.final_client_id)
    if existing_client is None:
        existing_client = (
            await session.execute(select(Client).where(Client.name == profile.canonical_name))
        ).scalar_one_or_none()
    created_or_updated = "updated" if existing_client is not None else "created"

    client = existing_client or Client(name=profile.canonical_name)
    client.messaging_pillars = _dedupe_strings(
        list(profile.opportunity_themes_json or []) + list(intake.get("monitoring_goals") or [])
    )[:12]
    client.risk_keywords = _dedupe_strings(
        list(profile.risk_themes_json or [])
        + [keyword for category in approved_categories for keyword in category.negative_keywords_json]
    )[:20]
    client.audience_profile = {
        "industry": profile.industry,
        "subindustry": profile.subindustry,
        "summary": profile.summary,
        "geographies": intake.get("geographies") or [],
        "monitoring_goals": intake.get("monitoring_goals") or [],
    }
    client.brand_voice_profile = {
        "summary": profile.summary,
        "themes": profile.themes_json,
        "notes": row.notes_input,
        "products": profile.products_json,
    }
    client.competitors = list(profile.competitors_json or [])
    if existing_client is None:
        session.add(client)
        await session.flush()

    profile_row = await session.get(ClientProfile, client.id)
    if profile_row is None:
        profile_row = ClientProfile(client_id=client.id)
        session.add(profile_row)
    profile_row.voice_instructions = (
        f"Speak as {profile.canonical_name} with a crisp, credible PR tone. "
        f"Anchor messaging in {', '.join(profile.opportunity_themes_json[:3]) or 'the approved strategy'}."
    )
    profile_row.compliance_notes = row.notes_input
    profile_row.meta_json = {
        "onboarding_session_id": str(row.id),
        "blueprint_id": str(blueprint.id),
        "canonical_name": profile.canonical_name,
        "industry": profile.industry,
        "channels": profile.channels_json,
        "source_recommendations": blueprint.proposal_json.get("suggested_sources", {}),
    }

    brand_config = (
        await session.execute(select(BrandConfigDB).where(BrandConfigDB.brand_name == profile.canonical_name))
    ).scalar_one_or_none()
    if brand_config is None:
        brand_config = BrandConfigDB(brand_name=profile.canonical_name)
        session.add(brand_config)
        await session.flush()
    brand_config.brand_domains = _extract_domains([profile.website] + list(profile.channels_json.get("social_profiles", [])))
    brand_config.brand_aliases = _build_aliases(profile.canonical_name, profile.website)
    brand_config.key_claims = {
        "summary": profile.summary or "",
        "industry": profile.industry or "",
        "subcategory": profile.subindustry or "",
    }
    brand_config.competitors = list(profile.competitors_json or [])
    brand_config.executive_names = list(profile.executives_json or [])
    brand_config.official_website = profile.website
    brand_config.social_profiles = _dedupe_strings(
        [profile.linkedin_url] + list(profile.channels_json.get("social_profiles", []))
    )

    topic_ids: list[uuid.UUID] = []
    subscription_ids: list[uuid.UUID] = []
    for category in approved_categories:
        topic = (
            await session.execute(
                select(TopicLens).where(TopicLens.client_id == client.id, TopicLens.name == category.title)
            )
        ).scalar_one_or_none()
        if topic is None:
            topic = TopicLens(client_id=client.id, name=category.title)
            session.add(topic)
            await session.flush()
        topic.description = category.description
        topic.keywords = _dedupe_strings(category.keywords_json)
        topic.competitor_overrides = _dedupe_strings(
            list(profile.competitors_json or [])
            if "compet" in category.title.lower()
            else category.entities_json
        )
        topic.risk_flags = _dedupe_strings(
            list(category.negative_keywords_json or [])
            + (list(profile.risk_themes_json or []) if "risk" in category.title.lower() else [])
        )
        topic.opportunity_tags = _dedupe_strings(
            list(profile.opportunity_themes_json or [])
            if "opportunity" in category.title.lower()
            else []
        )
        topic_ids.append(topic.id)

        for target in _materialization_targets(profile=profile, category=category):
            subscription = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.client_id == client.id,
                        Subscription.topic_id == topic.id,
                        Subscription.url == target["url"],
                    )
                )
            ).scalar_one_or_none()
            if subscription is None:
                subscription = Subscription(
                    client_id=client.id,
                    topic_id=topic.id,
                    type=target["type"],
                    name=target["name"],
                    url=target["url"],
                    enabled=True,
                    poll_interval_seconds=target.get("poll_interval_seconds", 1800),
                    fetch_full_content=target.get("fetch_full_content", False),
                    meta_json=target.get("meta_json", {}),
                )
                session.add(subscription)
                await session.flush()
            else:
                subscription.name = target["name"]
                subscription.type = target["type"]
                subscription.enabled = True
                subscription.poll_interval_seconds = target.get("poll_interval_seconds", 1800)
                subscription.fetch_full_content = target.get("fetch_full_content", False)
                subscription.meta_json = target.get("meta_json", {})
            subscription_ids.append(subscription.id)

    signal_route_ids: list[uuid.UUID] = []
    for route in payload.signal_routes:
        recipient_type = route.recipient_type.strip().lower()
        if recipient_type not in {SignalRecipientType.user.value, SignalRecipientType.group.value}:
            raise ValueError("Signal route recipient_type must be 'user' or 'group'")
        enum_recipient_type = SignalRecipientType(recipient_type)
        existing_route = (
            await session.execute(
                select(ClientSignalRoute).where(
                    ClientSignalRoute.client_id == client.id,
                    ClientSignalRoute.recipient_type == enum_recipient_type,
                    ClientSignalRoute.recipient_id == route.recipient_id,
                )
            )
        ).scalar_one_or_none()
        if existing_route is None:
            existing_route = ClientSignalRoute(
                client_id=client.id,
                recipient_type=enum_recipient_type,
                recipient_id=route.recipient_id,
            )
            session.add(existing_route)
            await session.flush()
        existing_route.enabled = route.enabled
        existing_route.from_number = route.from_number
        signal_route_ids.append(existing_route.id)

    row.final_client_id = client.id
    row.status = OnboardingStatus.materialized.value
    await session.commit()
    return MaterializationResultOut(
        client_id=client.id,
        client_name=client.name,
        created_or_updated=created_or_updated,
        topic_ids=_dedupe_ids(topic_ids),
        subscription_ids=_dedupe_ids(subscription_ids),
        signal_route_ids=_dedupe_ids(signal_route_ids),
        brand_config_id=brand_config.id,
    )


async def auto_onboard(
    session: AsyncSession,
    payload: OnboardingIntakeIn,
) -> OnboardingAutoOut:
    detail = await create_onboarding_session(session, payload)
    detail = await resolve_onboarding_session(session, detail.session.id)
    if detail.recommended_candidate is None:
        return OnboardingAutoOut(session=detail, stopped_at=OnboardingStatus.awaiting_company_confirmation.value)

    candidate_gap = 1.0
    if len(detail.candidates) > 1:
        candidate_gap = detail.candidates[0].confidence_score - detail.candidates[1].confidence_score
    auto_confident = (
        detail.recommended_candidate.confidence_score >= 0.72
        and candidate_gap >= 0.12
    )
    if not auto_confident:
        return OnboardingAutoOut(session=detail, stopped_at=OnboardingStatus.awaiting_company_confirmation.value)

    await confirm_resolution_candidate(
        session,
        detail.session.id,
        ConfirmCandidateIn(candidate_id=detail.recommended_candidate.id),
    )
    detail = await enrich_onboarding_session(session, detail.session.id)
    detail = await generate_onboarding_blueprint(session, detail.session.id)
    return OnboardingAutoOut(session=detail, stopped_at=OnboardingStatus.awaiting_user_review.value)


def _build_resolution_candidates(
    *,
    row: OnboardingSession,
    search_hits: list[SearchHit],
    linkedin_hits: list[SearchHit],
) -> list[dict[str, Any]]:
    company_name = row.company_name_input
    candidate_map: dict[str, dict[str, Any]] = {}

    def upsert_candidate(
        *,
        key: str,
        display_name: str,
        canonical_name: str,
        website: Optional[str],
        linkedin_url: Optional[str],
        summary: Optional[str],
        evidence: dict[str, Any],
    ) -> None:
        payload = candidate_map.setdefault(
            key,
            {
                "display_name": display_name or company_name,
                "canonical_name": canonical_name or company_name,
                "website": website,
                "linkedin_url": linkedin_url,
                "summary": summary,
                "confidence_score": 0.0,
                "source_evidence_json": {"evidence": []},
                "is_selected": False,
                "rationale": "",
            },
        )
        if website and not payload.get("website"):
            payload["website"] = website
        if linkedin_url and not payload.get("linkedin_url"):
            payload["linkedin_url"] = linkedin_url
        if summary and (not payload.get("summary") or len(summary) > len(payload["summary"] or "")):
            payload["summary"] = summary
        payload["source_evidence_json"]["evidence"].append(evidence)

    if row.website_input or row.linkedin_url_input:
        domain = _extract_domain(row.website_input or "") or row.company_name_input.lower()
        upsert_candidate(
            key=f"explicit:{domain}",
            display_name=row.company_name_input,
            canonical_name=row.company_name_input,
            website=row.website_input,
            linkedin_url=row.linkedin_url_input,
            summary=row.short_description_input,
            evidence={"source": "operator_input"},
        )

    for hit in search_hits:
        website = None
        linkedin_url = None
        domain = _extract_domain(hit.url)
        if "linkedin.com" in domain:
            linkedin_url = hit.url
            key = f"linkedin:{_slug_from_url(hit.url) or hit.title.lower()}"
        else:
            website = hit.url
            key = domain or hit.title.lower()
        display = _candidate_display_name(hit.title, company_name)
        upsert_candidate(
            key=key,
            display_name=display,
            canonical_name=display,
            website=website,
            linkedin_url=linkedin_url,
            summary=hit.snippet,
            evidence={"source": hit.source, "title": hit.title, "url": hit.url, "snippet": hit.snippet},
        )

    for hit in linkedin_hits:
        key = f"linkedin:{_slug_from_url(hit.url) or hit.title.lower()}"
        display = _candidate_display_name(hit.title, company_name)
        # try attach LinkedIn URL to an existing website candidate with similar display name
        attach_key = None
        for existing_key, existing in candidate_map.items():
            if _name_similarity(existing.get("display_name") or "", display) >= 0.82:
                attach_key = existing_key
                break
        upsert_candidate(
            key=attach_key or key,
            display_name=display,
            canonical_name=display,
            website=None,
            linkedin_url=hit.url,
            summary=hit.snippet,
            evidence={"source": hit.source, "title": hit.title, "url": hit.url, "snippet": hit.snippet},
        )

    candidates = list(candidate_map.values())
    for candidate in candidates:
        candidate["confidence_score"] = _candidate_confidence(row=row, candidate=candidate)
        candidate["rationale"] = _candidate_rationale(row=row, candidate=candidate)

    candidates.sort(key=lambda item: item["confidence_score"], reverse=True)
    if candidates:
        candidates[0]["is_selected"] = len(candidates) == 1 and candidates[0]["confidence_score"] >= 0.8
    return candidates[:6]


async def _build_resolved_company_profile(
    *,
    researcher: PublicWebResearcher,
    row: OnboardingSession,
    candidate: CompanyResolutionCandidate,
    intake: dict[str, Any],
) -> dict[str, Any]:
    pages: list[PageSnapshot] = []
    homepage = await researcher.fetch_page(candidate.website or row.website_input or "")
    if homepage is not None:
        pages.append(homepage)

    candidate_pages = []
    if homepage is not None:
        for link in homepage.links:
            url = link["url"]
            lowered = url.lower()
            if _same_domain(candidate.website, url) and any(
                hint in lowered for hint in ("/about", "/company", "/team", "/press", "/news", "/blog", "/products", "/solutions")
            ):
                candidate_pages.append(url)
    for url in _dedupe_strings(candidate_pages)[:5]:
        extra = await researcher.fetch_page(url)
        if extra is not None:
            pages.append(extra)

    competitor_hits = await researcher.search_web(f"competitors to {candidate.canonical_name}", limit=5)
    news_hits = await researcher.search_web(f"{candidate.canonical_name} news industry", limit=5)
    combined_text = " ".join(
        _clean_text(part)
        for part in [
            row.short_description_input,
            candidate.summary,
            *(page.description for page in pages),
            *(page.text_excerpt for page in pages),
            *(hit.snippet for hit in news_hits),
        ]
        if part
    )
    industry, subindustry = _infer_industry(combined_text, intake.get("industry"))
    executives = _dedupe_strings(list(intake.get("executives") or []) + _extract_executives_from_text(combined_text))
    products = _dedupe_strings(list(intake.get("products") or []) + _extract_products_from_pages(pages))
    competitors = _dedupe_strings(list(intake.get("competitors") or []) + _extract_competitors(candidate.website, competitor_hits))
    themes = _dedupe_strings(
        list(intake.get("monitoring_goals") or []) + _infer_themes(combined_text, industry, products=products)
    )
    risk_themes = _dedupe_strings(
        _INDUSTRY_RISK_THEMES.get(industry or "", []) + _infer_risk_themes(combined_text)
    )
    opportunity_themes = _dedupe_strings(
        _INDUSTRY_OPPORTUNITY_THEMES.get(industry or "", []) + _infer_opportunity_themes(combined_text, intake)
    )
    channels = _build_channels_json(
        candidate=candidate,
        pages=pages,
        news_hits=news_hits,
        competitor_hits=competitor_hits,
    )
    summary = _pick_summary(
        explicit_summary=row.short_description_input,
        candidate_summary=candidate.summary,
        homepage=homepage,
        combined_text=combined_text,
        industry=industry,
    )
    profile = {
        "canonical_name": candidate.canonical_name,
        "website": candidate.website or row.website_input,
        "linkedin_url": candidate.linkedin_url or row.linkedin_url_input,
        "summary": summary,
        "industry": industry,
        "subindustry": subindustry,
        "products_json": products,
        "executives_json": executives,
        "competitors_json": competitors,
        "channels_json": channels,
        "themes_json": themes,
        "risk_themes_json": risk_themes,
        "opportunity_themes_json": opportunity_themes,
        "source_evidence_json": {
            "candidate": candidate.source_evidence_json,
            "pages": [
                {
                    "url": page.url,
                    "title": page.title,
                    "description": page.description,
                }
                for page in pages
            ],
            "competitor_hits": [hit.__dict__ for hit in competitor_hits],
            "news_hits": [hit.__dict__ for hit in news_hits],
        },
        "confidence_json": {
            "resolution_confidence": candidate.confidence_score,
            "page_count": len(pages),
            "industry_inferred": bool(industry),
            "products_count": len(products),
            "executives_count": len(executives),
        },
    }
    llm_overlay = await _maybe_llm_profile_overlay(intake=intake, profile=profile)
    if llm_overlay:
        for key in (
            "summary",
            "industry",
            "subindustry",
            "products_json",
            "executives_json",
            "competitors_json",
            "themes_json",
            "risk_themes_json",
            "opportunity_themes_json",
        ):
            if llm_overlay.get(key):
                profile[key] = llm_overlay[key]
        profile["confidence_json"]["llm_refined"] = True
    return profile


async def _maybe_llm_profile_overlay(*, intake: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    llm = build_llm_client()
    if llm is None:
        return {}
    system = (
        "You are a company research analyst. Refine a deterministic company profile into a concise, structured output. "
        "Only use evidence provided. Do not invent executives or products."
    )
    user = json.dumps(
        {
            "intake": intake,
            "profile": profile,
        },
        ensure_ascii=False,
    )
    schema = {
        "name": "resolved_company_profile_overlay",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "industry": {"type": "string"},
                "subindustry": {"type": "string"},
                "products_json": {"type": "array", "items": {"type": "string"}},
                "executives_json": {"type": "array", "items": {"type": "string"}},
                "competitors_json": {"type": "array", "items": {"type": "string"}},
                "themes_json": {"type": "array", "items": {"type": "string"}},
                "risk_themes_json": {"type": "array", "items": {"type": "string"}},
                "opportunity_themes_json": {"type": "array", "items": {"type": "string"}},
            },
        },
    }
    try:
        payload, _ = await llm.generate_json(system=system, user=user, json_schema=schema)
        return payload
    except Exception:
        return {}


async def _maybe_llm_blueprint_overlay(
    *,
    row: OnboardingSession,
    profile: ResolvedCompanyProfile,
    proposal_json: dict[str, Any],
) -> dict[str, Any]:
    llm = build_llm_client()
    if llm is None:
        return {}
    system = (
        "You are a PR strategy onboarding agent. Refine a monitoring blueprint. "
        "Preserve deterministic facts and categories, but improve summary, rationale, and review framing."
    )
    user = json.dumps(
        {
            "company_name": row.company_name_input,
            "notes": row.notes_input,
            "profile": {
                "canonical_name": profile.canonical_name,
                "industry": profile.industry,
                "summary": profile.summary,
                "themes": profile.themes_json,
                "risk_themes": profile.risk_themes_json,
                "opportunity_themes": profile.opportunity_themes_json,
            },
            "proposal_json": proposal_json,
        },
        ensure_ascii=False,
    )
    schema = {
        "name": "monitoring_blueprint_overlay",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "rationale": {"type": "string"},
                "proposal_json": {"type": "object"},
            },
        },
    }
    try:
        payload, _ = await llm.generate_json(system=system, user=user, json_schema=schema)
        return payload
    except Exception:
        return {}


def _build_category_proposals(
    *,
    row: OnboardingSession,
    profile: ResolvedCompanyProfile,
    intake: dict[str, Any],
) -> list[dict[str, Any]]:
    aliases = _build_aliases(profile.canonical_name, profile.website)
    company_entities = _dedupe_strings([profile.canonical_name, row.company_name_input] + aliases)
    direct_sources = _sort_sources(
        ["official_website", "press", "blog"]
        + (["linkedin"] if profile.linkedin_url else [])
        + (["news"] if profile.channels_json.get("trade_publications") else [])
    )
    direct_queries = _sample_queries(company_entities[:3], extras=[profile.industry or ""])
    categories: list[dict[str, Any]] = [
        {
            "title": "Direct Company Signals",
            "description": "Track direct company mentions, aliases, official page updates, and press references.",
            "priority": "high",
            "rationale": "This is the core visibility layer and the fastest path to brand and press signal detection.",
            "sensitivity": "high",
            "recommended_sources_json": direct_sources,
            "entities_json": company_entities,
            "keywords_json": _dedupe_strings(company_entities + list(profile.themes_json[:4])),
            "negative_keywords_json": _negative_keywords_for_name(row.company_name_input),
            "sample_queries_json": direct_queries,
            "status": CategoryProposalStatus.proposed.value,
        },
    ]
    if profile.executives_json:
        categories.append(
            {
                "title": "Executive Visibility",
                "description": "Track executive mentions, interviews, posts, and leadership commentary.",
                "priority": "high",
                "rationale": "Executive presence is often the earliest PR leverage point and a leading indicator of reputation risk.",
                "sensitivity": "high",
                "recommended_sources_json": _sort_sources(["linkedin", "news", "blog", "official_website"]),
                "entities_json": list(profile.executives_json),
                "keywords_json": _dedupe_strings(
                    list(profile.executives_json) + [f"{profile.canonical_name} CEO", f"{profile.canonical_name} founder"]
                ),
                "negative_keywords_json": [],
                "sample_queries_json": _sample_queries(list(profile.executives_json), extras=[profile.canonical_name]),
                "status": CategoryProposalStatus.proposed.value,
            }
        )
    if profile.products_json or "product" in " ".join(profile.themes_json).lower():
        categories.append(
            {
                "title": "Product & Offering Narrative",
                "description": "Track product names, launches, feature mentions, solution framing, and customer use-case discussion.",
                "priority": "high",
                "rationale": "Product narratives drive both earned coverage and category positioning.",
                "sensitivity": "medium",
                "recommended_sources_json": _sort_sources(["official_website", "blog", "news", "trade_publications"]),
                "entities_json": list(profile.products_json),
                "keywords_json": _dedupe_strings(list(profile.products_json) + list(profile.themes_json[:4])),
                "negative_keywords_json": [],
                "sample_queries_json": _sample_queries(list(profile.products_json) or list(profile.themes_json[:2]), extras=[profile.canonical_name]),
                "status": CategoryProposalStatus.proposed.value,
            }
        )
    if profile.competitors_json:
        categories.append(
            {
                "title": "Competitive Landscape",
                "description": "Track competitor announcements, positioning shifts, and shared market conversations.",
                "priority": "high",
                "rationale": "Competitive context sharpens opportunity timing and share-of-voice analysis.",
                "sensitivity": "medium",
                "recommended_sources_json": _sort_sources(["competitor_channels", "news", "trade_publications", "blog"]),
                "entities_json": list(profile.competitors_json),
                "keywords_json": _dedupe_strings(list(profile.competitors_json) + [profile.canonical_name]),
                "negative_keywords_json": [],
                "sample_queries_json": _sample_queries(list(profile.competitors_json[:3]), extras=[profile.canonical_name]),
                "status": CategoryProposalStatus.proposed.value,
            }
        )
    categories.append(
        {
            "title": "Industry Narrative",
            "description": "Track major industry themes, regulation, policy, funding, and emerging trend narratives.",
            "priority": "medium",
            "rationale": "Broader industry narrative coverage creates context for response strategy and proactive storytelling.",
            "sensitivity": "medium",
            "recommended_sources_json": _sort_sources(["trade_publications", "news", "blog"]),
            "entities_json": [profile.industry] if profile.industry else [],
            "keywords_json": _dedupe_strings(list(profile.themes_json) + [profile.industry or "", profile.subindustry or ""]),
            "negative_keywords_json": [],
            "sample_queries_json": _sample_queries(list(profile.themes_json[:3]), extras=[profile.industry or ""]),
            "status": CategoryProposalStatus.proposed.value,
        }
    )
    categories.append(
        {
            "title": "Reputation & Risk",
            "description": "Track controversy markers, complaints, legal/regulatory escalation, and critical sentiment themes.",
            "priority": "high",
            "rationale": "Risk detection is time-sensitive and needs higher alerting sensitivity than broad narrative monitoring.",
            "sensitivity": "high",
            "recommended_sources_json": _sort_sources(["news", "linkedin", "official_website", "blog"]),
            "entities_json": company_entities[:3],
            "keywords_json": _dedupe_strings(company_entities[:3] + list(profile.risk_themes_json)),
            "negative_keywords_json": [],
            "sample_queries_json": _sample_queries(list(profile.risk_themes_json[:4]), extras=[profile.canonical_name]),
            "status": CategoryProposalStatus.proposed.value,
        }
    )
    categories.append(
        {
            "title": "Opportunity & Thought Leadership",
            "description": "Track under-owned conversations, media angles, and thought-leadership openings the brand can credibly own.",
            "priority": "medium",
            "rationale": "This category surfaces proactive PR opportunities rather than only reactive monitoring.",
            "sensitivity": "digest_only",
            "recommended_sources_json": _sort_sources(["trade_publications", "blog", "linkedin", "news"]),
            "entities_json": [profile.canonical_name],
            "keywords_json": _dedupe_strings(list(profile.opportunity_themes_json) + list(intake.get("monitoring_goals") or [])),
            "negative_keywords_json": [],
            "sample_queries_json": _sample_queries(list(profile.opportunity_themes_json[:3]), extras=[profile.industry or ""]),
            "status": CategoryProposalStatus.proposed.value,
        }
    )
    categories.sort(key=lambda item: _PRIORITY_ORDER.get(item["priority"], 99))
    return categories


def _build_proposal_json(
    *,
    row: OnboardingSession,
    profile: ResolvedCompanyProfile,
    categories: list[dict[str, Any]],
    intake: dict[str, Any],
) -> dict[str, Any]:
    approved_sources = _sort_sources(
        _dedupe_strings([source for category in categories for source in category["recommended_sources_json"]])
    )
    risks = []
    if len(row.company_name_input.split()) <= 1:
        risks.append("Brand name is broad and may require extra negative keywords to reduce noise.")
    if not profile.competitors_json:
        risks.append("Competitor inference is incomplete and may need operator refinement.")
    if not profile.linkedin_url:
        risks.append("LinkedIn company profile was not confidently resolved from public signals.")
    if not profile.channels_json.get("trade_publications"):
        risks.append("Trade publication discovery is partial; source landscape can be expanded over time.")

    return {
        "company_identity": {
            "who_we_believe_the_company_is": profile.canonical_name,
            "website": profile.website,
            "linkedin_url": profile.linkedin_url,
            "category": profile.industry,
            "confidence": profile.confidence_json,
            "summary": profile.summary,
        },
        "recommended_monitoring_strategy": {
            "summary": (
                f"Monitor {profile.canonical_name} across direct signals, leadership, product narrative, "
                f"industry context, risk markers, and opportunity themes."
            ),
            "rationale": (
                "The proposed mix prioritizes direct visibility and reputational timing first, then adds narrative "
                "and competitive context to make the monitoring output more strategic."
            ),
            "categories": [
                {"title": category["title"], "priority": category["priority"], "why": category["rationale"]}
                for category in categories
            ],
        },
        "suggested_things_to_track": {
            "company_names_and_aliases": _build_aliases(profile.canonical_name, profile.website),
            "executives": list(profile.executives_json),
            "products": list(profile.products_json),
            "competitors": list(profile.competitors_json),
            "topic_terms": list(profile.themes_json),
            "risk_terms": list(profile.risk_themes_json),
        },
        "suggested_sources": {
            "channels": approved_sources,
            "official_pages": profile.channels_json.get("official_pages", []),
            "press_pages": profile.channels_json.get("press_pages", []),
            "blog_pages": profile.channels_json.get("blog_pages", []),
            "trade_publications": profile.channels_json.get("trade_publications", []),
        },
        "suggested_alert_sensitivity": {
            "high_sensitivity": [category["title"] for category in categories if category["sensitivity"] == "high"],
            "medium_sensitivity": [category["title"] for category in categories if category["sensitivity"] == "medium"],
            "low_sensitivity": [category["title"] for category in categories if category["sensitivity"] == "low"],
            "digest_only": [category["title"] for category in categories if category["sensitivity"] == "digest_only"],
        },
        "risks_and_ambiguities": risks,
        "review_actions": [
            "approve all",
            "approve with edits",
            "remove category",
            "add category",
            "reject blueprint",
        ],
        "operator_notes": intake.get("notes") or row.notes_input,
        "overall_confidence": _overall_confidence(profile),
    }


async def _apply_blueprint_edits(
    session: AsyncSession,
    *,
    blueprint: MonitoringBlueprintProposal,
    diff_json: dict[str, Any],
) -> None:
    if not diff_json:
        return
    if diff_json.get("summary") is not None:
        blueprint.summary = str(diff_json["summary"])
    if diff_json.get("rationale") is not None:
        blueprint.rationale = str(diff_json["rationale"])
    if diff_json.get("proposal_json") is not None and isinstance(diff_json["proposal_json"], dict):
        blueprint.proposal_json = diff_json["proposal_json"]

    profile_patch = diff_json.get("company_profile")
    if isinstance(profile_patch, dict):
        profile = await session.get(ResolvedCompanyProfile, blueprint.company_profile_id)
        if profile is not None:
            for key, value in profile_patch.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)

    categories_patch = diff_json.get("categories")
    if isinstance(categories_patch, list):
        existing_categories = {
            str(category.id): category
            for category in (
                await session.execute(
                    select(MonitoringCategoryProposal).where(MonitoringCategoryProposal.blueprint_id == blueprint.id)
                )
            ).scalars().all()
        }
        for raw_patch in categories_patch:
            patch = MonitoringCategoryProposalPatch.model_validate(raw_patch)
            if patch.id is not None and str(patch.id) in existing_categories:
                category = existing_categories[str(patch.id)]
            else:
                category = MonitoringCategoryProposal(blueprint_id=blueprint.id)
                session.add(category)
            category.title = patch.title
            category.description = patch.description
            category.priority = patch.priority
            category.rationale = patch.rationale
            category.sensitivity = patch.sensitivity
            category.recommended_sources_json = patch.recommended_sources_json
            category.entities_json = patch.entities_json
            category.keywords_json = patch.keywords_json
            category.negative_keywords_json = patch.negative_keywords_json
            category.sample_queries_json = patch.sample_queries_json
            category.status = patch.status


async def _set_category_statuses(session: AsyncSession, blueprint_id: uuid.UUID, *, approved: bool) -> None:
    categories = (
        await session.execute(
            select(MonitoringCategoryProposal).where(MonitoringCategoryProposal.blueprint_id == blueprint_id)
        )
    ).scalars().all()
    for category in categories:
        if category.status not in (CategoryProposalStatus.removed.value, CategoryProposalStatus.rejected.value):
            category.status = CategoryProposalStatus.approved.value if approved else CategoryProposalStatus.proposed.value


async def _set_single_category_status(session: AsyncSession, category_id: str, status: str) -> None:
    category = await session.get(MonitoringCategoryProposal, uuid.UUID(category_id))
    if category is not None:
        category.status = status


def _materialization_targets(
    *,
    profile: ResolvedCompanyProfile,
    category: MonitoringCategoryProposal,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    official_pages = list(profile.channels_json.get("official_pages", []))
    press_pages = list(profile.channels_json.get("press_pages", []))
    blog_pages = list(profile.channels_json.get("blog_pages", []))
    competitor_urls = list(profile.channels_json.get("competitor_urls", []))

    def add_target(name: str, url: str, sub_type: SubscriptionType, meta_json: Optional[dict[str, Any]] = None) -> None:
        if not url:
            return
        targets.append(
            {
                "name": name,
                "url": url,
                "type": sub_type,
                "fetch_full_content": sub_type == SubscriptionType.web_link_discovery,
                "poll_interval_seconds": 1800 if category.priority == "high" else 3600,
                "meta_json": meta_json or {"onboarding_source": True, "category": category.title},
            }
        )

    if category.title == "Direct Company Signals":
        for url in official_pages[:1]:
            add_target("Official Website", url, SubscriptionType.web_page_diff)
        for url in press_pages[:2]:
            add_target("Press Page", url, SubscriptionType.web_link_discovery)
        for url in blog_pages[:2]:
            add_target("Company Blog", url, SubscriptionType.web_link_discovery)
        if profile.linkedin_url:
            add_target("Company LinkedIn", profile.linkedin_url, SubscriptionType.web_page_diff)
    elif category.title == "Executive Visibility":
        if profile.linkedin_url:
            add_target("Executive / Company LinkedIn", profile.linkedin_url, SubscriptionType.web_page_diff)
        for url in [page for page in official_pages if any(hint in page.lower() for hint in ("/team", "/leadership", "/about"))][:2]:
            add_target("Leadership Page", url, SubscriptionType.web_page_diff)
    elif category.title == "Product & Offering Narrative":
        for url in [page for page in official_pages if any(hint in page.lower() for hint in ("/product", "/products", "/solutions"))][:2]:
            add_target("Product Page", url, SubscriptionType.web_link_discovery)
        for url in blog_pages[:2]:
            add_target("Product Blog", url, SubscriptionType.web_link_discovery)
    elif category.title == "Competitive Landscape":
        for url in competitor_urls[:3]:
            add_target("Competitor Website", url, SubscriptionType.web_page_diff, {"competitor_watch": True, "category": category.title})
    elif category.title == "Industry Narrative":
        for url in list(profile.channels_json.get("trade_publications", []))[:2]:
            add_target("Trade Publication", url, SubscriptionType.web_link_discovery)
    elif category.title == "Reputation & Risk":
        for url in press_pages[:1] + official_pages[:1]:
            add_target("Risk Watch Source", url, SubscriptionType.web_page_diff)
    elif category.title == "Opportunity & Thought Leadership":
        for url in blog_pages[:2] + list(profile.channels_json.get("trade_publications", []))[:1]:
            add_target("Thought Leadership Source", url, SubscriptionType.web_link_discovery)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        key = f"{target['type'].value}:{target['url']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _build_channels_json(
    *,
    candidate: CompanyResolutionCandidate,
    pages: list[PageSnapshot],
    news_hits: list[SearchHit],
    competitor_hits: list[SearchHit],
) -> dict[str, Any]:
    official_pages = _dedupe_strings([page.url for page in pages])
    press_pages = _dedupe_strings([page.url for page in pages if any(hint in page.url.lower() for hint in ("/press", "/news", "/media"))])
    blog_pages = _dedupe_strings([page.url for page in pages if "/blog" in page.url.lower()])
    social_profiles = _dedupe_strings(
        [
            link["url"]
            for page in pages
            for link in page.links
            if any(host in link["url"] for host in ("linkedin.com", "twitter.com", "x.com", "youtube.com", "facebook.com"))
        ]
        + ([candidate.linkedin_url] if candidate.linkedin_url else [])
    )
    trade_publications = _dedupe_strings(
        [
            hit.url
            for hit in news_hits
            if _extract_domain(hit.url)
            and _extract_domain(hit.url) not in {_extract_domain(candidate.website or ""), "linkedin.com"}
        ]
    )
    competitor_urls = _dedupe_strings([hit.url for hit in competitor_hits])
    return {
        "official_pages": official_pages,
        "press_pages": press_pages,
        "blog_pages": blog_pages,
        "social_profiles": social_profiles,
        "trade_publications": trade_publications,
        "competitor_urls": competitor_urls,
    }


def _pick_summary(
    *,
    explicit_summary: Optional[str],
    candidate_summary: Optional[str],
    homepage: Optional[PageSnapshot],
    combined_text: str,
    industry: Optional[str],
) -> str:
    if explicit_summary:
        return explicit_summary.strip()
    if homepage and homepage.description:
        return homepage.description
    if candidate_summary:
        return candidate_summary.strip()
    if combined_text:
        text = combined_text[:260].strip()
        if industry and industry.lower() not in text.lower():
            return f"{text} Industry context suggests {industry}."
        return text
    return "Public company profile generated from operator input and web evidence."


def _infer_industry(text: str, explicit_industry: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if explicit_industry:
        return explicit_industry.strip(), None
    lowered = (text or "").lower()
    for rule in _INDUSTRY_RULES:
        if any(keyword in lowered for keyword in rule["keywords"]):
            return rule["industry"], rule["subindustry"]
    return None, None


def _infer_themes(text: str, industry: Optional[str], *, products: list[str]) -> list[str]:
    lowered = (text or "").lower()
    themes: list[str] = []
    for candidate in (
        "thought leadership",
        "regulation",
        "funding",
        "product launch",
        "customer proof",
        "market education",
        "partnerships",
        "innovation",
    ):
        if candidate in lowered:
            themes.append(candidate)
    if industry:
        themes.append(f"{industry.lower()} narrative")
    if products:
        themes.append("product narrative")
    return themes


def _infer_risk_themes(text: str) -> list[str]:
    lowered = (text or "").lower()
    candidates = [
        "regulatory scrutiny",
        "pricing backlash",
        "customer complaints",
        "security concerns",
        "legal escalation",
        "brand confusion",
        "negative sentiment",
    ]
    return [candidate for candidate in candidates if candidate.split()[0] in lowered]


def _infer_opportunity_themes(text: str, intake: dict[str, Any]) -> list[str]:
    lowered = (text or "").lower()
    themes = list(intake.get("monitoring_goals") or [])
    if "thought leadership" in lowered or "thought leadership" in themes:
        themes.append("thought leadership")
    if "category" in lowered:
        themes.append("category framing")
    if "innovation" in lowered:
        themes.append("innovation narrative")
    if "media" in lowered:
        themes.append("media angle development")
    return themes


def _extract_executives_from_text(text: str) -> list[str]:
    return _dedupe_strings([match.group(1) for match in _EXECUTIVE_RE.finditer(text or "")])


def _extract_products_from_pages(pages: list[PageSnapshot]) -> list[str]:
    products: list[str] = []
    for page in pages:
        for link in page.links:
            text = _clean_text(link["text"])
            lowered_url = link["url"].lower()
            if any(hint in lowered_url for hint in ("/product", "/products", "/solution", "/solutions")) and 2 <= len(text.split()) <= 5:
                products.append(text)
    return _dedupe_strings(products)


def _extract_competitors(website: Optional[str], hits: list[SearchHit]) -> list[str]:
    own_domain = _extract_domain(website or "")
    competitors: list[str] = []
    urls: list[str] = []
    for hit in hits:
        domain = _extract_domain(hit.url)
        if not domain or domain == own_domain or "linkedin.com" in domain:
            continue
        display = _candidate_display_name(hit.title, "")
        if display:
            competitors.append(display)
        urls.append(hit.url)
    deduped = _dedupe_strings(competitors)[:6]
    return deduped


def _candidate_confidence(*, row: OnboardingSession, candidate: dict[str, Any]) -> float:
    score = 0.25
    name = candidate.get("canonical_name") or candidate.get("display_name") or ""
    score += 0.35 * _name_similarity(row.company_name_input, name)
    if candidate.get("website"):
        score += 0.15
    if candidate.get("linkedin_url"):
        score += 0.1
    if row.website_input and candidate.get("website") and _same_domain(row.website_input, candidate["website"]):
        score += 0.2
    if row.linkedin_url_input and candidate.get("linkedin_url") and _clean_url(row.linkedin_url_input) == _clean_url(candidate["linkedin_url"]):
        score += 0.15
    if candidate.get("summary"):
        score += 0.05
    return round(min(score, 0.99), 2)


def _candidate_rationale(*, row: OnboardingSession, candidate: dict[str, Any]) -> str:
    parts = []
    if candidate.get("website"):
        parts.append("website result")
    if candidate.get("linkedin_url"):
        parts.append("LinkedIn evidence")
    if _name_similarity(row.company_name_input, candidate.get("canonical_name") or "") >= 0.9:
        parts.append("strong name match")
    if row.website_input and candidate.get("website") and _same_domain(row.website_input, candidate["website"]):
        parts.append("operator website alignment")
    if candidate.get("summary"):
        parts.append("supporting summary evidence")
    if not parts:
        parts.append("fallback candidate")
    return ", ".join(parts).capitalize() + "."


def _candidate_display_name(title: str, company_name: str) -> str:
    cleaned = re.split(r"\s+[|\-–]\s+", title or "", maxsplit=1)[0].strip()
    if not cleaned:
        return company_name
    return _SPACE_RE.sub(" ", cleaned)


def _negative_keywords_for_name(company_name: str) -> list[str]:
    negatives = list(_COMMON_NEGATIVE_KEYWORDS)
    if len(company_name.split()) <= 1:
        negatives.extend(["song", "movie", "dictionary"])
    return _dedupe_strings(negatives)


def _sample_queries(phrases: list[str], *, extras: list[str]) -> list[str]:
    queries: list[str] = []
    for phrase in phrases:
        if not phrase:
            continue
        queries.append(f"\"{phrase}\"")
        for extra in extras:
            if extra:
                queries.append(f"\"{phrase}\" AND \"{extra}\"")
                break
        if len(queries) >= 5:
            break
    return _dedupe_strings(queries)[:5]


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


def _build_disambiguation_prompt(candidates: list[CompanyResolutionCandidateOut]) -> Optional[str]:
    if len(candidates) < 2:
        return None
    if candidates[0].confidence_score >= 0.8 and candidates[0].confidence_score - candidates[1].confidence_score >= 0.12:
        return None
    labels = []
    for candidate in candidates[:3]:
        descriptor = candidate.website or candidate.linkedin_url or candidate.summary or "no public reference"
        labels.append(f"{candidate.display_name} ({descriptor})")
    return "Confirm the intended company: " + "; ".join(labels)


def _decision_out(decision: BlueprintReviewDecision) -> Any:
    from pr_monitor_app.onboarding_schemas import BlueprintReviewDecisionOut

    return BlueprintReviewDecisionOut.model_validate(decision)


async def _blueprint_out(
    session: AsyncSession,
    blueprint: MonitoringBlueprintProposal,
) -> MonitoringBlueprintProposalOut:
    categories = (
        await session.execute(
            select(MonitoringCategoryProposal)
            .where(MonitoringCategoryProposal.blueprint_id == blueprint.id)
            .order_by(MonitoringCategoryProposal.created_at.asc())
        )
    ).scalars().all()
    return MonitoringBlueprintProposalOut(
        id=blueprint.id,
        onboarding_session_id=blueprint.onboarding_session_id,
        company_profile_id=blueprint.company_profile_id,
        proposal_version=blueprint.proposal_version,
        summary=blueprint.summary,
        overall_confidence=blueprint.overall_confidence,
        rationale=blueprint.rationale,
        proposal_json=blueprint.proposal_json or {},
        categories=[MonitoringCategoryProposalOut.model_validate(category) for category in categories],
        created_at=blueprint.created_at,
        updated_at=blueprint.updated_at,
    )


async def _load_latest_blueprint(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> Optional[MonitoringBlueprintProposal]:
    return (
        await session.execute(
            select(MonitoringBlueprintProposal)
            .where(MonitoringBlueprintProposal.onboarding_session_id == onboarding_session_id)
            .order_by(MonitoringBlueprintProposal.proposal_version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_selected_candidate(
    session: AsyncSession,
    onboarding_session_id: uuid.UUID,
) -> Optional[CompanyResolutionCandidate]:
    return (
        await session.execute(
            select(CompanyResolutionCandidate).where(
                CompanyResolutionCandidate.onboarding_session_id == onboarding_session_id,
                CompanyResolutionCandidate.is_selected.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _get_session_or_raise(session: AsyncSession, onboarding_session_id: uuid.UUID) -> OnboardingSession:
    row = await session.get(OnboardingSession, onboarding_session_id)
    if row is None:
        raise ValueError("Onboarding session not found")
    return row


def _overall_confidence(profile: ResolvedCompanyProfile) -> float:
    resolution = float((profile.confidence_json or {}).get("resolution_confidence") or 0.5)
    signal_bonus = 0.05 * min(len(profile.products_json) + len(profile.executives_json) + len(profile.competitors_json), 4)
    return round(min(resolution + signal_bonus, 0.96), 2)


def _intake_to_json(payload: OnboardingIntakeIn) -> dict[str, Any]:
    data = payload.model_dump()
    data["website"] = _clean_url(data.get("website"))
    data["linkedin_url"] = _clean_url(data.get("linkedin_url"))
    data["short_description"] = _clean_text(data.get("short_description"))
    data["notes"] = _clean_text(data.get("notes"))
    for key in ("competitors", "executives", "products", "geographies", "monitoring_goals"):
        data[key] = _dedupe_strings(data.get(key) or [])
    return data


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
    if not re.match(r"^[a-z]+://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    try:
        parsed = httpx.URL(candidate)
    except Exception:
        return None
    return parsed.human_repr()


def _extract_domain(url: str) -> str:
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return ""
    hostname = hostname.lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def _same_domain(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    return _extract_domain(left) == _extract_domain(right)


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    return path.split("/")[-1]


def _name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_name(left), _normalize_name(right)).ratio()


def _normalize_name(value: str) -> str:
    lowered = _COMPANY_SUFFIX_RE.sub("", value or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _dedupe_strings(values: Iterable[Optional[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _dedupe_ids(values: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_dict_links(values: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        key = value["url"]
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _sort_sources(values: list[str]) -> list[str]:
    return sorted(_dedupe_strings(values), key=lambda item: _SOURCE_PRIORITY.get(item, 99))


def _extract_domains(urls: Iterable[Optional[str]]) -> list[str]:
    return _dedupe_strings([_extract_domain(url or "") for url in urls if _extract_domain(url or "")])


def _merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
