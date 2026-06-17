from __future__ import annotations

import html

from apps.documents.schemas import Jin10DailyAnalysisReport


def render_jin10_daily_html(report: Jin10DailyAnalysisReport) -> str:
    title = html.escape(report.title)
    conclusion = html.escape(report.core_conclusion)
    prices = _list_items(report.market_prices, lambda item: f"{item.get('label')}: {item.get('value')}")
    logic = _list_items(report.logic_chains, lambda item: f"{item.get('label')}: {item.get('summary')}")
    watch = _list_items(report.watch_variables, lambda item: f"{item.get('label')} [{item.get('status')}]")
    levels = _list_items(report.key_levels, lambda item: f"{item.get('label')}: {item.get('value')}")
    scenarios = _list_items(report.scenario_matrix, lambda item: f"{item.get('scenario')} ({item.get('confidence')}): {item.get('summary')}")
    risks = _list_items(report.risks, lambda item: f"{item.get('label')}: {item.get('summary')}")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ --bg:#f3efe6; --card:#fffaf2; --ink:#201a14; --muted:#6d5d4b; --accent:#aa5a1c; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family: "Noto Serif SC", "Source Han Serif SC", serif; background:linear-gradient(180deg,#f7f1e7 0%,#efe4d2 100%); color:var(--ink); }}
    main {{ max-width:1100px; margin:0 auto; padding:32px 20px 48px; }}
    .hero {{ padding:28px; border-radius:24px; background:var(--card); box-shadow:0 24px 80px rgba(50,33,14,.12); }}
    h1 {{ margin:0 0 12px; font-size:34px; line-height:1.2; }}
    .meta {{ color:var(--muted); font-size:14px; }}
    .lead {{ margin-top:18px; font-size:18px; line-height:1.7; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:18px; margin-top:22px; }}
    section {{ margin-top:22px; padding:20px; border-radius:20px; background:rgba(255,250,242,.9); box-shadow:0 12px 48px rgba(64,39,13,.08); }}
    h2 {{ margin:0 0 12px; font-size:18px; }}
    ul {{ margin:0; padding-left:18px; line-height:1.65; }}
  </style>
</head>
<body>
  <main>
    <div class="hero">
      <div class="meta">Jin10 黄金每日报告 · {html.escape(report.trade_date)} · run_id {html.escape(report.run_id)}</div>
      <h1>{title}</h1>
      <div class="lead">{conclusion}</div>
    </div>
    <div class="grid">
      <section><h2>市场价格</h2><ul>{prices}</ul></section>
      <section><h2>关键位</h2><ul>{levels}</ul></section>
      <section><h2>观察变量</h2><ul>{watch}</ul></section>
      <section><h2>风险提示</h2><ul>{risks}</ul></section>
    </div>
    <section><h2>逻辑链</h2><ul>{logic}</ul></section>
    <section><h2>情景矩阵</h2><ul>{scenarios}</ul></section>
  </main>
</body>
</html>
"""


def _list_items(items: list[dict[str, object]], render) -> str:
    if not items:
        return "<li>未提及</li>"
    return "".join(f"<li>{html.escape(str(render(item) or '未提及'))}</li>" for item in items)
