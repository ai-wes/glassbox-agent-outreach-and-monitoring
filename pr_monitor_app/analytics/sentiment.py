from __future__ import annotations

from dataclasses import dataclass

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from pr_monitor_app.logging import get_logger

log = get_logger(component="analytics.sentiment")


@dataclass(frozen=True)
class SentimentResult:
    score: float
    label: str  # "negative" | "neutral" | "positive"


class SentimentAnalyzer:
    """VADER-based sentiment analysis.

    VADER is fast and robust for social/news style text. We use the compound score.
    """

    def __init__(self) -> None:
        self._analyzer = SentimentIntensityAnalyzer()

    def analyze(self, text: str) -> SentimentResult:
        if not text or not text.strip():
            return SentimentResult(score=0.0, label="neutral")

        scores = self._analyzer.polarity_scores(text)
        compound = float(scores.get("compound", 0.0))

        # VADER recommended thresholds
        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"

        return SentimentResult(score=compound, label=label)
