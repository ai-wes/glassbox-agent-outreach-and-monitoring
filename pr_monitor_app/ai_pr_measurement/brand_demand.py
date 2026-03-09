"""
Brand demand and "dark influence" proxies via Google Trends.

Tracks interest-over-time for brand keywords and competitors.
Uses the pytrends library which queries Google Trends directly.

No API key required, but Google may rate-limit.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .config import BrandConfig
from .models import BrandDemandRecord, ModuleResult, Status

logger = logging.getLogger(__name__)


def _enable_pytrends_retry_compat() -> None:
    """Patch urllib3 Retry to accept deprecated method_whitelist for old pytrends."""
    try:
        from urllib3.util import Retry
    except Exception:
        return

    init = getattr(Retry, "__init__", None)
    if init is None:
        return

    # Idempotent patch guard.
    if getattr(init, "_npe_method_whitelist_compat", False):
        return

    def _compat_init(self, *args, **kwargs):
        if "method_whitelist" in kwargs and "allowed_methods" not in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        elif "method_whitelist" in kwargs:
            kwargs.pop("method_whitelist")
        return init(self, *args, **kwargs)

    _compat_init._npe_method_whitelist_compat = True  # type: ignore[attr-defined]
    Retry.__init__ = _compat_init  # type: ignore[assignment]


def fetch_brand_demand(
    brand: BrandConfig,
    timeframe: str = "today 3-m",  # last 3 months
    geo: str = "",
) -> tuple[list[BrandDemandRecord], ModuleResult]:
    """Fetch Google Trends interest-over-time for brand and competitor keywords."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return [], ModuleResult(
            module="brand_demand",
            status=Status.FAILED,
            reason="pytrends package not installed",
        )

    keywords = [brand.brand_name] + brand.competitors[:4]  # GT supports max 5 at once
    if not keywords:
        return [], ModuleResult(
            module="brand_demand",
            status=Status.SKIPPED,
            reason="No brand keywords to monitor",
        )

    try:
        _enable_pytrends_retry_compat()
        try:
            # Prefer retry-enabled client when supported by installed pytrends/urllib3.
            pytrends = TrendReq(hl="en-US", tz=360, retries=3, backoff_factor=1.0)
        except TypeError as exc:
            # Compatibility fallback for older pytrends on newer urllib3 where
            # Retry no longer accepts deprecated kwargs used internally.
            logger.warning("pytrends_retry_config_unsupported", error=str(exc))
            pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
    except Exception as exc:
        return [], ModuleResult(
            module="brand_demand",
            status=Status.FAILED,
            reason=f"pytrends call failed: {exc}",
        )

    if df is None or df.empty:
        return [], ModuleResult(
            module="brand_demand",
            status=Status.FAILED,
            reason="Google Trends returned empty data",
        )

    records: list[BrandDemandRecord] = []
    for dt_idx, row in df.iterrows():
        date_str = str(dt_idx.date()) if hasattr(dt_idx, "date") else str(dt_idx)
        for kw in keywords:
            if kw in row:
                val = int(row[kw])
                rec = BrandDemandRecord(
                    keyword=kw,
                    date=date_str,
                    interest_value=val,
                )
                records.append(rec)

    return records, ModuleResult(
        module="brand_demand",
        status=Status.SUCCESS,
        records_produced=len(records),
    )


def compute_demand_summary(
    records: list[BrandDemandRecord], brand_name: str
) -> dict:
    """Compute summary statistics from brand demand records."""
    if not records:
        return {"status": "SKIPPED", "reason": "no demand records"}

    by_keyword: dict[str, list[int]] = {}
    for r in records:
        by_keyword.setdefault(r.keyword, []).append(r.interest_value)

    summaries: dict[str, dict] = {}
    for kw, values in by_keyword.items():
        n = len(values)
        mean_val = sum(values) / n if n > 0 else 0.0
        # Simple trend: compare last third to first third
        third = max(n // 3, 1)
        early = values[:third]
        late = values[-third:]
        early_mean = sum(early) / len(early) if early else 0
        late_mean = sum(late) / len(late) if late else 0
        if early_mean > 0:
            trend_pct = ((late_mean - early_mean) / early_mean) * 100
        else:
            trend_pct = 0.0

        summaries[kw] = {
            "data_points": n,
            "mean_interest": round(mean_val, 2),
            "latest_interest": values[-1] if values else 0,
            "trend_pct_change": round(trend_pct, 2),
            "is_brand": kw.lower() == brand_name.lower(),
        }

    return {
        "status": "SUCCESS",
        "keywords": summaries,
    }
