from __future__ import annotations

from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pr_monitor_app.llm.openai_compat import build_llm_client
from pr_monitor_app.models import AlertTier, Client, ClientEvent, CreativeDraftSet, EngagementMode, Event, StrategicBrief, TopicLens
from pr_monitor_app.pipeline.guardrails import run_guardrails
from pr_monitor_app.utils.text import normalize_text

log = structlog.get_logger(__name__)


_BRIEF_JSON_SCHEMA = {
    "name": "npe_brief_and_drafts",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "event_summary": {"type": "string"},
            "strategic_analysis": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "why_it_matters": {"type": "string"},
                    "opportunity_vector": {"type": "string"},
                    "risk_vector": {"type": "string"},
                    "recommended_stance": {"type": "string"},
                    "engagement_mode_recommendation": {
                        "type": "string",
                        "enum": ["comment", "independent_post", "thread", "journalist_outreach", "stay_silent"],
                    },
                    "angle_generator": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"name": {"type": "string"}, "angle": {"type": "string"}}},
                    },
                },
                "required": ["why_it_matters", "opportunity_vector", "risk_vector", "recommended_stance", "engagement_mode_recommendation"],
            },
            "confidence": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "verified_facts_used": {"type": "array", "items": {"type": "string"}},
                    "assumptions_made": {"type": "array", "items": {"type": "string"}},
                    "risk_level": {"type": "string", "enum": ["Low", "Moderate", "Sensitive"]},
                    "notes": {"type": "string"},
                },
                "required": ["verified_facts_used", "assumptions_made", "risk_level"],
            },
            "linkedin_comments": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "micro_insight": {"type": "string"},
                    "contrarian": {"type": "string"},
                    "framework": {"type": "string"},
                    "narrative_amplifier": {"type": "string"},
                    "question_driven": {"type": "string"},
                },
                "required": ["micro_insight", "contrarian", "framework", "narrative_amplifier", "question_driven"],
            },
            "independent_posts": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rapid_response": {"type": "string"},
                    "founder_story": {"type": "string"},
                    "industry_framework": {"type": "string"},
                },
                "required": ["rapid_response", "founder_story", "industry_framework"],
            },
        },
        "required": ["event_summary", "strategic_analysis", "confidence", "linkedin_comments", "independent_posts"],
    },
}


def _fallback_brief_and_drafts(client: Client, topic: TopicLens, event: Event, client_event: ClientEvent) -> dict[str, Any]:
    """
    Deterministic fallback that still produces usable output (when LLM disabled).
    """
    title = event.title or "Update"
    why = f"This touches {topic.name} and intersects with {', '.join((client.messaging_pillars or [])[:2]) or 'your messaging priorities'}."
    opp = "Add a grounded perspective and clarify implications for practitioners. Offer a small actionable takeaway."
    risk = "Avoid overstating certainty; don't claim numbers not present in the source; keep regulatory language cautious."
    stance = "Measured, practical, and slightly forward-looking. Emphasize responsible adoption and second-order effects."
    engagement_mode = "comment" if client_event.tier in (AlertTier.P0, AlertTier.P1) else "independent_post"

    angles = [
        {"name": "Authority reinforcement", "angle": "Anchor on first principles and highlight what practitioners should do next."},
        {"name": "Market reframing", "angle": "Shift from hype to operational reality and incentives."},
        {"name": "Data interpretation", "angle": "Interpret what is known vs unknown; ask for better measurement."},
        {"name": "Narrative tension", "angle": "Point out the trade-off or paradox that most miss."},
        {"name": "Future projection", "angle": "Project the next 6–12 months and what leaders should prepare for."},
    ]

    comments = {
        "micro_insight": f"Interesting development on {topic.name}. The real unlock is translating this into day-to-day decision rules, not abstract debate.",
        "contrarian": f"One nuance: the headline takeaway may be overstated—what matters is how this changes incentives and enforcement in practice.",
        "framework": "A quick lens:\n1) What changes now (policy/product)\n2) Who bears the cost\n3) What the operating playbook should be",
        "narrative_amplifier": f"This feels like another step in the broader shift toward {topic.name} becoming an execution discipline, not a talking point.",
        "question_driven": "Curious—what do you think will be the first real-world constraint teams feel from this: compliance burden, liability risk, or go-to-market friction?",
    }

    posts = {
        "rapid_response": f"{title}\n\nA quick take: {why}\n\n{opp}\n\nWhat I'd watch next: implementation details, enforcement signals, and how the strongest teams operationalize it without slowing shipping.\n\nWhat are you seeing on your side?",
        "founder_story": "I’ve seen this pattern before: a new framework lands, everyone debates it, and then the winners quietly turn it into a checklist.\n\nThe question isn’t “is it good?”—it’s “what’s the minimum operating system that keeps us moving while staying responsible?”\n\nThat’s where teams build trust and speed at the same time.",
        "industry_framework": "A simple positioning frame:\n\n• Reality: the surface headline is rarely the constraint\n• Constraint: incentives + enforcement shape behavior\n• Advantage: the teams who operationalize early set the norms\n\nIf you lead this shift with clarity, you earn disproportionate credibility.",
    }

    return {
        "event_summary": normalize_text(event.raw_text[:420]),
        "strategic_analysis": {
            "why_it_matters": why,
            "opportunity_vector": opp,
            "risk_vector": risk,
            "recommended_stance": stance,
            "engagement_mode_recommendation": engagement_mode,
            "angle_generator": angles,
        },
        "confidence": {
            "verified_facts_used": [title],
            "assumptions_made": ["Assumed typical industry implications; verify specifics before making claims."],
            "risk_level": "Moderate" if client_event.tier == AlertTier.P0 else "Low",
            "notes": "Fallback mode (LLM disabled).",
        },
        "linkedin_comments": comments,
        "independent_posts": posts,
    }


