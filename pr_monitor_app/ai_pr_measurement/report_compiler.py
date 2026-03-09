"""
HTML report compiler for AI PR Measurement results.

Consumes an OrchestratorResult (or its JSON-serialized output files)
and produces a single self-contained HTML report with embedded
Chart.js visualizations — warm glassmorphic light-mode design.
"""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Warm palette constants used in chart builders
_PAL = {
    "teal": "#2a9d8f",
    "sage": "#6b9080",
    "coral": "#e07a5f",
    "amber": "#e9c46a",
    "sand": "#d4a373",
    "slate": "#5e6472",
    "blue": "#457b9d",
    "rose": "#bc4749",
    "mint": "#8ecae6",
    "lavender": "#b5838d",
}
_CHART_COLORS = ["#2a9d8f", "#e07a5f", "#457b9d", "#e9c46a", "#b5838d", "#6b9080"]


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _score(v: float, decimals: int = 4) -> str:
    return f"{v:.{decimals}f}"


def _status_badge(status: str) -> str:
    s = status.upper()
    styles = {
        "SUCCESS": "background:rgba(42,157,143,0.12);color:#2a9d8f",
        "SKIPPED": "background:rgba(233,196,106,0.18);color:#b8860b",
        "FAILED": "background:rgba(188,71,73,0.12);color:#bc4749",
    }
    st = styles.get(s, "background:rgba(94,100,114,0.10);color:#5e6472")
    return f'<span class="badge" style="{st}">{html.escape(s)}</span>'


def _esc(val: Any) -> str:
    return html.escape(str(val)) if val else ""


# ---------------------------------------------------------------------------
# Chart theme (shared options applied via defaults block in <script>)
# ---------------------------------------------------------------------------
_CHART_DEFAULTS_JS = """
Chart.defaults.font.family = "'Plus Jakarta Sans', 'DM Sans', system-ui, sans-serif";
Chart.defaults.color = '#6b7280';
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.padding = 14;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(255,255,255,0.96)';
Chart.defaults.plugins.tooltip.titleColor = '#1e293b';
Chart.defaults.plugins.tooltip.bodyColor = '#475569';
Chart.defaults.plugins.tooltip.borderColor = 'rgba(0,0,0,0.06)';
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.cornerRadius = 10;
Chart.defaults.plugins.tooltip.padding = 12;
Chart.defaults.plugins.tooltip.boxPadding = 4;
"""


def _chart_doughnut(canvas_id: str, labels: list[str], values: list[float],
                    colors: list[str], title: str = "") -> str:
    return f"""
<canvas id="{canvas_id}" height="250"></canvas>
<script>
new Chart(document.getElementById('{canvas_id}'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(labels)},
    datasets: [{{
      data: {json.dumps(values)},
      backgroundColor: {json.dumps(colors)},
      borderWidth: 0,
      hoverOffset: 8
    }}]
  }},
  options: {{
    cutout: '66%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 12 }} }} }},
      title: {{ display: {json.dumps(bool(title))}, text: {json.dumps(title)}, font: {{ size: 13, weight: '600' }}, padding: {{ bottom: 12 }} }}
    }}
  }}
}});
</script>"""


def _chart_bar(canvas_id: str, labels: list[str], datasets: list[dict],
               title: str = "", y_pct: bool = False) -> str:
    y_callback = ""
    if y_pct:
        y_callback = "callback: v => (v*100).toFixed(0)+'%',"
    return f"""
<canvas id="{canvas_id}" height="280"></canvas>
<script>
new Chart(document.getElementById('{canvas_id}'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(labels)},
    datasets: {json.dumps(datasets)}
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'top' }},
      title: {{ display: {json.dumps(bool(title))}, text: {json.dumps(title)}, font: {{ size: 13, weight: '600' }}, padding: {{ bottom: 12 }} }}
    }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 11 }} }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ font: {{ size: 11 }}, {y_callback} }}, grid: {{ color: 'rgba(0,0,0,0.04)' }}, beginAtZero: true, border: {{ display: false }} }}
    }}
  }}
}});
</script>"""


def _chart_line(canvas_id: str, labels: list[str], datasets: list[dict],
                title: str = "") -> str:
    return f"""
<canvas id="{canvas_id}" height="260"></canvas>
<script>
new Chart(document.getElementById('{canvas_id}'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(labels)},
    datasets: {json.dumps(datasets)}
  }},
  options: {{
    responsive: true,
    interaction: {{ intersect: false, mode: 'index' }},
    plugins: {{
      legend: {{ position: 'top' }},
      title: {{ display: {json.dumps(bool(title))}, text: {json.dumps(title)}, font: {{ size: 13, weight: '600' }}, padding: {{ bottom: 12 }} }}
    }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 10 }}, maxRotation: 45 }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ font: {{ size: 11 }} }}, grid: {{ color: 'rgba(0,0,0,0.04)' }}, beginAtZero: true, border: {{ display: false }} }}
    }}
  }}
}});
</script>"""


