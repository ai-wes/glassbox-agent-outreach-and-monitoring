from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SequenceStepTemplate:
    step_number: int
    channel: str
    delay_days: int
    subject_template: str | None
    body_template: str
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SequenceTemplate:
    key: str
    name: str
    audience: str
    steps: list[SequenceStepTemplate]


SEQUENCES: dict[str, SequenceTemplate] = {
    "technical_intro": SequenceTemplate(
        key="technical_intro",
        name="Technical Intro",
        audience="ICs and tech leads",
        steps=[
            SequenceStepTemplate(
                step_number=1,
                channel="email",
                delay_days=0,
                subject_template="{hook_subject}",
                body_template=(
                    "Noticed {trigger_line}. I run Glassbox Bio—cryptographically-verifiable target audits that "
                    "surface kill/watch gates in hours, not quarters. {proof_line} Worth 10 minutes to see if "
                    "this fits your pipeline?"
                ),
            ),
            SequenceStepTemplate(
                step_number=2,
                channel="linkedin",
                delay_days=2,
                subject_template=None,
                body_template=(
                    "Loved your {trigger_short}. We built a Moody’s-style audit for targets—deterministic, "
                    "sealed, and investor-ready. Happy to show a TRI preview on a safe example. Interested?"
                ),
            ),
            SequenceStepTemplate(
                step_number=3,
                channel="email",
                delay_days=5,
                subject_template="Quick close-the-loop on {company_name}",
                body_template=(
                    "If timing is bad, I can send a short Loom on how we bind raw data to SHA-256 artifacts, "
                    "Evidence IDs, and TRI bands. If it’s not useful, I’ll bow out."
                ),
            ),
        ],
    ),
    "productized_pilot_exec": SequenceTemplate(
        key="productized_pilot_exec",
        name="Productized Pilot",
        audience="BD and executive buyers",
        steps=[
            SequenceStepTemplate(
                step_number=1,
                channel="email",
                delay_days=0,
                subject_template="Pilot: audit 3 targets → board-ready artifacts",
                body_template=(
                    "Teams like yours are getting stuck in vague AI claims. Our Standard/Deep runs produce sealed "
                    "artifacts plus TRI risk bands that boards understand. {proof_line} Worth a look?"
                ),
            ),
            SequenceStepTemplate(
                step_number=2,
                channel="email",
                delay_days=3,
                subject_template="Spec for a scoped pilot at {company_name}",
                body_template=(
                    "Sharing the short spec: inputs, outputs, example Risk Meter, and Evidence IDs. If a private "
                    "offer helps, I can issue it same-day."
                ),
            ),
            SequenceStepTemplate(
                step_number=3,
                channel="linkedin",
                delay_days=6,
                subject_template=None,
                body_template=(
                    "Reacting to your recent work because it lines up with a pattern we see: deterministic audit "
                    "artifacts can cut decision latency materially when target claims are noisy."
                ),
            ),
        ],
    ),
    "social_warm_partner": SequenceTemplate(
        key="social_warm_partner",
        name="Social Warm Partner",
        audience="Cloud partner and co-sell motions",
        steps=[
            SequenceStepTemplate(
                step_number=1,
                channel="linkedin",
                delay_days=0,
                subject_template=None,
                body_template=(
                    "Glassbox is a Kubernetes-based molecular-audit app for HCLS buyers who need proof, not prose. "
                    "Happy to share a one-pager and demo that helps deals where AI-biology needs validation."
                ),
            ),
            SequenceStepTemplate(
                step_number=2,
                channel="email",
                delay_days=1,
                subject_template="Deterministic audit for {company_name}",
                body_template=(
                    "{partner_intro} We can run a single Deep on a hairy target to show the kill/watch logic and "
                    "deliver a board-grade memo in 72 hours. Up for a scoped try?"
                ),
            ),
            SequenceStepTemplate(
                step_number=3,
                channel="email",
                delay_days=4,
                subject_template="Co-sell one-pager and private offer tiers",
                body_template=(
                    "Sending the co-sell one-pager and private-offer tiers in case it helps. If it’s not a priority, "
                    "I’ll circle back post-quarter."
                ),
            ),
        ],
    ),
    "investor_diligence": SequenceTemplate(
        key="investor_diligence",
        name="Investor Diligence",
        audience="VC and investors",
        steps=[
            SequenceStepTemplate(
                step_number=1,
                channel="email",
                delay_days=0,
                subject_template="Independent diligence signal on AI-bio targets",
                body_template=(
                    "You back companies where platform claims move faster than verification. Glassbox produces "
                    "deterministic target audits with sealed artifacts and TRI bands so diligence can be sharper "
                    "before wet-lab burn ramps. Worth a brief look?"
                ),
            ),
            SequenceStepTemplate(
                step_number=2,
                channel="email",
                delay_days=4,
                subject_template="Portfolio diligence memo sample",
                body_template=(
                    "I can send a sample memo structure showing how Evidence IDs, risk bands, and kill/watch gates "
                    "translate into investment committee language."
                ),
            ),
        ],
    ),
    "founder_fundraising": SequenceTemplate(
        key="founder_fundraising",
        name="Founder Fundraising",
        audience="Founders and CSOs",
        steps=[
            SequenceStepTemplate(
                step_number=1,
                channel="email",
                delay_days=0,
                subject_template="Your {company_name} story, but with sealed proof",
                body_template=(
                    "When investors push past the narrative, deterministic audit artifacts help. We turn target claims "
                    "into sealed evidence, TRI risk bands, and a memo investors can trust. Open to a 10-minute fit "
                    "check?"
                ),
            ),
            SequenceStepTemplate(
                step_number=2,
                channel="linkedin",
                delay_days=2,
                subject_template=None,
                body_template=(
                    "Founders using AI in biology are under pressure to make proof portable. We built a way to do that "
                    "without waiting a quarter for a diligence cycle."
                ),
            ),
        ],
    ),
}

APPROVED_METRIC_CLAIMS = {
    "cut_should_we_fund_cycles_42": "cut ‘should we fund this?’ cycles by 42%",
    "clarified_go_no_go": "clarified at least one go/no-go decision in a two-week pilot",
    "decision_latency_40": "cut decision latency by about 40%",
    "board_memo_72h": "delivered a board-grade memo in 72 hours",
}
