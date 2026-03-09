from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from pr_monitor_app.utils.text import keyword_hits, normalize_text, top_capitalized_phrases


_NUM_RE = re.compile(r"(?<!\w)(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?(?!\w)")
_PERCENT_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)?\s*%(?!\w)")
_OVERSTATEMENT_PATTERNS = [
    r"\bguarantee(d)?\b",
    r"\balways\b",
    r"\bnever\b",
    r"\bno doubt\b",
    r"\bproves?\b",
    r"\bscientifically proven\b",
    r"\beveryone\b",
    r"\bno one\b",
    r"\bwill definitely\b",
    r"\bmust\b",
]


def _uniq(seq: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for s in seq:
        k = (s or "").strip()
        if not k:
            continue
        kl = k.lower()
        if kl in seen:
            continue
        seen.add(kl)
        out.append(k)
    return out


def verify_no_new_numbers(generated: str, source_text: str) -> list[str]:
    """
    Flags numeric claims that don't appear in the source text.
    This is a heuristic to reduce hallucinated stats.
    """
    gen = generated or ""
    src = source_text or ""
    gen_nums = set(_NUM_RE.findall(gen)) | set(_PERCENT_RE.findall(gen))
    src_nums = set(_NUM_RE.findall(src)) | set(_PERCENT_RE.findall(src)) | set(_PERCENT_RE.findall(src))
    violations = sorted([n for n in gen_nums if n not in src_nums])
    return violations


def detect_overstatement(generated: str) -> list[str]:
    gen = (generated or "").lower()
    hits: list[str] = []
    for pat in _OVERSTATEMENT_PATTERNS:
        if re.search(pat, gen):
            hits.append(pat)
    return hits


def brand_alignment_check(generated: str, brand_voice_profile: dict[str, Any]) -> dict[str, Any]:
    """
    Minimal brand alignment:
      - checks forbidden_words / avoid list
      - checks required tone markers (optional)
    """
    text = (generated or "").lower()
    forbidden = []
    for key in ("forbidden_words", "avoid"):
        lst = brand_voice_profile.get(key) or []
        if isinstance(lst, list):
            forbidden.extend([str(x) for x in lst])

    required = []
    for key in ("required_words", "include"):
        lst = brand_voice_profile.get(key) or []
        if isinstance(lst, list):
            required.extend([str(x) for x in lst])

    forbidden_hits = [w for w in forbidden if w and w.lower() in text]
    missing_required = [w for w in required if w and w.lower() not in text]

    return {"forbidden_hits": _uniq(forbidden_hits), "missing_required": _uniq(missing_required)}


def new_named_entities(generated: str, source_text: str, extra_allow: list[str] | None = None) -> list[str]:
    """
    Heuristic: detect capitalized phrases in generated text not present in source_text.
    """
    src = source_text or ""
    allow = set((extra_allow or []))
    src_lower = src.lower()
    candidates = top_capitalized_phrases(generated or "", max_phrases=20)
    out = []
    for c in candidates:
        if c.lower() in src_lower:
            continue
        if c in allow:
            continue
        out.append(c)
    return _uniq(out)


def risk_level_from_findings(findings: dict[str, Any]) -> str:
    # Very simple mapping
    if findings.get("number_violations"):
        return "Sensitive"
    if findings.get("overstatement_hits"):
        return "Moderate"
    if findings.get("risk_keyword_hits"):
        return "Moderate"
    return "Low"


def run_guardrails(
    *,
    generated_texts: dict[str, str],
    source_text: str,
    risk_keywords: list[str],
    brand_voice_profile: dict[str, Any],
    entity_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run anti-slop guardrails across multiple generated drafts.
    """
    report: dict[str, Any] = {"drafts": {}, "summary": {}}
    any_num_viol = []
    any_over = []
    any_risk = []
    any_new_ents = []
    any_forbidden = []
    any_missing_required = []

    for k, txt in generated_texts.items():
        nums = verify_no_new_numbers(txt, source_text)
        over = detect_overstatement(txt)
        risk_hits = keyword_hits(txt, risk_keywords)
        ba = brand_alignment_check(txt, brand_voice_profile)
        new_ents = new_named_entities(txt, source_text, extra_allow=entity_allowlist or [])

        findings = {
            "number_violations": nums,
            "overstatement_hits": over,
            "risk_keyword_hits": risk_hits,
            "brand_alignment": ba,
            "new_entities": new_ents,
        }
        findings["risk_level"] = risk_level_from_findings(findings)
        report["drafts"][k] = findings

        any_num_viol.extend(nums)
        any_over.extend(over)
        any_risk.extend(risk_hits)
        any_new_ents.extend(new_ents)
        any_forbidden.extend(ba.get("forbidden_hits") or [])
        any_missing_required.extend(ba.get("missing_required") or [])

    report["summary"] = {
        "number_violations": _uniq(any_num_viol),
        "overstatement_hits": _uniq(any_over),
        "risk_keyword_hits": _uniq(any_risk),
        "new_entities": _uniq(any_new_ents),
        "forbidden_hits": _uniq(any_forbidden),
        "missing_required": _uniq(any_missing_required),
    }
    report["summary"]["risk_level"] = risk_level_from_findings(report["summary"])
    return report