def _chart_radar(canvas_id: str, labels: list[str], values: list[float],
                 title: str = "") -> str:
    return f"""
<canvas id="{canvas_id}" height="300"></canvas>
<script>
new Chart(document.getElementById('{canvas_id}'), {{
  type: 'radar',
  data: {{
    labels: {json.dumps(labels)},
    datasets: [{{
      label: 'Score',
      data: {json.dumps(values)},
      backgroundColor: 'rgba(42,157,143,0.12)',
      borderColor: '#2a9d8f',
      borderWidth: 2,
      pointBackgroundColor: '#2a9d8f',
      pointBorderColor: '#fff',
      pointBorderWidth: 2,
      pointRadius: 5
    }}]
  }},
  options: {{
    plugins: {{
      legend: {{ display: false }},
      title: {{ display: {json.dumps(bool(title))}, text: {json.dumps(title)}, font: {{ size: 13, weight: '600' }}, padding: {{ bottom: 12 }} }}
    }},
    scales: {{
      r: {{
        grid: {{ color: 'rgba(0,0,0,0.06)' }},
        angleLines: {{ color: 'rgba(0,0,0,0.06)' }},
        pointLabels: {{ font: {{ size: 11, weight: '500' }}, color: '#475569' }},
        ticks: {{ display: false, stepSize: 0.25 }},
        min: 0, max: 1
      }}
    }}
  }}
}});
</script>"""


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_executive_summary(data: dict) -> str:
    vi_all = None
    for vi in data.get("visibility_indices", []):
        if vi.get("scope") == "all" and vi.get("status") == "SUCCESS":
            vi_all = vi
            break

    zc = data.get("zero_click_summary", {})

    # Each card: (icon_svg, label, value, subtitle, accent_color)
    cards: list[tuple[str, str, str, str, str]] = []
    if vi_all:
        cards.append(("chart", "AI Visibility Index", _score(vi_all["visibility_index"]), "Unweighted composite", "#2a9d8f"))
        cards.append(("layers", "Weighted Visibility", _score(vi_all["weighted_visibility_index"]), "Business &amp; platform weighted", "#457b9d"))
        cards.append(("megaphone", "AI Answer SOV", _pct(vi_all["ai_answer_sov"]), "Brand mentioned in AI answers", "#e07a5f"))
        cards.append(("link", "AI Citation SOV", _pct(vi_all["ai_citation_sov"]), "Brand domain cited", "#e9c46a"))
        cards.append(("check", "Mean Accuracy", _pct(vi_all["mean_accuracy"]), "Factual correctness rate", "#6b9080"))
        cards.append(("smile", "Mean Sentiment", _score(vi_all["mean_sentiment"]), "Normalized 0 &ndash; 1", "#b5838d"))

    if zc.get("status") == "SUCCESS":
        cards.append(("eye-off", "Zero-Click Rate", _pct(zc["zero_click_mention_rate"]), "Mentioned without citation link", "#5e6472"))
        if "dark_influence_gap" in zc:
            cards.append(("zap", "Dark Influence Gap", _score(zc["dark_influence_gap"]), "SOV minus click share", "#bc4749"))

    html_cards = ""
    for icon, label, value, subtitle, accent in cards:
        html_cards += f"""
        <div class="kpi-card">
            <div class="kpi-icon" style="background:{accent}15;color:{accent}">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
            </div>
            <div class="kpi-label">{label}</div>
            <div class="kpi-value" style="color:{accent}">{_esc(value)}</div>
            <div class="kpi-sub">{subtitle}</div>
        </div>"""

    return f"""
    <section id="executive-summary">
        <div class="section-header">
            <span class="section-num">01</span>
            <h2>Executive Summary</h2>
        </div>
        <div class="kpi-grid">{html_cards}</div>
    </section>"""


def _section_module_status(data: dict) -> str:
    rows = ""
    for mr in data.get("module_results", []):
        rows += f"""
        <tr>
            <td class="mod-name">{_esc(mr['module'])}</td>
            <td>{_status_badge(mr.get('status', 'SKIPPED'))}</td>
            <td class="num">{mr.get('records_produced', 0)}</td>
            <td class="dim">{_esc(mr.get('reason', ''))}</td>
        </tr>"""

    return f"""
    <section id="module-status">
        <div class="section-header">
            <span class="section-num">02</span>
            <h2>Module Status</h2>
        </div>
        <div class="glass-card">
        <div class="table-wrap">
        <table>
            <thead><tr><th>Module</th><th>Status</th><th>Records</th><th>Details</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        </div>
        </div>
    </section>"""


