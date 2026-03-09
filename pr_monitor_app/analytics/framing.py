from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from pr_monitor_app.logging import get_logger

log = get_logger(component="analytics.framing")


@dataclass(frozen=True)
class FrameHit:
    frame: str
    score: float
    matches: int
    matched_terms: list[str]


_DEFAULT_FRAMES: dict[str, list[str]] = {
    # Product & innovation
    "innovation": [
        "breakthrough",
        "innovation",
        "innovative",
        "new approach",
        "state of the art",
        "sota",
        "research",
        "launch",
        "released",
        "introduces",
        "announces",
        "rollout",
        "update",
        "feature",
    ],
    # Regulation & policy
    "regulation_policy": [
        "regulation",
        "regulatory",
        "policy",
        "compliance",
        "law",
        "legislation",
        "ban",
        "fine",
        "enforcement",
        "oversight",
        "antitrust",
        "eu",
        "commission",
        "senate",
        "congress",
        "ftc",
        "doj",
        "gdpr",
        "ai act",
        "hipaa",
        "sec",
    ],
    # Security & privacy
    "security_privacy": [
        "breach",
        "breached",
        "hack",
        "hacked",
        "ransomware",
        "vulnerability",
        "zero-day",
        "security",
        "privacy",
        "leak",
        "leaked",
        "incident",
        "exposed",
        "data loss",
        "phishing",
        "malware",
    ],
    # Funding & finance
    "finance_funding": [
        "series a",
        "series b",
        "series c",
        "seed round",
        "raised",
        "funding",
        "investment",
        "valuation",
        "ipo",
        "acquisition",
        "acquired",
        "merger",
        "earnings",
        "revenue",
        "profit",
        "loss",
        "guidance",
    ],
    # People / org changes
    "people_org": [
        "layoff",
        "layoffs",
        "restructuring",
        "reorg",
        "hiring",
        "appointed",
        "joins",
        "resigns",
        "steps down",
        "leadership",
        "ceo",
        "cfo",
        "cto",
        "chief",
        "workforce",
    ],
    # Partnerships & ecosystem
    "partnerships": [
        "partner",
        "partnership",
        "collaboration",
        "collaborate",
        "alliance",
        "ecosystem",
        "integration",
        "integrates",
        "joins forces",
    ],
    # Crisis / controversy
    "crisis_controversy": [
        "backlash",
        "controversy",
        "criticized",
        "outrage",
        "lawsuit",
        "sued",
        "settlement",
        "boycott",
        "scandal",
        "whistleblower",
        "investigation",
        "probe",
        "allegations",
        "apologized",
    ],
    # Thought leadership / opinion
    "thought_leadership": [
        "opinion",
        "my take",
        "here's why",
        "what this means",
        "framework",
        "lesson",
        "insight",
        "perspective",
        "trend",
        "analysis",
    ],
}


def _compile_term(term: str) -> re.Pattern[str] | None:
    term = term.strip().lower()
    if not term:
        return None
    if " " in term or "-" in term:
        # phrase match using simple substring via regex escape
        return re.compile(re.escape(term))
    # word boundary
    return re.compile(rf"\b{re.escape(term)}\b")


class FramingDetector:
    """Heuristic framing detector based on keyword/phrase matches.

    This is deterministic and explainable, which is ideal for an automated analytics layer.
    """

    def __init__(self, frames: dict[str, list[str]] | None = None) -> None:
        frames = frames or _DEFAULT_FRAMES
        compiled: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        for frame, terms in frames.items():
            pats: list[tuple[str, re.Pattern[str]]] = []
            for t in terms:
                pat = _compile_term(t)
                if pat is not None:
                    pats.append((t.lower(), pat))
            compiled[frame] = pats
        self._compiled = compiled

    def detect(self, text: str, *, title: str | None = None, max_frames: int = 4) -> list[FrameHit]:
        if not text:
            return []

        haystack = (title + " " if title else "") + text
        haystack_l = haystack.lower()

        hits: list[FrameHit] = []
        for frame, pats in self._compiled.items():
            matches = 0
            matched_terms: list[str] = []
            for term, pat in pats:
                if pat.search(haystack_l):
                    matches += 1
                    matched_terms.append(term)
            if matches == 0:
                continue

            # saturating score curve: 1 - exp(-k*matches)
            score = 1.0 - math.exp(-0.45 * matches)
            hits.append(FrameHit(frame=frame, score=float(score), matches=matches, matched_terms=matched_terms[:12]))

        hits.sort(key=lambda h: (h.score, h.matches), reverse=True)
        return hits[:max_frames]
