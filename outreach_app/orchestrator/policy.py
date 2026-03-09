from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

from app.core.config import settings


class RiskTier(IntEnum):
    TIER0_READONLY = 0
    TIER1_INTERNAL_WRITE = 1
    TIER2_EXTERNAL_IMPACT = 2
    TIER3_FINANCIAL_LEGAL = 3


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


class PolicyEngine:
    def __init__(self) -> None:
        self._tier2 = settings.tier2_requires_approval
        self._tier3 = settings.tier3_requires_approval

    def evaluate_step(self, risk_tier: int, external_effect: bool, dry_run: bool) -> PolicyDecision:
        tier = RiskTier(int(risk_tier))

        if dry_run and (external_effect or tier >= RiskTier.TIER2_EXTERNAL_IMPACT):
            return PolicyDecision(False, False, "Dry-run mode blocks external-impact actions.")

        if tier <= RiskTier.TIER1_INTERNAL_WRITE:
            return PolicyDecision(True, False, "Low risk.")

        if tier == RiskTier.TIER2_EXTERNAL_IMPACT:
            if self._tier2:
                return PolicyDecision(True, True, "Tier 2 external impact requires approval.")
            return PolicyDecision(True, False, "Tier 2 allowed without approval by configuration.")

        if tier >= RiskTier.TIER3_FINANCIAL_LEGAL:
            if self._tier3:
                return PolicyDecision(True, True, "Tier 3 financial/legal requires approval.")
            return PolicyDecision(False, True, "Tier 3 blocked unless policy changed.")

        return PolicyDecision(False, True, "Unknown risk tier state.")

    def max_risk(self, steps: Iterable[dict]) -> int:
        mx = 0
        for s in steps:
            mx = max(mx, int(s.get("risk_tier", 0)))
        return mx