def _section_visibility_index(data: dict) -> str:
    vis_list = [v for v in data.get("visibility_indices", []) if v.get("status") == "SUCCESS"]
    if not vis_list:
        return '<section id="visibility"><div class="section-header"><span class="section-num">03</span><h2>AI Visibility Index</h2></div><p class="empty-state">No visibility data available.</p></section>'

    vi_all = next((v for v in vis_list if v.get("scope") == "all"), None)
    radar_html = ""
    if vi_all:
        radar_html = _chart_radar(
            "radarVis",
            ["Mention SOV", "Citation SOV", "Prominence", "Accuracy", "Sentiment"],
            [vi_all["ai_answer_sov"], vi_all["ai_citation_sov"],
             vi_all["mean_prominence"], vi_all["mean_accuracy"], vi_all["mean_sentiment"]],
            "Overall Index Components"
        )

    plat_vis = [v for v in vis_list if v["scope"].startswith("platform:")]
    bar_html = ""
    if plat_vis:
        labels = [v["scope"].replace("platform:", "").title() for v in plat_vis]
        bar_html = _chart_bar("barVisPlatform", labels, [
            {"label": "Visibility Index", "data": [v["visibility_index"] for v in plat_vis],
             "backgroundColor": "#2a9d8f", "borderRadius": 6},
            {"label": "Weighted Index", "data": [v["weighted_visibility_index"] for v in plat_vis],
             "backgroundColor": "#457b9d", "borderRadius": 6},
        ], "Visibility by Platform")

    grp_vis = [v for v in vis_list if v["scope"].startswith("group:")]
    grp_html = ""
    if grp_vis:
        labels = [v["scope"].replace("group:", "").title() for v in grp_vis]
        grp_html = _chart_bar("barVisGroup", labels, [
            {"label": "AI Answer SOV", "data": [v["ai_answer_sov"] for v in grp_vis],
             "backgroundColor": "#e07a5f", "borderRadius": 6},
            {"label": "AI Citation SOV", "data": [v["ai_citation_sov"] for v in grp_vis],
             "backgroundColor": "#e9c46a", "borderRadius": 6},
        ], "SOV by Query Group", y_pct=True)

    return f"""
    <section id="visibility">
        <div class="section-header">
            <span class="section-num">03</span>
            <h2>AI Visibility Index</h2>
        </div>
        <div class="chart-grid">
            <div class="glass-card">{radar_html}</div>
            <div class="glass-card">{bar_html}</div>
        </div>
        {f'<div class="glass-card">{grp_html}</div>' if grp_html else ''}
    </section>"""


def _section_zero_click(data: dict) -> str:
    zc = data.get("zero_click_summary", {})
    if zc.get("status") != "SUCCESS":
        return '<section id="zero-click"><div class="section-header"><span class="section-num">04</span><h2>Zero-Click Influence</h2></div><p class="empty-state">No zero-click data.</p></section>'

    sd = zc.get("sentiment_distribution", {})
    sent_chart = _chart_doughnut("doughnutSent",
        ["Positive", "Neutral", "Negative"],
        [sd.get("positive", 0), sd.get("neutral", 0), sd.get("negative", 0)],
        ["#2a9d8f", "#94a3b8", "#bc4749"],
        "Sentiment Distribution")

    bp = zc.get("by_platform", {})
    plat_chart = ""
    if bp:
        plat_labels = [p.title() for p in sorted(bp.keys())]
        plat_data_mention = [bp[p]["ai_answer_sov"] for p in sorted(bp.keys())]
        plat_data_cite = [bp[p]["ai_citation_sov"] for p in sorted(bp.keys())]
        plat_chart = _chart_bar("barZcPlat", plat_labels, [
            {"label": "Mention SOV", "data": plat_data_mention, "backgroundColor": "#2a9d8f", "borderRadius": 6},
            {"label": "Citation SOV", "data": plat_data_cite, "backgroundColor": "#e9c46a", "borderRadius": 6},
        ], "SOV by Platform", y_pct=True)

    metric_items = [
        ("Total Observations", str(zc.get('total_observations', 0))),
        ("AI Answer SOV", _pct(zc.get('ai_answer_sov', 0))),
        ("AI Citation SOV", _pct(zc.get('ai_citation_sov', 0))),
        ("Own Domain Citation", _pct(zc.get('own_domain_citation_rate', 0))),
        ("Zero-Click Mention", _pct(zc.get('zero_click_mention_rate', 0))),
        ("Accuracy Rate", _pct(zc.get('claim_accuracy_rate', 0))),
    ]
    if "dark_influence_gap" in zc:
        metric_items.append(("Dark Influence Gap", _score(zc["dark_influence_gap"])))

    metric_html = ""
    for lbl, val in metric_items:
        metric_html += f'<div class="metric-row"><span class="metric-label">{lbl}</span><span class="metric-value">{val}</span></div>'

    return f"""
    <section id="zero-click">
        <div class="section-header">
            <span class="section-num">04</span>
            <h2>Zero-Click Influence</h2>
        </div>
        <div class="chart-grid tri">
            <div class="glass-card">{sent_chart}</div>
            <div class="glass-card">{plat_chart}</div>
            <div class="glass-card metric-stack">{metric_html}</div>
        </div>
    </section>"""


