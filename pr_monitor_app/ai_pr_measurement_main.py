#!/usr/bin/env python3
"""
CLI entry point for the AI PR Measurement System.

Usage:
    python main.py [--db DB_PATH] [--output OUTPUT_DIR] [--serp-delay SECONDS]
                   [--prompt-delay SECONDS] [--trends-timeframe TIMEFRAME]
                   [--ga4-days DAYS]

Environment variables required (set whichever you have):
    BRAND_CONFIG_PATH       Path to brand configuration JSON file
    PROMPT_LIBRARY_PATH     Path to prompt library JSON file
    OPENAI_API_KEY         OpenAI API key for ChatGPT monitoring and analysis
    PERPLEXITY_API_KEY     Perplexity API key for answer engine monitoring
    GOOGLE_KG_API_KEY      Google Knowledge Graph API key
    GA4_PROPERTY_ID        Google Analytics 4 property ID
    GOOGLE_APPLICATION_CREDENTIALS  Path to GA4 service account JSON

Optional:
    PLATFORM_WEIGHTS_PATH   Path to platform weights JSON file
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI PR Measurement System — zero-click influence, entity authority, AI Visibility Index",
    )
    parser.add_argument(
        "--db", default="ai_pr_measurement.db",
        help="SQLite database path (default: ai_pr_measurement.db)",
    )
    parser.add_argument(
        "--output", default="output",
        help="Output directory for CSV and JSON exports (default: output)",
    )
    parser.add_argument(
        "--serp-delay", type=float, default=2.0,
        help="Delay between search monitoring calls in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--prompt-delay", type=float, default=1.5,
        help="Delay between prompt API calls in seconds (default: 1.5)",
    )
    parser.add_argument(
        "--trends-timeframe", default="today 3-m",
        help="Google Trends timeframe (default: 'today 3-m')",
    )
    parser.add_argument(
        "--ga4-days", type=int, default=30,
        help="Number of days back for GA4 referral data (default: 30)",
    )
    args = parser.parse_args()

    from pr_monitor_app.ai_pr_measurement.orchestrator import run_measurement

    result = run_measurement(
        db_path=args.db,
        output_dir=args.output,
        serp_delay=args.serp_delay,
        prompt_delay=args.prompt_delay,
        trends_timeframe=args.trends_timeframe,
        ga4_days_back=args.ga4_days,
    )

    # Print summary to stdout
    print("\n" + "=" * 72)
    print("AI PR MEASUREMENT — RUN SUMMARY")
    print("=" * 72)
    for mr in result.module_results:
        status_icon = {"SUCCESS": "✓", "SKIPPED": "⊘", "FAILED": "✗"}.get(mr.status.value, "?")
        line = f"  [{status_icon}] {mr.module:<25} {mr.status.value:<8}"
        if mr.records_produced:
            line += f"  records={mr.records_produced}"
        if mr.reason:
            line += f"  ({mr.reason})"
        print(line)

    # Visibility Index
    for vi in result.visibility_indices:
        if vi.status == "SUCCESS" and vi.scope == "all":
            print(f"\n  AI Visibility Index (overall): {vi.visibility_index:.4f}")
            print(f"  Weighted AI Visibility Index:  {vi.weighted_visibility_index:.4f}")
            print(f"  AI Answer SOV:                 {vi.ai_answer_sov:.2%}")
            print(f"  AI Citation SOV:               {vi.ai_citation_sov:.2%}")
            print(f"  Mean Accuracy:                 {vi.mean_accuracy:.2%}")
            print(f"  Mean Sentiment (0-1 norm):     {vi.mean_sentiment:.4f}")

    # Zero-click
    zc = result.zero_click_summary
    if zc.get("status") == "SUCCESS":
        print(f"\n  Zero-Click Mention Rate:       {zc['zero_click_mention_rate']:.2%}")
        if "dark_influence_gap" in zc:
            print(f"  Dark Influence Gap:            {zc['dark_influence_gap']:.4f}")

    print("\n" + "=" * 72)
    print(f"  Outputs written to: {args.output}/")
    print("=" * 72 + "\n")

    # Exit code: 0 if at least one module succeeded
    any_success = any(mr.status.value == "SUCCESS" for mr in result.module_results)
    return 0 if any_success else 1


if __name__ == "__main__":
    sys.exit(main())
