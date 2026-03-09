from __future__ import annotations

from typing import Any

from pr_monitor_app.config import settings
from pr_monitor_app.logging import get_logger

log = get_logger(component="analytics.ai_pr_measurement")


def run_ai_pr_measurement_from_settings(
    *,
    brand_name: str | None = None,
    brand_config_id: str | None = None,
) -> dict[str, Any]:
    """
    Run AI PR measurement orchestrator using NPE settings.

    This keeps the orchestration optional and isolated from the core
    pipeline so deployments can enable it incrementally.
    """
    if not settings.ai_pr_measurement_enabled:
        return {"status": "SKIPPED", "reason": "AI_PR_MEASUREMENT_ENABLED is false"}

    try:
        from pr_monitor_app.ai_pr_measurement.orchestrator import run_measurement
    except Exception as exc:  # pragma: no cover - defensive import guard
        log.warning("ai_pr_measurement_import_failed", error=str(exc))
        return {"status": "FAILED", "reason": f"import_failed: {exc}"}

    try:
        result = run_measurement(
            db_path=settings.ai_pr_measurement_db_path,
            output_dir=settings.ai_pr_measurement_output_dir,
            serp_delay=float(settings.ai_pr_measurement_serp_delay),
            prompt_delay=float(settings.ai_pr_measurement_prompt_delay),
            trends_timeframe=settings.ai_pr_measurement_trends_timeframe,
            ga4_days_back=int(settings.ai_pr_measurement_ga4_days_back),
            brand_name=brand_name,
            brand_config_id=brand_config_id,
        )
    except Exception as exc:
        log.warning("ai_pr_measurement_run_failed", error=str(exc))
        return {"status": "FAILED", "reason": str(exc)}

    module_results = [mr.model_dump() for mr in result.module_results]
    success_count = sum(1 for mr in result.module_results if mr.status.value == "SUCCESS")

    return {
        "status": "SUCCESS" if success_count > 0 else "SKIPPED",
        "module_results": module_results,
        "total_observations": len(result.observations),
        "output_dir": settings.ai_pr_measurement_output_dir,
        "db_path": settings.ai_pr_measurement_db_path,
    }