def _section_entity_authority(data: dict) -> str:
    checks = data.get("entity_checks_data", [])
    if not checks:
        return '<section id="entity"><div class="section-header"><span class="section-num">05</span><h2>Entity Authority</h2></div><p class="empty-state">No entity checks ran.</p></section>'

    found_count = sum(1 for c in checks if c.get("found"))
    not_found = len(checks) - found_count
    doughnut = _chart_doughnut("doughnutEntity",
        ["Found", "Not Found"],
        [found_count, not_found],
        ["#2a9d8f", "#e2e8f0"],
        "Entity Presence")

    rows = ""
    for c in checks:
        found_str = '<span class="pill-found">Found</span>' if c.get("found") else '<span class="pill-missing">Not Found</span>'
        rows += f"""
        <tr>
            <td>{_esc(c.get('check_type', ''))}</td>
            <td class="fw-500">{_esc(c.get('entity_name', ''))}</td>
            <td>{found_str}</td>
            <td>{_status_badge(c.get('status', 'SKIPPED'))}</td>
            <td class="dim">{_esc(c.get('source_api', ''))}</td>
        </tr>"""

    return f"""
    <section id="entity">
        <div class="section-header">
            <span class="section-num">05</span>
            <h2>Entity Authority</h2>
        </div>
        <div class="chart-grid">
            <div class="glass-card">{doughnut}</div>
            <div class="glass-card flex-grow">
                <div class="table-wrap">
                <table>
                    <thead><tr><th>Check</th><th>Entity</th><th>Result</th><th>Status</th><th>Source</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                </div>
            </div>
        </div>
    </section>"""


def _section_referral(data: dict) -> str:
    ref = data.get("referral_summary", {})
    if ref.get("status") != "SUCCESS":
        return '<section id="referral"><div class="section-header"><span class="section-num">06</span><h2>AI Referral Analytics</h2></div><p class="empty-state">No referral data available.</p></section>'

    by_source = ref.get("ai_by_source", {})
    chart = ""
    if by_source:
        labels = list(by_source.keys())
        sessions = [by_source[k]["sessions"] for k in labels]
        chart = _chart_bar("barReferral", labels, [
            {"label": "AI Sessions", "data": sessions, "backgroundColor": "#457b9d", "borderRadius": 6},
        ], "AI Referral Sessions by Source")

    metric_items = [
        ("Total Sessions", f"{ref.get('total_sessions', 0):,}"),
        ("AI Sessions", f"{ref.get('ai_sessions', 0):,}"),
        ("AI Session Share", _pct(ref.get('ai_session_share', 0))),
        ("Total Conversions", f"{ref.get('total_conversions', 0):,}"),
        ("AI Conversions", f"{ref.get('ai_conversions', 0):,}"),
        ("AI Conversion Share", _pct(ref.get('ai_conversion_share', 0))),
    ]
    metric_html = ""
    for lbl, val in metric_items:
        metric_html += f'<div class="metric-row"><span class="metric-label">{lbl}</span><span class="metric-value">{val}</span></div>'

    return f"""
    <section id="referral">
        <div class="section-header">
            <span class="section-num">06</span>
            <h2>AI Referral Analytics</h2>
        </div>
        <div class="chart-grid">
            <div class="glass-card">{chart}</div>
            <div class="glass-card metric-stack">{metric_html}</div>
        </div>
    </section>"""


