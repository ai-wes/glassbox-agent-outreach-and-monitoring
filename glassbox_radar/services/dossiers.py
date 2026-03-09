from __future__ import annotations

from pathlib import Path
import re

from glassbox_radar.contracts import CollectionContext, MilestoneInference, OpportunityScore
from glassbox_radar.core.config import get_settings
from glassbox_radar.models import Company, Program, Signal


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "item"


def render_dossier(
    company: Company,
    program: Program,
    context: CollectionContext,
    score: OpportunityScore,
    inference: MilestoneInference,
    signals: list[Signal],
) -> str:
    recent_signals = sorted(
        [signal for signal in signals if signal.published_at],
        key=lambda item: item.published_at,
        reverse=True,
    )[:6]
    evidence_summary = {
        "human_data": 0,
        "genetic_validation": 0,
        "animal_models": 0,
        "orthogonal_assays": 0,
    }
    for signal in signals:
        tags = set(signal.evidence_tags)
        evidence_summary["human_data"] += int("human_data" in tags)
        evidence_summary["genetic_validation"] += int("genetic_validation" in tags)
        evidence_summary["animal_models"] += int("animal_model" in tags)
        evidence_summary["orthogonal_assays"] += int("orthogonal_assay" in tags)

    lines = [
        f"# {company.name} — {program.asset_name or program.target or 'Program'}",
        "",
        f"- **Target / mechanism:** {program.target or 'Unknown'} / {program.mechanism or 'Unknown'}",
        f"- **Modality / indication:** {program.modality or 'Unknown'} / {program.indication or 'Unknown'}",
        f"- **Stage:** {program.stage or company.stage or 'Unknown'}",
        f"- **Radar score:** {score.radar_score:.2f}",
        f"- **Milestone:** {score.milestone_type.value}",
        f"- **Milestone window:** {score.milestone_window_start or 'Unknown'} to {score.milestone_window_end or 'Unknown'}",
        "",
        "## Why now",
        "",
        f"This program is currently scored as **Tier {score.tier}** because recent signals suggest a likely **{score.milestone_type.value.replace('_', ' ')}** window with confidence **{score.milestone_confidence:.2f}**.",
        "",
        "Recent signal rationale:",
    ]
    for reason in inference.rationale[:5]:
        lines.append(f"- {reason}")

    lines.extend(
        [
            "",
            "## Core biological dependency",
            "",
            score.risk_hypothesis,
            "",
            "## Evidence profile",
            "",
            f"- Human-relevant evidence signals detected: **{evidence_summary['human_data']}**",
            f"- Genetic validation signals detected: **{evidence_summary['genetic_validation']}**",
            f"- Animal-model signals detected: **{evidence_summary['animal_models']}**",
            f"- Orthogonal-assay signals detected: **{evidence_summary['orthogonal_assays']}**",
            "",
            "## Commercial path",
            "",
            f"- Primary buyer: **{score.primary_buyer_role}**",
            f"- Capital exposure band: **{score.capital_exposure_band}**",
            f"- Warm introduction paths: **{', '.join(context.warm_intro_paths) if context.warm_intro_paths else 'None detected'}**",
            f"- Recommended framing: **{score.outreach_angle}**",
            "",
            "## Recent signals",
            "",
        ]
    )

    if recent_signals:
        for signal in recent_signals:
            lines.append(
                f"- [{signal.title}]({signal.source_url}) — {signal.published_at.date() if signal.published_at else 'Unknown date'} — {signal.signal_type.value}"
            )
    else:
        lines.append("- No dated recent signals available in the current run.")

    lines.extend(
        [
            "",
            "## Recommended action",
            "",
            "1. Validate the fragility hypothesis with a targeted mechanistic dependency review.",
            "2. Route outreach through the strongest available buyer path (founder, CSO, board, or investor).",
            "3. Offer a milestone-specific Snapshot focused on the assumption most responsible for downstream capital exposure.",
            "",
        ]
    )

    return "\n".join(lines)


def write_dossier(
    company: Company,
    program: Program,
    context: CollectionContext,
    score: OpportunityScore,
    inference: MilestoneInference,
    signals: list[Signal],
) -> str:
    settings = get_settings()
    company_slug = slugify(company.name)
    program_slug = slugify(program.asset_name or program.target or "program")
    folder = settings.dossiers_dir / company_slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{program_slug}-{score.milestone_type.value}.md"
    path.write_text(
        render_dossier(company=company, program=program, context=context, score=score, inference=inference, signals=signals),
        encoding="utf-8",
    )
    return str(path)
