from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def render_daily_brief_markdown(snapshot: Mapping[str, Any] | Any) -> str:
    data = _snapshot_dict(snapshot)
    if not bool(data.get("should_generate")) or data.get("report_mode") == "empty":
        return _render_empty_flash(data)

    lines: list[str] = [
        "# 每日市场快讯",
        "",
        f"- date: {_text(data.get('date'))}",
        f"- run_id: {_text(data.get('run_id'))}",
        f"- report_mode: {_text(data.get('report_mode'))}",
        "",
        "## 一句话结论",
        "",
        _one_line_conclusion(data),
        "",
        "## 分析溯源 / 数据来源",
        "",
        *(_render_source_refs(_list(data.get("source_refs"))) or ["- unavailable"]),
        "",
        "### 质量标记",
        "",
        *_bullets(_list(data.get("quality_flags")) or ["none"]),
        "",
        "## 今日市场状态总览",
        "",
        *_render_core_events(_list(data.get("core_events"))),
        "",
        "### 重点文章 / 报告",
        "",
        *_render_key_articles(_list(data.get("key_articles"))),
        "",
        "## 今日为什么变动",
        "",
        *_render_market_reactions(_list(data.get("market_reactions"))),
        "",
        "## 为什么还不能确认趋势",
        "",
        *_render_limits(data),
        "",
        "## 阶段判断更新",
        "",
        *_render_stage(data),
        "",
        "## 关键位",
        "",
        *_render_key_levels(_dict(data.get("key_levels"))),
        "",
        "## 三条路径推演",
        "",
        *_render_scenarios(_list(data.get("scenario_inputs"))),
        "",
        "## 操作层理解",
        "",
        "该部分只给研究分析口径：先确认事件来源、行情验证和关键位状态，再判断后续日报是否需要升级为完整分析。",
        "",
        "## 最终综合判断",
        "",
        _final_judgement(data),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_daily_brief_payload(
    snapshot: Mapping[str, Any] | Any,
    *,
    markdown: str | None = None,
    artifact_path: str | None = None,
    input_snapshot_path: str | None = None,
) -> dict[str, Any]:
    data = _snapshot_dict(snapshot)
    rendered_markdown = markdown if markdown is not None else render_daily_brief_markdown(data)
    if not bool(data.get("should_generate")) or data.get("report_mode") == "empty":
        status = "empty"
    elif _list(data.get("quality_flags")):
        status = "partial"
    else:
        status = "available"
    return {
        "status": status,
        "date": data.get("date"),
        "run_id": data.get("run_id"),
        "report_mode": data.get("report_mode"),
        "artifact_path": artifact_path,
        "input_snapshot_path": input_snapshot_path,
        "markdown": rendered_markdown,
        "structured": {
            "core_event_count": len(_list(data.get("core_events"))),
            "key_article_count": len(_list(data.get("key_articles"))),
            "market_reaction_count": len(_list(data.get("market_reactions"))),
            "risk_flag_count": len(_list(data.get("risk_flags"))),
            "key_levels": _dict(data.get("key_levels")),
            "one_line_inputs": _list(data.get("one_line_inputs")),
        },
        "source_refs": _list(data.get("source_refs")),
        "quality_flags": _list(data.get("quality_flags")),
    }


def archive_daily_brief(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    snapshot: Mapping[str, Any] | Any,
) -> dict[str, str]:
    markdown_path = storage_root / "outputs" / "daily_brief" / retrieved_date / run_id / "daily_brief.md"
    json_path = storage_root / "outputs" / "daily_brief" / retrieved_date / run_id / "daily_brief.json"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = markdown_path.relative_to(storage_root).as_posix()
    input_snapshot_path = f"features/news/{retrieved_date}/{run_id}/daily_brief_input_snapshot.json"
    markdown = render_daily_brief_markdown(snapshot)
    payload = render_daily_brief_payload(
        snapshot,
        markdown=markdown,
        artifact_path=artifact_path,
        input_snapshot_path=input_snapshot_path,
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "markdown": artifact_path,
        "json": json_path.relative_to(storage_root).as_posix(),
    }


def _render_empty_flash(data: dict[str, Any]) -> str:
    lines = [
        "# 每日市场快讯｜小快讯",
        "",
        f"- date: {_text(data.get('date'))}",
        f"- run_id: {_text(data.get('run_id'))}",
        f"- report_mode: {_text(data.get('report_mode') or 'empty')}",
        "",
        "暂无足够输入生成完整日报。",
        "",
        "## 质量标记",
        "",
        *_bullets(_list(data.get("quality_flags")) or ["no_actionable_inputs"]),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _one_line_conclusion(data: dict[str, Any]) -> str:
    events = [_dict(item) for item in _list(data.get("core_events"))]
    if events:
        event = events[0]
        validation = (
            "已获行情阈值确认"
            if any(bool(_dict(item).get("threshold_hit")) for item in _list(data.get("market_reactions")))
            else "尚缺行情阈值确认，仅作待验证主线"
        )
        event_summary = (
            _text(event.get("what_happened"))
            or _text(event.get("title"))
            or "核心事件待确认"
        )
        impact = {
            "bullish": "利多",
            "bearish": "利空",
            "neutral": "中性",
            "mixed": "多空交织",
        }.get(_text(event.get("gold_impact")).lower(), "待确认")
        pricing = {
            "fully_priced": "已充分定价",
            "partially_priced": "部分定价",
            "not_priced": "尚未定价",
            "unpriced": "尚未定价",
        }.get(_text(event.get("pricing_status")).lower(), "待确认")
        return (
            f"今日主线：{event_summary}；黄金影响评估为{impact}，"
            f"市场处于{pricing}状态，{validation}。"
        )

    articles = [_dict(item) for item in _list(data.get("key_articles"))]
    if articles:
        return (
            f"报告主线：{_text(articles[0].get('headline'))}；"
            "尚缺独立事件与行情验证，当前仅作研究线索。"
        )

    inputs = [str(item) for item in _list(data.get("one_line_inputs")) if str(item).strip()]
    if inputs:
        return f"待验证主线：{inputs[0]}；当前没有足够结构化证据形成稳定方向结论。"
    return "当前没有足够输入形成稳定结论。"


def _render_core_events(events: list[Any]) -> list[str]:
    if not events:
        return ["- 暂无可用核心事件。"]
    lines: list[str] = []
    for event in (_dict(item) for item in events[:6]):
        lines.extend(
            [
                f"- {_text(event.get('what_happened'))}",
                f"  - event_id: {_text(event.get('event_id'))}",
                f"  - event_type: {_text(event.get('event_type'))}",
                f"  - source_confidence: {_text(event.get('source_confidence'))}",
                f"  - impact_path: {_text(event.get('impact_path'))}",
                f"  - gold_impact: {_text(event.get('gold_impact'))}",
                f"  - pricing_status: {_text(event.get('pricing_status'))}",
            ]
        )
    return lines


def _render_market_reactions(reactions: list[Any]) -> list[str]:
    if not reactions:
        return ["- 暂无行情验证，需等待价格、美元、美债或油价反应。"]
    lines: list[str] = []
    for reaction in (_dict(item) for item in reactions[:8]):
        move = reaction.get("pct_change")
        if move is None:
            move = reaction.get("change_bp")
        lines.append(
            "- "
            f"{_text(reaction.get('asset'))} {_text(reaction.get('window'))}: "
            f"{_text(reaction.get('direction'))}, change={_text(move)}, "
            f"threshold_hit={_text(reaction.get('threshold_hit'))}, "
            f"pricing_status={_text(reaction.get('pricing_status'))}"
        )
    return lines


def _render_key_articles(articles: list[Any]) -> list[str]:
    if not articles:
        return ["- 暂无重点文章输入。"]
    lines: list[str] = []
    for article in (_dict(item) for item in articles[:5]):
        lines.extend(
            [
                f"- {_text(article.get('headline'))}",
                f"  - article_class: {_text(article.get('article_class'))}",
                f"  - source_confidence: {_text(article.get('source_confidence'))}",
                f"  - access_status: {_text(article.get('access_status'))}",
                f"  - source_url: {_text(article.get('source_url'))}",
                f"  - analysis_summary: {_text(article.get('analysis_summary'))}",
            ]
        )
        key_points = _list(article.get("key_points"))
        if key_points:
            lines.append("  - key_points:")
            lines.extend(f"    - {_text(point)}" for point in key_points[:5])
    return lines


def _render_limits(data: dict[str, Any]) -> list[str]:
    flags = _list(data.get("quality_flags"))
    risks = _list(data.get("risk_flags"))
    lines: list[str] = []
    if flags:
        lines.append("当前限制来自数据质量标记：")
        lines.extend(_bullets(flags))
    if risks:
        lines.append("当前风险标记：")
        lines.extend(_bullets(risks))
    if not lines:
        lines.append("- 暂无额外限制，但仍需以后续市场验证为准。")
    return lines


def _render_stage(data: dict[str, Any]) -> list[str]:
    mode = str(data.get("report_mode") or "unknown")
    if mode == "hybrid":
        return ["- 新闻主线与重点文章同时触发，适合生成完整日报，但需保留来源置信度标记。"]
    if mode == "news_driven":
        return ["- 当前由新闻或行情反应主导，报告文章只作为补充。"]
    if mode == "report_driven":
        return ["- 当前由报告/重点文章驱动，尚需外部新闻或行情验证。"]
    return ["- 当前输入不足，阶段判断不可用。"]


def _render_key_levels(levels: dict[str, Any]) -> list[str]:
    mentioned = _list(levels.get("mentioned_levels"))
    if not mentioned:
        return ["- 暂无结构化关键位。"]
    return [f"- mentioned_levels: {', '.join(str(item) for item in mentioned)}"]


def _render_scenarios(scenarios: list[Any]) -> list[str]:
    if not scenarios:
        return ["- 路径A：等待新增事件或行情验证。", "- 路径B：若核心事件被多源确认，再升级完整日报。", "- 路径C：若输入失效，维持小快讯。"]
    lines: list[str] = []
    labels = ["路径A", "路径B", "路径C"]
    for index, scenario in enumerate(_dict(item) for item in scenarios[:3]):
        label = labels[index] if index < len(labels) else f"路径{index + 1}"
        lines.append(f"- {label}: {_text(scenario.get('text') or scenario.get('event_type'))}")
    while len(lines) < 3:
        lines.append(f"- {labels[len(lines)]}: 等待更多确认输入。")
    return lines


def _final_judgement(data: dict[str, Any]) -> str:
    mode = str(data.get("report_mode") or "unknown")
    quality_flags = ", ".join(str(item) for item in _list(data.get("quality_flags"))) or "none"
    if mode == "hybrid":
        return f"当前可以生成完整日报，但结论必须携带质量标记：{quality_flags}。"
    if mode == "news_driven":
        return f"当前可以生成新闻驱动日报，后续重点检查报告和关键位是否补强；质量标记：{quality_flags}。"
    if mode == "report_driven":
        return f"当前只适合报告驱动分析，需等待行情和多源新闻验证；质量标记：{quality_flags}。"
    return "当前不应生成完整日报。"


def _render_source_refs(refs: list[Any]) -> list[str]:
    lines: list[str] = []
    for ref in (_dict(item) for item in refs):
        if not ref:
            continue
        lines.append(f"- source: {_text(ref.get('source'))}")
        for key in ("source_ref", "url", "asset_type", "path"):
            if ref.get(key):
                lines.append(f"  - {key}: {_text(ref.get(key))}")
    return lines


def _bullets(items: list[Any]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- unavailable"]


def _snapshot_dict(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    data = _dict(value)
    nested = data.get("daily_brief_input_snapshot")
    return _dict(nested) if isinstance(nested, Mapping) else data


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _text(value: Any) -> str:
    text = str(value) if value is not None else "unavailable"
    return text.strip() or "unavailable"