def _section_brand_demand(data: dict) -> str:
    dem = data.get("demand_summary", {})
    demand_records = data.get("demand_records_data", [])

    if dem.get("status") != "SUCCESS" and not demand_records:
        return '<section id="demand"><div class="section-header"><span class="section-num">07</span><h2>Brand Demand Trends</h2></div><p class="empty-state">No brand demand data.</p></section>'

    line_chart = ""
    if demand_records:
        by_kw: dict[str, list[tuple[str, int]]] = {}
        for r in demand_records:
            by_kw.setdefault(r.get("keyword", "?"), []).append(
                (r.get("date", ""), r.get("interest_value", 0))
            )
        all_dates = sorted({r.get("date", "") for r in demand_records})
        datasets = []
        for i, (kw, pts) in enumerate(by_kw.items()):
            pt_map = {d: v for d, v in pts}
            c = _CHART_COLORS[i % len(_CHART_COLORS)]
            datasets.append({
                "label": kw,
                "data": [pt_map.get(d, 0) for d in all_dates],
                "borderColor": c,
                "backgroundColor": "transparent",
                "tension": 0.35,
                "borderWidth": 2.5,
                "pointRadius": 3,
                "pointBackgroundColor": c,
            })
        line_chart = _chart_line("lineDemand", all_dates, datasets, "Interest Over Time (Google Trends)")

    kw_data = dem.get("keywords", {})
    kw_rows = ""
    for kw, info in kw_data.items():
        trend_pct = info.get("trend_pct_change", 0)
        arrow = "&#9650;" if trend_pct >= 0 else "&#9660;"
        trend_color = "#2a9d8f" if trend_pct >= 0 else "#bc4749"
        brand_pill = '<span class="pill-brand">Brand</span>' if info.get('is_brand') else ''
        kw_rows += f"""
        <tr>
            <td class="fw-500">{_esc(kw)} {brand_pill}</td>
            <td class="num">{info.get('mean_interest', 0):.1f}</td>
            <td class="num">{info.get('latest_interest', 0)}</td>
            <td class="num" style="color:{trend_color}">{arrow} {trend_pct:+.1f}%</td>
        </tr>"""

    return f"""
    <section id="demand">
        <div class="section-header">
            <span class="section-num">07</span>
            <h2>Brand Demand Trends</h2>
        </div>
        {f'<div class="glass-card">{line_chart}</div>' if line_chart else ''}
        <div class="glass-card" style="margin-top:16px">
        <div class="table-wrap">
        <table>
            <thead><tr><th>Keyword</th><th>Mean Interest</th><th>Latest</th><th>Trend</th></tr></thead>
            <tbody>{kw_rows}</tbody>
        </table>
        </div>
        </div>
    </section>"""


def _section_observations_table(data: dict) -> str:
    obs = data.get("observations_data", [])
    if not obs:
        return '<section id="observations"><div class="section-header"><span class="section-num">08</span><h2>Observation Log</h2></div><p class="empty-state">No observations recorded.</p></section>'

    rows = ""
    for o in obs[:200]:
        m_dot = '<span class="dot dot-yes"></span>' if o.get('brand_mentioned') else '<span class="dot dot-no"></span>'
        c_dot = '<span class="dot dot-yes"></span>' if o.get('brand_cited') else '<span class="dot dot-no"></span>'
        a_dot = '<span class="dot dot-yes"></span>' if o.get('accuracy_flag') else '<span class="dot dot-warn"></span>'
        rows += f"""
        <tr>
            <td class="dim">{_esc(o.get('date', ''))}</td>
            <td><span class="platform-pill">{_esc(o.get('platform', ''))}</span></td>
            <td>{_esc(o.get('query_group', ''))}</td>
            <td class="query-cell">{_esc(o.get('query', ''))}</td>
            <td class="center">{m_dot}</td>
            <td class="center">{c_dot}</td>
            <td class="num">{o.get('prominence_score', 0)}</td>
            <td class="num">{o.get('sentiment_score', 0)}</td>
            <td class="center">{a_dot}</td>
            <td>{_status_badge(o.get('status', 'SUCCESS'))}</td>
        </tr>"""

    return f"""
    <section id="observations">
        <div class="section-header">
            <span class="section-num">08</span>
            <h2>Observation Log</h2>
        </div>
        <p class="section-sub">Showing up to 200 of {len(obs)} observations.</p>
        <div class="glass-card">
        <div class="table-wrap">
        <table class="obs-table">
            <thead>
                <tr>
                    <th>Date</th><th>Platform</th><th>Group</th><th>Query</th>
                    <th class="center">Ment.</th><th class="center">Cited</th><th>Prom.</th>
                    <th>Sent.</th><th class="center">Acc.</th><th>Status</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        </div>
        </div>
    </section>"""


# ---------------------------------------------------------------------------
# CSS — warm glassmorphic light-mode
# ---------------------------------------------------------------------------

_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=JetBrains+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --bg: #1f427683;
        --bg-overlay: #ddd5c882;

    --glass: rgba(255,255,255,0.22);
    --glass-strong: rgba(255,255,255,0.32);
    --glass-border: rgba(255,255,255,0.45);
    --glass-border-strong: rgba(255,255,255,0.60);
    --glass-shadow: 0 8px 32px rgba(0,0,0,0.06), 0 1.5px 4px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,0.5);
    --glass-shadow-hover: 0 12px 48px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.05), inset 0 1px 0 rgba(255,255,255,0.6);
    --text: #1e293b;
    --text-secondary: #334155;
    --text-dim: #475569;
    --accent: #2a9d8f;
    --accent2: #457b9d;
    --radius: 20px;
    --radius-sm: 14px;
    --blur: 20px;
    --blur-heavy: 36px;
}