async def generate_briefs_and_drafts(session: AsyncSession, *, limit: int = 100) -> dict[str, Any]:
    """
    For ClientEvents (P0–P2) without StrategicBrief, generate:
      - StrategicBrief
      - CreativeDraftSet (+ guardrail report)
    """
    # find client events needing briefs
    subq = select(StrategicBrief.client_event_id).subquery()
    rows = (
        await session.execute(
            select(ClientEvent, Client, TopicLens, Event)
            .join(Client, Client.id == ClientEvent.client_id)
            .join(TopicLens, TopicLens.id == ClientEvent.topic_id)
            .join(Event, Event.id == ClientEvent.event_id)
            .where(
                ClientEvent.tier.in_([AlertTier.P0, AlertTier.P1, AlertTier.P2]),
                ~ClientEvent.id.in_(select(subq.c.client_event_id)),
            )
            .order_by(ClientEvent.created_at.asc())
            .limit(limit)
        )
    ).all()

    if not rows:
        return {"generated": 0}

    llm = build_llm_client()
    created = 0

    for ce, client, topic, event in rows:
        try:
            payload: dict[str, Any]
            if llm is None:
                payload = _fallback_brief_and_drafts(client, topic, event, ce)
            else:
                system = (
                    "You are the Strategic Brief + Creative Engagement agent for a PR/exec comms team.\n"
                    "Rules:\n"
                    "- Use ONLY the provided event text and metadata as factual input.\n"
                    "- Do NOT invent stats, quotes, or regulatory details.\n"
                    "- If you are uncertain, state it as an assumption.\n"
                    "- Be concise, specific, and brand-safe.\n"
                    "- Output valid JSON only.\n"
                )
                user = _build_user_prompt(client=client, topic=topic, event=event, client_event=ce)
                payload, _ = await llm.generate_json(system=system, user=user, json_schema=_BRIEF_JSON_SCHEMA)

            # map engagement mode
            rec = str(payload.get("strategic_analysis", {}).get("engagement_mode_recommendation") or "comment")
            try:
                em = EngagementMode(rec)
            except Exception:
                em = EngagementMode.comment

            brief = StrategicBrief(
                client_event_id=ce.id,
                event_summary=normalize_text(payload.get("event_summary") or ""),
                strategic_analysis=payload.get("strategic_analysis") or {},
                engagement_mode=em,
                confidence=payload.get("confidence") or {},
            )
            session.add(brief)
            await session.flush()

            # collect generated texts for guardrails
            linkedin_comments = payload.get("linkedin_comments") or {}
            independent_posts = payload.get("independent_posts") or {}

            flat_texts = {}
            for k, v in (linkedin_comments.items() if isinstance(linkedin_comments, dict) else []):
                flat_texts[f"linkedin_{k}"] = str(v)
            for k, v in (independent_posts.items() if isinstance(independent_posts, dict) else []):
                flat_texts[f"post_{k}"] = str(v)

            risk_keywords = list(set((client.risk_keywords or []) + (topic.risk_flags or [])))
            allow = list(set([client.name] + (client.competitors or []) + [topic.name]))

            guardrail_report = run_guardrails(
                generated_texts=flat_texts,
                source_text=event.raw_text or "",
                risk_keywords=risk_keywords,
                brand_voice_profile=client.brand_voice_profile or {},
                entity_allowlist=allow,
            )

            drafts = CreativeDraftSet(
                brief_id=brief.id,
                linkedin_comments=linkedin_comments if isinstance(linkedin_comments, dict) else {},
                independent_posts=independent_posts if isinstance(independent_posts, dict) else {},
                guardrail_report=guardrail_report,
            )
            session.add(drafts)

            created += 1
        except Exception as e:
            log.exception("brief_generation_failed", client_event_id=str(ce.id), error=str(e))

    log.info("brief_generation_done", created=created)
    return {"generated": created}


