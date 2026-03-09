"""
Main orchestrator.

Runs all measurement modules in sequence:
  1. SERP monitoring (AI Overview presence + citation extraction)
  2. Prompt monitoring (OpenAI + Perplexity AI Answer SOV)
  3. Sentiment and accuracy enrichment
  4. Entity authority analysis
  5. AI referral analytics
  6. Brand demand / dark influence proxies
  7. AI Visibility Index computation
  8. Zero-click influence aggregation
  9. Storage and CSV export

Each module that cannot run returns SKIPPED/FAILED with a reason.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brand_demand import compute_demand_summary, fetch_brand_demand
from .config import (
    BrandConfig,
    PlatformWeights,
    PromptEntry,
    Secrets,
    load_brand_config,
    load_platform_weights,
    load_prompt_library,
    load_secrets,
)
from .entity_analyzer import analyze_entity_authority
from .models import ModuleResult, Observation, Status, VisibilityIndexResult
from .prompt_monitor import monitor_prompts
from .referral_analyzer import compute_ai_referral_summary, fetch_referral_data
from .serp_monitor import monitor_serp
from .storage import Storage
from .visibility_index import compute_index_by_scope
from .report_compiler import compile_report_from_result
from .zero_click_tracker import compute_zero_click_metrics

logger = logging.getLogger(__name__)


class OrchestratorResult:
    def __init__(self) -> None:
        self.module_results: list[ModuleResult] = []
        self.observations: list[Observation] = []
        self.entity_checks: list = []
        self.referral_records: list = []
        self.demand_records: list = []
        self.visibility_indices: list[VisibilityIndexResult] = []
        self.zero_click_summary: dict[str, Any] = {}
        self.referral_summary: dict[str, Any] = {}
        self.demand_summary: dict[str, Any] = {}
        self.run_timestamp: str = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_timestamp": self.run_timestamp,
            "module_results": [mr.model_dump() for mr in self.module_results],
            "total_observations": len(self.observations),
            "total_entity_checks": len(self.entity_checks),
            "visibility_indices": [vi.model_dump() for vi in self.visibility_indices],
            "zero_click_summary": self.zero_click_summary,
            "referral_summary": self.referral_summary,
            "demand_summary": self.demand_summary,
        }


def run_measurement(
    db_path: str = "ai_pr_measurement.db",
    output_dir: str = "output",
    serp_delay: float = 2.0,
    prompt_delay: float = 1.5,
    trends_timeframe: str = "today 3-m",
    ga4_days_back: int = 30,
    brand_name: str | None = None,
    brand_config_id: str | None = None,
) -> OrchestratorResult:
    """Execute the full measurement pipeline."""
    # NOTE: logging is configured by the application entry point; do not call
    # logging.basicConfig here as it would add duplicate handlers.

    result = OrchestratorResult()
    os.makedirs(output_dir, exist_ok=True)

    # ---- Load configuration ----
    secrets = load_secrets()
    brand_id_value: uuid.UUID | None = None
    if brand_config_id:
        try:
            brand_id_value = uuid.UUID(str(brand_config_id))
        except ValueError:
            logger.warning("Invalid brand_config_id=%s; ignoring", brand_config_id)
    brand = load_brand_config(brand_name=brand_name, brand_config_id=brand_id_value)
    prompts = load_prompt_library(brand=brand)
    platform_weights = load_platform_weights()

    if brand is None:
        mr = ModuleResult(
            module="config",
            status=Status.SKIPPED,
            reason=(
                "Brand config not loaded. Create one via /brand-configs or set BRAND_CONFIG_PATH for file fallback."
            ),
        )
        result.module_results.append(mr)
        logger.error(mr.reason)
        _save_result(result, output_dir)
        return result

    if prompts is None:
        mr = ModuleResult(
            module="config",
            status=Status.SKIPPED,
            reason="Prompt library not loaded. Set PROMPT_LIBRARY_PATH.",
        )
        result.module_results.append(mr)
        logger.error(mr.reason)
        # Continue with entity / referral / demand even without prompts
        prompts = []

    result.module_results.append(ModuleResult(
        module="config",
        status=Status.SUCCESS,
        reason=f"brand={brand.brand_name}, prompts={len(prompts) if prompts else 0}",
    ))

    storage = Storage(db_path)

    # ---- 1. SERP monitoring ----
    if prompts:
        logger.info("Starting SERP monitoring (%d prompts)...", len(prompts))
        serp_obs, serp_mr = monitor_serp(prompts, brand, secrets, delay_between_calls=serp_delay)
        result.observations.extend(serp_obs)
        result.module_results.append(serp_mr)
        storage.insert_observations(serp_obs)
        logger.info("SERP monitoring: %s (%d records)", serp_mr.status, serp_mr.records_produced)
    else:
        result.module_results.append(ModuleResult(
            module="serp_monitor", status=Status.SKIPPED, reason="No prompts loaded"
        ))

    # ---- 2. Prompt monitoring (OpenAI + Perplexity) ----
    if prompts:
        logger.info("Starting prompt monitoring...")
        prompt_obs, prompt_mr = monitor_prompts(prompts, brand, secrets, delay_between_calls=prompt_delay)
        result.observations.extend(prompt_obs)
        result.module_results.append(prompt_mr)
        storage.insert_observations(prompt_obs)
        logger.info("Prompt monitoring: %s (%d records)", prompt_mr.status, prompt_mr.records_produced)
    else:
        result.module_results.append(ModuleResult(
            module="prompt_monitor", status=Status.SKIPPED, reason="No prompts loaded"
        ))

    # ---- 3. Entity authority analysis ----
    logger.info("Starting entity authority analysis...")
    entity_checks, entity_mr = analyze_entity_authority(brand, secrets)
    result.entity_checks = entity_checks
    result.module_results.append(entity_mr)
    for ec in entity_checks:
        storage.insert_entity_check(ec)
    logger.info("Entity analysis: %s (%d checks)", entity_mr.status, entity_mr.records_produced)

    # ---- 4. AI referral analytics ----
    logger.info("Starting referral analytics...")
    ref_records, ref_mr = fetch_referral_data(secrets, days_back=ga4_days_back)
    result.referral_records = ref_records
    result.module_results.append(ref_mr)
    for rec in ref_records:
        storage.insert_referral_record(rec)
    result.referral_summary = compute_ai_referral_summary(ref_records)
    logger.info("Referral analytics: %s (%d records)", ref_mr.status, ref_mr.records_produced)

    # ---- 5. Brand demand ----
    logger.info("Starting brand demand analysis...")
    demand_records, demand_mr = fetch_brand_demand(brand, timeframe=trends_timeframe)
    result.demand_records = demand_records
    result.module_results.append(demand_mr)
    for rec in demand_records:
        storage.insert_brand_demand(rec)
    result.demand_summary = compute_demand_summary(demand_records, brand.brand_name)
    logger.info("Brand demand: %s (%d records)", demand_mr.status, demand_mr.records_produced)

    # ---- 6. AI Visibility Index ----
    logger.info("Computing AI Visibility Index...")
    vis_results = compute_index_by_scope(result.observations, platform_weights)
    result.visibility_indices = vis_results
    for vi in vis_results:
        storage.insert_visibility_index(vi)
    result.module_results.append(ModuleResult(
        module="visibility_index",
        status=Status.SUCCESS if any(v.status == Status.SUCCESS for v in vis_results) else Status.SKIPPED,
        reason=None if any(v.status == Status.SUCCESS for v in vis_results) else "No successful observations",
        records_produced=len(vis_results),
    ))

    # ---- 7. Zero-click influence summary ----
    logger.info("Computing zero-click influence metrics...")
    result.zero_click_summary = compute_zero_click_metrics(
        result.observations,
        referral_summary=result.referral_summary,
        demand_summary=result.demand_summary,
    )

    # ---- Export ----
    csv_path = os.path.join(output_dir, "observations.csv")
    n_exported = storage.export_observations_csv(csv_path)
    logger.info("Exported %d observations to %s", n_exported, csv_path)

    full_csv_path = os.path.join(output_dir, "observations_full.csv")
    storage.export_full_observations_csv(full_csv_path)

    _save_result(result, output_dir)

    # ---- HTML report ----
    report_path = os.path.join(output_dir, "report.html")
    try:
        compile_report_from_result(result, report_path)
        logger.info("HTML report generated at %s", report_path)
    except Exception as exc:
        logger.warning("HTML report generation failed: %s", exc)

    storage.close()
    logger.info("Measurement run complete.")
    return result


def _save_result(result: OrchestratorResult, output_dir: str) -> None:
    summary_path = os.path.join(output_dir, "run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    logger.info("Run summary saved to %s", summary_path)

    # Entity checks report
    if result.entity_checks:
        entity_path = os.path.join(output_dir, "entity_checks.json")
        checks_data = []
        for ec in result.entity_checks:
            checks_data.append(ec.model_dump())
        with open(entity_path, "w", encoding="utf-8") as f:
            json.dump(checks_data, f, indent=2, default=str)

    # Visibility index report
    if result.visibility_indices:
        vi_path = os.path.join(output_dir, "visibility_index.json")
        vi_data = [vi.model_dump() for vi in result.visibility_indices]
        with open(vi_path, "w", encoding="utf-8") as f:
            json.dump(vi_data, f, indent=2, default=str)

    # Zero-click summary
    if result.zero_click_summary:
        zc_path = os.path.join(output_dir, "zero_click_summary.json")
        with open(zc_path, "w", encoding="utf-8") as f:
            json.dump(result.zero_click_summary, f, indent=2, default=str)

    # Referral summary
    if result.referral_summary:
        ref_path = os.path.join(output_dir, "referral_summary.json")
        with open(ref_path, "w", encoding="utf-8") as f:
            json.dump(result.referral_summary, f, indent=2, default=str)

    # Demand summary
    if result.demand_summary:
        dem_path = os.path.join(output_dir, "demand_summary.json")
        with open(dem_path, "w", encoding="utf-8") as f:
            json.dump(result.demand_summary, f, indent=2, default=str)