body {
    font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.65;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
    position: relative;
    overflow-x: hidden;
}

/* Layered ambient gradient blobs for depth */
body::before, body::after {
    content: '';
    position: fixed;
    border-radius: 50%;
    pointer-events: none;
    z-index: 0;
}
body::before {
    width: 900px; height: 900px;
    top: -200px; left: -200px;
    background: radial-gradient(circle, rgba(168,198,162,0.7) 0%, rgba(200,213,185,0.4) 40%, transparent 70%);
    filter: blur(80px);
}
body::after {
    width: 800px; height: 800px;
    bottom: -150px; right: -200px;
    background: radial-gradient(circle, rgba(244,162,97,0.5) 0%, rgba(233,196,106,0.3) 40%, transparent 70%);
    filter: blur(80px);
    background: var(--bg-overlay);
}
.bg-blob-mid {
    position: fixed;
    width: 600px; height: 600px;
    top: 40%; left: 50%;
    transform: translate(-50%, -50%);
    background: radial-gradient(circle, rgba(138,180,200,0.3) 0%, transparent 65%);
    filter: blur(90px);
    pointer-events: none;
    z-index: 0;
    border-radius: 50%;
}
.bg-blob-top-right {
    position: fixed;
    width: 500px; height: 500px;
    top: -80px; right: 10%;
    background: radial-gradient(circle, rgba(233,196,106,0.35) 0%, transparent 65%);
    filter: blur(70px);
    pointer-events: none;
    z-index: 0;
    border-radius: 50%;
}

.report-wrap {
    position: relative;
    z-index: 1;
    max-width: 1320px;
    margin: 0 auto;
    padding: 48px 36px 80px;
}

/* ---- Header ---- */
header {
    margin-bottom: 40px;
    padding: 32px 36px;
    background: var(--glass);
    backdrop-filter: blur(var(--blur-heavy));
    -webkit-backdrop-filter: blur(var(--blur-heavy));
    border: 1px solid var(--glass-border-strong);
    border-radius: var(--radius);
    box-shadow: var(--glass-shadow);
    position: relative;
    overflow: hidden;
}
header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.8), transparent);
    pointer-events: none;
}
header h1 {
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: -0.04em;
    color: var(--text);
    line-height: 1.15;
}
header h1 span {
    display: block;
    font-size: 0.95rem;
    font-weight: 500;
    color: var(--text-secondary);
    letter-spacing: 0;
    margin-top: 4px;
}
header .meta {
    margin-top: 10px;
    font-size: 0.78rem;
    color: var(--text-secondary);
    font-family: 'JetBrains Mono', monospace;
}

/* ---- Nav pills ---- */
nav {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 44px;
    padding: 10px 14px;
    background: var(--glass);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    border: 1px solid var(--glass-border);
    border-radius: 100px;
    box-shadow: var(--glass-shadow);
    width: fit-content;
}
nav a {
    display: inline-block;
    padding: 8px 18px;
    border-radius: 100px;
    font-size: 0.78rem;
    font-weight: 600;
    color: #273449;
    text-decoration: none;
    background: rgba(255,255,255,0.18);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(255,255,255,0.30);
    transition: all 0.25s ease;
}
nav a:hover {
    color: var(--accent);
    background: rgba(42,157,143,0.12);
    border-color: rgba(42,157,143,0.35);
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(42,157,143,0.12);
}

/* ---- Sections ---- */
section { margin-bottom: 52px; }
.section-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 22px;
}
.section-header h2 {
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--text);
}
.section-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px; height: 34px;
    border-radius: 11px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--accent);
    background: rgba(42,157,143,0.12);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(42,157,143,0.15);
    box-shadow: 0 2px 8px rgba(42,157,143,0.08);
    flex-shrink: 0;
}
.section-sub {
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin: -12px 0 16px 44px;
}

/* ---- Glass cards ---- */
.glass-card {
    background: var(--glass);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    padding: 28px;
    box-shadow: var(--glass-shadow);
    transition: box-shadow 0.3s ease, transform 0.25s ease, background 0.3s ease;
    position: relative;
    overflow: hidden;
}
.glass-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.7), transparent);
    pointer-events: none;
}
.glass-card:hover {
    box-shadow: var(--glass-shadow-hover);
    background: var(--glass-strong);
    transform: translateY(-2px);
}