def _build_user_prompt(*, client: Client, topic: TopicLens, event: Event, client_event: ClientEvent) -> str:
    # Keep prompt deterministic; make the model generate diversity inside angles.
    return f"""
CLIENT CONTEXT
- Client: {client.name}
- Messaging pillars: {client.messaging_pillars}
- Competitors: {client.competitors}
- Risk keywords: {client.risk_keywords}
- Audience profile (JSON): {client.audience_profile}
- Brand voice profile (JSON): {client.brand_voice_profile}

TOPIC LENS
- Topic: {topic.name}
- Description: {topic.description}
- Keywords: {topic.keywords}
- Topic risk flags: {topic.risk_flags}
- Opportunity tags: {topic.opportunity_tags}

EVENT
- Source type: {event.source_type.value}
- Title: {event.title}
- Author: {event.author}
- URL/URN: {event.url}
- Published at (UTC): {event.published_at.isoformat()}
- Engagement stats (JSON): {event.engagement_stats}
- Detected entities: {event.detected_entities}
- Sentiment (compound): {event.sentiment}

EVENT TEXT (the only factual source)
\"\"\"{event.raw_text}\"\"\"

SCORING CONTEXT
- Tier: {client_event.tier.value}
- Composite score: {client_event.composite_score}
- Rationale: {client_event.rationale}

TASK
1) Produce a tight Event Summary (<= 3 sentences).
2) Strategic Analysis:
   - Why it matters to THIS client.
   - Opportunity vector (what to do).
   - Risk vector (what to avoid).
   - Recommended stance (tone + positioning).
   - Engagement mode recommendation: comment | independent_post | thread | journalist_outreach | stay_silent
3) Angle Generator:
   Provide 5 angles:
   - Authority reinforcement
   - Market reframing
   - Data interpretation (without adding new numbers)
   - Narrative tension
   - Future projection
4) Creative outputs:
   LinkedIn comment set:
   - micro_insight (short, sharp)
   - contrarian (respectful)
   - framework (3 bullets or steps)
   - narrative_amplifier (tie to bigger shift)
   - question_driven (drive replies)
   Independent post drafts (3 versions):
   - rapid_response (150-200 words)
   - founder_story (voice, personal, but not fictional facts)
   - industry_framework (positioning, model)
5) Confidence section:
   - verified_facts_used: bullet list of facts explicitly present in EVENT TEXT/metadata
   - assumptions_made: bullet list
   - risk_level: Low | Moderate | Sensitive
Return JSON ONLY.
""".strip()
