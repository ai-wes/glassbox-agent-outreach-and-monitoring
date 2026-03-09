"""
AI referral analytics via Google Analytics 4 Data API.

Segments traffic by known AI referral sources:
  - chatgpt.com / chat.openai.com
  - perplexity.ai
  - copilot.microsoft.com
  - you.com
  - phind.com
  - Google AI Overviews (detectable via specific landing-page patterns
    or referrer strings)

Requires GOOGLE_APPLICATION_CREDENTIALS (service account) and GA4_PROPERTY_ID.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

from .config import Secrets
from .models import ModuleResult, ReferralRecord, Status

logger = logging.getLogger(__name__)

AI_SOURCE_PATTERNS: list[str] = [
    "chatgpt.com",
    "chat.openai.com",
    "perplexity.ai",
    "copilot.microsoft.com",
    "you.com",
    "phind.com",
    "gemini.google.com",
    "claude.ai",
    "poe.com",
]


def _is_ai_source(source: str) -> bool:
    s = source.lower()
    for pattern in AI_SOURCE_PATTERNS:
        if pattern in s:
            return True
    return False


def fetch_referral_data(
    secrets: Secrets,
    days_back: int = 30,
) -> tuple[list[ReferralRecord], ModuleResult]:
    """Fetch session data by source/medium from GA4 and classify AI sources."""
    if not secrets.ga4_property_id:
        return [], ModuleResult(
            module="referral_analyzer",
            status=Status.SKIPPED,
            reason="GA4_PROPERTY_ID not set",
        )
    creds_path = secrets.ga4_credentials_path
    if not creds_path or not os.path.exists(creds_path):
        return [], ModuleResult(
            module="referral_analyzer",
            status=Status.SKIPPED,
            reason="GOOGLE_APPLICATION_CREDENTIALS not set or file not found",
        )

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )
    except ImportError:
        return [], ModuleResult(
            module="referral_analyzer",
            status=Status.FAILED,
            reason="google-analytics-data package not installed",
        )

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    try:
        client = BetaAnalyticsDataClient()
        request = RunReportRequest(
            property=f"properties/{secrets.ga4_property_id}",
            date_ranges=[DateRange(start_date=start_str, end_date=end_str)],
            dimensions=[
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="screenPageViews"),
                Metric(name="conversions"),
            ],
        )
        response = client.run_report(request)
    except Exception as exc:
        return [], ModuleResult(
            module="referral_analyzer",
            status=Status.FAILED,
            reason=f"GA4 API call failed: {exc}",
        )

    records: list[ReferralRecord] = []
    for row in response.rows:
        source = row.dimension_values[0].value if len(row.dimension_values) > 0 else ""
        medium = row.dimension_values[1].value if len(row.dimension_values) > 1 else ""
        sessions = int(row.metric_values[0].value) if len(row.metric_values) > 0 else 0
        page_views = int(row.metric_values[1].value) if len(row.metric_values) > 1 else 0
        conversions = int(row.metric_values[2].value) if len(row.metric_values) > 2 else 0

        rec = ReferralRecord(
            date_range_start=start_str,
            date_range_end=end_str,
            source=source,
            medium=medium,
            sessions=sessions,
            page_views=page_views,
            conversions=conversions,
            is_ai_source=_is_ai_source(source),
            source_api="ga4",
        )
        records.append(rec)

    return records, ModuleResult(
        module="referral_analyzer",
        status=Status.SUCCESS,
        records_produced=len(records),
    )


def compute_ai_referral_summary(records: list[ReferralRecord]) -> dict:
    """Compute summary statistics from referral records."""
    if not records:
        return {"status": "SKIPPED", "reason": "no referral records"}

    total_sessions = sum(r.sessions for r in records)
    ai_sessions = sum(r.sessions for r in records if r.is_ai_source)
    total_conversions = sum(r.conversions for r in records)
    ai_conversions = sum(r.conversions for r in records if r.is_ai_source)

    ai_by_source: dict[str, dict] = {}
    for r in records:
        if r.is_ai_source:
            key = r.source
            if key not in ai_by_source:
                ai_by_source[key] = {"sessions": 0, "page_views": 0, "conversions": 0}
            ai_by_source[key]["sessions"] += r.sessions
            ai_by_source[key]["page_views"] += r.page_views
            ai_by_source[key]["conversions"] += r.conversions

    return {
        "status": "SUCCESS",
        "date_range_start": records[0].date_range_start,
        "date_range_end": records[0].date_range_end,
        "total_sessions": total_sessions,
        "ai_sessions": ai_sessions,
        "ai_session_share": ai_sessions / total_sessions if total_sessions > 0 else 0.0,
        "total_conversions": total_conversions,
        "ai_conversions": ai_conversions,
        "ai_conversion_share": ai_conversions / total_conversions if total_conversions > 0 else 0.0,
        "ai_by_source": ai_by_source,
    }