/* ---- KPI Grid ---- */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
}
.kpi-card {
    background: var(--glass);
    backdrop-filter: blur(var(--blur-heavy));
    -webkit-backdrop-filter: blur(var(--blur-heavy));
    border: 1px solid var(--glass-border-strong);
    border-radius: var(--radius);
    padding: 22px 20px 20px;
    box-shadow: var(--glass-shadow);
    transition: transform 0.3s ease, box-shadow 0.3s ease, background 0.3s ease;
    position: relative;
    overflow: hidden;
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent 10%, rgba(255,255,255,0.8) 50%, transparent 90%);
    pointer-events: none;
}
.kpi-card::after {
    content: '';
    position: absolute;
    top: -40%; right: -30%;
    width: 120px; height: 120px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.15), transparent 70%);
    pointer-events: none;
}
.kpi-card:hover {
    transform: translateY(-4px) scale(1.01);
    box-shadow: var(--glass-shadow-hover);
    background: var(--glass-strong);
}
.kpi-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px; height: 36px;
    border-radius: 10px;
    margin-bottom: 12px;
}
.kpi-value {
    font-size: 1.9rem;
    font-weight: 800;
    letter-spacing: -0.05em;
    font-family: 'Plus Jakarta Sans', sans-serif;
    line-height: 1.1;
}
.kpi-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 2px;
}
.kpi-sub {
    font-size: 0.7rem;
    color: var(--text-secondary);
    margin-top: 6px;
}

/* ---- Chart grid ---- */
.chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 16px;
    margin-bottom: 16px;
}
.chart-grid.tri {
    grid-template-columns: repeat(3, 1fr);
}
.flex-grow { flex: 1; }

/* ---- Metric stack (inside glass cards) ---- */
.metric-stack {
    display: flex;
    flex-direction: column;
    gap: 0;
    justify-content: center;
}
.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 11px 4px;
    border-bottom: 1px solid rgba(255,255,255,0.25);
}
.metric-row:last-child { border-bottom: none; }
.metric-label {
    font-size: 0.82rem;
    color: var(--text-secondary);
    font-weight: 500;
}
.metric-value {
    font-size: 0.88rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: var(--text);
}

/* ---- Tables ---- */
.table-wrap {
    overflow-x: auto;
    background: var(--glass);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    box-shadow: var(--glass-shadow);
}
.glass-card > .table-wrap {
    background: rgba(255,255,255,0.08);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    border: none;
    border-radius: var(--radius-sm);
    box-shadow: none;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
}
thead th {
    text-align: left;
    padding: 12px 16px;
    color: var(--text-secondary);
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    border-bottom: 1px solid rgba(255,255,255,0.35);
    white-space: nowrap;
    background: rgba(255,255,255,0.10);
}
tbody td {
    padding: 11px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.18);
    vertical-align: middle;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: rgba(255,255,255,0.15); }
.num {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    text-align: right;
    font-weight: 500;
}
.center { text-align: center; }
.dim { color: var(--text-secondary); }
.fw-500 { font-weight: 600; }
.mod-name { font-weight: 600; color: var(--text); }
.query-cell {
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* ---- Badges & pills ---- */
.badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 0.67rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.03em;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    border: 1px solid rgba(255,255,255,0.20);
}
.pill-found {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 100px;
    font-size: 0.7rem;
    font-weight: 600;
    background: rgba(42,157,143,0.15);
    color: #2a9d8f;
    border: 1px solid rgba(42,157,143,0.20);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}
.pill-missing {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 100px;
    font-size: 0.7rem;
    font-weight: 600;
    background: rgba(148,163,184,0.12);
    color: #475569;
    border: 1px solid rgba(148,163,184,0.18);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}
