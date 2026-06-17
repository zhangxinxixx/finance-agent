"""Deterministic standalone HTML renderer for CME options visual reports."""

from __future__ import annotations

from html import escape

from apps.analysis.options.visual_report import (
    OptionsVisualReportVM,
    VisualLevelRow,
    VisualMetricCard,
    VisualMetricRow,
    VisualScenarioRow,
    VisualWallRow,
)


def render_options_visual_html(vm: OptionsVisualReportVM) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(vm.hero_title)}</title>
  <style>
    :root {{
      --bg: #0c1017;
      --panel: #121926;
      --panel-2: #172132;
      --text: #edf2fb;
      --muted: #91a0b8;
      --line: rgba(255,255,255,0.08);
      --gold: #d8b15d;
      --red: #e07a7a;
      --green: #6cc59d;
      --blue: #7aa7ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top, rgba(122,167,255,.12), transparent 32%), var(--bg);
      color: var(--text);
      font: 14px/1.6 "Segoe UI", "PingFang SC", sans-serif;
    }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px 48px; }}
    .hero, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; }}
    .hero {{ padding: 24px; margin-bottom: 20px; }}
    .hero h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .sub {{ color: var(--muted); margin-bottom: 12px; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
    .tag {{ border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; color: var(--gold); font-size: 12px; }}
    .conclusion {{ padding: 14px 16px; background: var(--panel-2); border-left: 3px solid var(--gold); border-radius: 10px; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(12, minmax(0, 1fr)); }}
    .col-6 {{ grid-column: span 6; }}
    .col-4 {{ grid-column: span 4; }}
    .col-12 {{ grid-column: span 12; }}
    .panel {{ padding: 18px; }}
    .panel h2 {{ margin: 0 0 14px; font-size: 16px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .metric-card {{ padding: 12px; background: var(--panel-2); border-radius: 12px; }}
    .metric-label {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .metric-value {{ font-size: 18px; }}
    .list {{ display: grid; gap: 8px; }}
    .row {{ padding: 10px 12px; background: var(--panel-2); border-radius: 12px; }}
    .row strong {{ display: block; margin-bottom: 4px; }}
    .muted {{ color: var(--muted); }}
    .tone-bullish {{ color: var(--green); }}
    .tone-bearish {{ color: var(--red); }}
    .tone-warning {{ color: var(--gold); }}
    .tone-info {{ color: var(--blue); }}
    .source-list {{ padding-left: 18px; }}
    @media (max-width: 900px) {{
      .col-6, .col-4 {{ grid-column: span 12; }}
      .metric-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>{escape(vm.hero_title)}</h1>
      <div class="sub">{escape(vm.hero_subtitle)}</div>
      <div class="tags">{''.join(f'<span class="tag">{escape(tag)}</span>' for tag in vm.tags)}</div>
      <div class="conclusion">{escape(vm.core_conclusion)}</div>
    </section>

    <section class="grid">
      <div class="panel col-6">
        <h2>模型参数</h2>
        <div class="list">{_render_metric_rows(vm.model_parameters)}</div>
      </div>
      <div class="panel col-6">
        <h2>关键指标</h2>
        <div class="metric-grid">{_render_metric_cards(vm.key_metrics)}</div>
      </div>

      <div class="panel col-6">
        <h2>GEX Top Walls</h2>
        <div class="list">{_render_wall_rows(vm.gex_top_walls)}</div>
      </div>
      <div class="panel col-6">
        <h2>WallScore</h2>
        <div class="list">{_render_wall_rows(vm.wall_scores)}</div>
      </div>

      <div class="panel col-6">
        <h2>GEX 变化</h2>
        <div class="list">{_render_metric_rows(vm.gex_changes)}</div>
      </div>
      <div class="panel col-6">
        <h2>IV Skew</h2>
        <div class="list">{_render_metric_rows(vm.iv_skew_rows)}</div>
      </div>

      <div class="panel col-6">
        <h2>Support Levels</h2>
        <div class="list">{_render_levels(vm.support_levels)}</div>
      </div>
      <div class="panel col-6">
        <h2>Resistance Levels</h2>
        <div class="list">{_render_levels(vm.resistance_levels)}</div>
      </div>

      <div class="panel col-4">
        <h2>Call OI Walls</h2>
        <div class="list">{_render_metric_rows(vm.call_oi_walls)}</div>
      </div>
      <div class="panel col-4">
        <h2>Put OI Walls</h2>
        <div class="list">{_render_metric_rows(vm.put_oi_walls)}</div>
      </div>
      <div class="panel col-4">
        <h2>Greeks</h2>
        <div class="metric-grid">{_render_metric_cards(vm.greeks)}</div>
      </div>

      <div class="panel col-6">
        <h2>Scenario Matrix</h2>
        <div class="list">{_render_scenarios(vm.scenarios)}</div>
      </div>
      <div class="panel col-6">
        <h2>Switches</h2>
        <div class="list">{_render_metric_rows(vm.switches)}</div>
      </div>

      <div class="panel col-6">
        <h2>Roll Structure</h2>
        <div class="list">{_render_metric_rows(vm.roll_structure)}</div>
      </div>
      <div class="panel col-6">
        <h2>Institutional Intent</h2>
        <div class="row">{escape(vm.institutional_intent)}</div>
      </div>

      <div class="panel col-6">
        <h2>Data Quality Notes</h2>
        <div class="list">{_render_notes(vm.data_quality_notes)}</div>
      </div>
      <div class="panel col-6">
        <h2>Source Refs</h2>
        <ul class="source-list">{''.join(f'<li>{escape(str(ref))}</li>' for ref in vm.source_refs)}</ul>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _render_metric_rows(rows: list[VisualMetricRow]) -> str:
    return "".join(
        f'<div class="row"><strong class="tone-{escape(row.tone)}">{escape(row.label)} · {escape(row.value)}</strong><div class="muted">{escape(row.note)}</div></div>'
        for row in rows
    )


def _render_metric_cards(cards: list[VisualMetricCard]) -> str:
    return "".join(
        f'<div class="metric-card"><div class="metric-label">{escape(card.label)}</div><div class="metric-value tone-{escape(card.tone)}">{escape(card.value)}</div><div class="muted">{escape(card.change)}</div></div>'
        for card in cards
    )


def _render_wall_rows(rows: list[VisualWallRow]) -> str:
    return "".join(
        f'<div class="row"><strong class="tone-{escape(row.tone)}">{escape(row.strike)} · {escape(row.wall_type)}</strong><div class="muted">{escape(row.expiry)} · net GEX {escape(row.net_gex)} · score {escape(row.wall_score)}</div></div>'
        for row in rows
    )


def _render_levels(rows: list[VisualLevelRow]) -> str:
    return "".join(
        f'<div class="row"><strong class="tone-{escape(row.tone)}">{escape(row.strike)}</strong><div class="muted">{escape(row.wall_type)} · score {escape(row.wall_score)} · distance {escape(row.distance_pct)}</div></div>'
        for row in rows
    )


def _render_scenarios(rows: list[VisualScenarioRow]) -> str:
    return "".join(
        f'<div class="row"><strong class="tone-{escape(row.tone)}">{escape(row.title)}</strong><div class="muted">{escape(row.detail)}</div></div>'
        for row in rows
    )


def _render_notes(notes: list[str]) -> str:
    return "".join(
        f'<div class="row"><div class="muted">{escape(note)}</div></div>'
        for note in notes
    )