.pill-brand {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 100px;
    font-size: 0.62rem;
    font-weight: 700;
    background: rgba(42,157,143,0.12);
    color: #2a9d8f;
    margin-left: 6px;
    vertical-align: middle;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.platform-pill {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 100px;
    font-size: 0.72rem;
    font-weight: 600;
    background: rgba(69,123,157,0.12);
    color: #457b9d;
    text-transform: capitalize;
    border: 1px solid rgba(69,123,157,0.15);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}
.dot {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 50%;
}
.dot-yes { background: #2a9d8f; }
.dot-no { background: #e2e8f0; }
.dot-warn { background: #e9c46a; }

.empty-state {
    color: var(--text-secondary);
    font-style: italic;
    padding: 32px 20px;
    text-align: center;
    background: var(--glass);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    border-radius: var(--radius);
    border: 1px dashed rgba(255,255,255,0.35);
    box-shadow: var(--glass-shadow);
}

/* ---- Footer ---- */
footer {
    margin-top: 32px;
    padding: 24px 28px;
    background: var(--glass);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    box-shadow: var(--glass-shadow);
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-align: center;
    font-family: 'JetBrains Mono', monospace;
}

/* ---- Print ---- */
@media print {
    body::before, body::after, .bg-blob-mid, .bg-blob-top-right { display: none; }
    body { background: #fff; }
    .glass-card, .kpi-card, header, nav, footer, .table-wrap { backdrop-filter: none; -webkit-backdrop-filter: none; background: #f9fafb; border-color: #e5e7eb; box-shadow: none; }
    .glass-card::before, .kpi-card::before, .kpi-card::after, header::before { display: none; }
    nav { display: none; }
}

@media (max-width: 900px) {
    .chart-grid, .chart-grid.tri { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
    .report-wrap { padding: 24px 16px 48px; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .chart-grid, .chart-grid.tri { grid-template-columns: 1fr; }
    header h1 { font-size: 1.6rem; }
}
"""


def compile_report_html(data: dict) -> str:
    """Generate a self-contained HTML report string from measurement data."""
    ts = data.get("run_timestamp", datetime.now(timezone.utc).isoformat())

    nav_items = [
        ("executive-summary", "Executive Summary"),
        ("module-status", "Modules"),
        ("visibility", "Visibility Index"),
        ("zero-click", "Zero-Click"),
        ("entity", "Entity Authority"),
        ("referral", "Referrals"),
        ("demand", "Brand Demand"),
        ("observations", "Observations"),
    ]
    nav_html = "".join(f'<a href="#{eid}">{label}</a>' for eid, label in nav_items)

    sections = "".join([
        _section_executive_summary(data),
        _section_module_status(data),
        _section_visibility_index(data),
        _section_zero_click(data),
        _section_entity_authority(data),
        _section_referral(data),
        _section_brand_demand(data),
        _section_observations_table(data),
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI PR Measurement Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="bg-blob-mid"></div>
<div class="bg-blob-top-right"></div>
<script>{_CHART_DEFAULTS_JS}</script>
<div class="report-wrap">
    <header>
        <h1>AI PR Measurement<span>Narrative Pulse Engine &middot; Intelligence Report</span></h1>
        <div class="meta">{_esc(ts[:10])} &middot; Generated {_esc(ts)} UTC</div>
    </header>
    <nav>{nav_html}</nav>
    {sections}
    <footer>
        AI PR Measurement System &middot; Narrative Pulse Engine
        &middot; {_esc(ts[:10])}
    </footer>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def compile_report_from_result(result: Any, output_path: str) -> str:
    """Compile an HTML report from an OrchestratorResult object.

    Returns the output file path.
    """
    data = result.to_dict()

    data["observations_data"] = [o.model_dump() for o in result.observations]
    data["entity_checks_data"] = [
        ec.model_dump() if hasattr(ec, "model_dump") else ec
        for ec in result.entity_checks
    ]
    data["demand_records_data"] = [
        r.model_dump() if hasattr(r, "model_dump") else r
        for r in result.demand_records
    ]

    html_content = compile_report_html(data)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("HTML report written to %s", output_path)
    return output_path


def compile_report_from_output_dir(output_dir: str, report_filename: str = "report.html") -> str:
    """Compile an HTML report by reading JSON files from a previous run's output directory.

    Returns the output file path.
    """
    def _load_json(name: str) -> Any:
        p = os.path.join(output_dir, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    summary = _load_json("run_summary.json")
    data = dict(summary)
    data["entity_checks_data"] = _load_json("entity_checks.json") or []
    data["referral_summary"] = data.get("referral_summary") or _load_json("referral_summary.json")
    data["demand_summary"] = data.get("demand_summary") or _load_json("demand_summary.json")
    data["zero_click_summary"] = data.get("zero_click_summary") or _load_json("zero_click_summary.json")
    data["visibility_indices"] = data.get("visibility_indices") or _load_json("visibility_index.json") or []
    data["demand_records_data"] = []
    data["observations_data"] = []

    obs_csv_path = os.path.join(output_dir, "observations_full.csv")
    if os.path.exists(obs_csv_path):
        import csv as csv_mod
        with open(obs_csv_path, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                for int_field in ("brand_mentioned", "brand_cited", "own_domain_cited",
                                  "prominence_score", "sentiment_score", "accuracy_flag",
                                  "actionability"):
                    if int_field in row and row[int_field]:
                        try:
                            row[int_field] = int(row[int_field])
                        except ValueError:
                            pass
                for float_field in ("business_value", "risk_level"):
                    if float_field in row and row[float_field]:
                        try:
                            row[float_field] = float(row[float_field])
                        except ValueError:
                            pass
                data["observations_data"].append(row)

    html_content = compile_report_html(data)
    report_path = os.path.join(output_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("HTML report written to %s", report_path)
    return report_path
