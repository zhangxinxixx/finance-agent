from __future__ import annotations

from typing import Any, Mapping

from apps.renderer.contracts import MacroEventFollowupStructuredPayload


def build_macro_event_followup_structured_payload(snapshot: Mapping[str, Any]) -> MacroEventFollowupStructuredPayload:
    trade_date = str(snapshot.get("trade_date") or "")
    anchor_trade_date = str(snapshot.get("anchor_trade_date") or "")
    anchor_report_refs = [dict(item) for item in snapshot.get("anchor_report_refs") or [] if isinstance(item, dict)]
    inputs = snapshot.get("inputs") if isinstance(snapshot.get("inputs"), Mapping) else {}
    availability = snapshot.get("availability") if isinstance(snapshot.get("availability"), Mapping) else {}
    quality_flags = [str(item) for item in snapshot.get("quality_flags") or [] if item]
    warnings = [str(item) for item in snapshot.get("warnings") or [] if item]

    daily_market_brief = _payload(inputs.get("daily_market_brief"))
    followups = _payload(inputs.get("daily_analysis_followups"))
    article_briefs = _payload(inputs.get("jin10_article_briefs"))

    return MacroEventFollowupStructuredPayload.model_validate(
        {
            "report_type": "macro_event_followup",
            "trade_date": trade_date,
            "anchor_trade_date": anchor_trade_date,
            "anchor_report_refs": anchor_report_refs,
            "new_macro_events": _new_macro_events(
                daily_market_brief=daily_market_brief,
                followups=followups,
                article_briefs=article_briefs,
            ),
            "impact_assessment": {
                "status": str(snapshot.get("status") or "unknown"),
                "supports_anchor_view": not quality_flags,
                "summary": _impact_summary(
                    daily_market_brief=daily_market_brief,
                    followups=followups,
                    article_briefs=article_briefs,
                    warnings=warnings,
                ),
                "availability": {str(key): str(value) for key, value in availability.items()},
            },
            "watch_items": _watch_items(followups=followups, article_briefs=article_briefs),
            "revision_risk": {
                "level": "needs_review" if quality_flags else "monitor",
                "reason": warnings[0] if warnings else "暂未发现会立即推翻锚点结论的新矛盾。",
                "quality_flags": quality_flags,
            },
            "source_refs": _source_refs(
                anchor_report_refs=anchor_report_refs,
                daily_market_brief=daily_market_brief,
                followups=followups,
                article_briefs=article_briefs,
            ),
        }
    )


def render_macro_event_followup_source_markdown(snapshot: Mapping[str, Any]) -> str:
    trade_date = str(snapshot.get("trade_date") or "unknown")
    anchor_trade_date = str(snapshot.get("anchor_trade_date") or "unknown")
    availability = snapshot.get("availability") if isinstance(snapshot.get("availability"), Mapping) else {}
    anchor_report_refs = [dict(item) for item in snapshot.get("anchor_report_refs") or [] if isinstance(item, dict)]
    inputs = snapshot.get("inputs") if isinstance(snapshot.get("inputs"), Mapping) else {}

    lines = [
        "# Macro Event Follow-up Sources",
        "",
        f"- trade_date: {trade_date}",
        f"- anchor_trade_date: {anchor_trade_date}",
        "",
        "## Anchor Reports",
        "",
    ]
    if anchor_report_refs:
        for item in anchor_report_refs:
            lines.append(
                f"- {item.get('artifact_type')}: {item.get('path')} (run_id={item.get('run_id')}, available={item.get('available')})"
            )
    else:
        lines.append("- unavailable")
    lines.extend(["", "## Same-Day Inputs", ""])
    for key in ("daily_market_brief", "daily_analysis_followups", "jin10_article_briefs", "event_flow_overview"):
        input_item = inputs.get(key) if isinstance(inputs, Mapping) else None
        payload = _payload(input_item)
        lines.append(f"- {key}: {availability.get(key, 'unavailable')}")
        if key == "daily_analysis_followups" and payload.get("followups"):
            for followup in payload.get("followups")[:5]:
                if isinstance(followup, Mapping):
                    lines.append(f"  - {followup.get('title') or followup.get('headline') or followup.get('event_type')}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_macro_event_followup_analysis_markdown(payload: Mapping[str, Any]) -> str:
    structured = MacroEventFollowupStructuredPayload.model_validate(dict(payload))
    impact = structured.impact_assessment if isinstance(structured.impact_assessment, Mapping) else {}
    revision_risk = structured.revision_risk if isinstance(structured.revision_risk, Mapping) else {}
    stance = str(impact.get("stance") or "monitor")
    summary = str(impact.get("summary") or "暂无可用的影响评估摘要。")
    risk_level = str(revision_risk.get("level") or "unknown")
    risk_reason = str(revision_risk.get("reason") or "unknown")
    conclusion = _conclusion_line(stance, summary, structured.anchor_trade_date)
    change_line = _change_line(structured.new_macro_events, structured.anchor_trade_date)
    watch_items = _dedupe_watch_items(structured.watch_items)

    lines = [
        "# XAUUSD 宏观事件跟进补充",
        "",
        f"- trade_date: {structured.trade_date}",
        f"- anchor_trade_date: {structured.anchor_trade_date}",
        "",
        "## 开头结论",
        "",
        conclusion,
        "",
        "## 相比锚点的变化",
        "",
        change_line,
        "",
        "## 新增宏观事件",
        "",
    ]
    if structured.new_macro_events:
        for item in structured.new_macro_events:
            title = str(item.get("title") or item.get("event_type") or "未命名事件")
            lines.append(f"- {title}")
    else:
        lines.append("- 无可用新增事件。")
    lines.extend(["", "## 影响评估", ""])
    lines.append(summary)
    lines.extend(["", "## 开盘前观察项", ""])
    if watch_items:
        for item in watch_items:
            label = str(item.get("label") or item.get("title") or item.get("headline") or "观察项")
            lines.append(f"- {label}")
    else:
        lines.append("- 无新增观察项。")
    lines.extend(["", "## 改判风险", ""])
    lines.append(f"- 风险级别：{risk_level}")
    lines.append(f"- 风险原因：{risk_reason}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = value.get("payload")
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _new_macro_events(
    *,
    daily_market_brief: Mapping[str, Any],
    followups: Mapping[str, Any],
    article_briefs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in daily_market_brief.get("confirmed_events") or []:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("what_happened") or item.get("event_type") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(
            {
                "event_type": item.get("event_type"),
                "title": title,
                "source": "daily_market_brief",
                "source_refs": [dict(ref) for ref in item.get("source_refs") or [] if isinstance(ref, Mapping)],
            }
        )

    for item in followups.get("followups") or []:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or item.get("headline") or item.get("event_type") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(
            {
                "event_type": item.get("event_type"),
                "title": title,
                "source": "daily_analysis_followups",
                "source_refs": [dict(ref) for ref in item.get("source_refs") or [] if isinstance(ref, Mapping)],
            }
        )

    for item in article_briefs.get("briefs") or []:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("analysis_summary") or item.get("headline") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        result.append(
            {
                "event_type": item.get("article_class"),
                "title": title,
                "source": "jin10_article_briefs",
                "source_refs": [dict(ref) for ref in item.get("source_refs") or [] if isinstance(ref, Mapping)],
            }
        )

    return result


def _watch_items(*, followups: Mapping[str, Any], article_briefs: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in followups.get("followups") or []:
        if isinstance(item, Mapping):
            title = str(item.get("title") or item.get("headline") or item.get("event_type") or "").strip()
            if title:
                result.append({"label": title, "source": "daily_analysis_followups"})
    for item in article_briefs.get("briefs") or []:
        if isinstance(item, Mapping):
            headline = str(item.get("headline") or "").strip()
            if headline:
                result.append({"label": headline, "source": "jin10_article_briefs"})
    return result[:8]


def _dedupe_watch_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        label = str(item.get("label") or item.get("title") or item.get("headline") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(item)
    return result


def _conclusion_line(stance: str, summary: str, anchor_trade_date: str) -> str:
    stance_text = {
        "reinforce": "整体仍在强化锚点判断",
        "monitor": "当前更适合继续观察",
        "revise": "已有改写锚点判断的迹象",
    }.get(stance, "当前信号需要谨慎解读")
    return f"本次补充分析显示：{stance_text}，锚定 {anchor_trade_date} 的正式结论不变。{summary}"


def _change_line(new_macro_events: list[dict[str, Any]], anchor_trade_date: str) -> str:
    if not new_macro_events:
        return f"{anchor_trade_date} 之后没有形成新的可确认宏观主线，因此主要看法仍以原正式报告为准。"
    first_event = str(new_macro_events[0].get("title") or "新增事件").strip()
    if len(new_macro_events) == 1:
        return f"新增的核心变化是 {first_event}，它会影响接下来对开盘节奏和风险偏好的判断。"
    return f"新增变化不止一条，最先需要关注 {first_event}，其余事件已在下文继续展开。"


def _impact_summary(
    *,
    daily_market_brief: Mapping[str, Any],
    followups: Mapping[str, Any],
    article_briefs: Mapping[str, Any],
    warnings: list[str],
) -> str:
    event_text = ""
    confirmed_events = daily_market_brief.get("confirmed_events") or []
    if confirmed_events and isinstance(confirmed_events[0], Mapping):
        event_text = str(confirmed_events[0].get("what_happened") or confirmed_events[0].get("event_type") or "").strip()
    followup_text = ""
    followup_items = followups.get("followups") or []
    if followup_items and isinstance(followup_items[0], Mapping):
        followup_text = str(followup_items[0].get("title") or followup_items[0].get("event_type") or "").strip()
    brief_text = ""
    brief_items = article_briefs.get("briefs") or []
    if brief_items and isinstance(brief_items[0], Mapping):
        brief_text = str(brief_items[0].get("analysis_summary") or brief_items[0].get("headline") or "").strip()

    parts = [text for text in (event_text, followup_text, brief_text) if text]
    if parts:
        return " | ".join(parts[:3])
    if warnings:
        return warnings[0]
    return "当天可用的宏观跟进输入不足，因此只能保守维持锚点结论。"


def _source_refs(
    *,
    anchor_report_refs: list[dict[str, Any]],
    daily_market_brief: Mapping[str, Any],
    followups: Mapping[str, Any],
    article_briefs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in anchor_report_refs:
        source_ref = str(item.get("path") or "")
        if source_ref:
            _append_source_ref(
                result,
                seen,
                {"source": "macro_anchor_report", "source_type": "report", "ref": source_ref},
            )

    for ref in daily_market_brief.get("source_refs") or []:
        if isinstance(ref, Mapping):
            _append_source_ref(result, seen, dict(ref))

    for container in [followups.get("followups") or [], article_briefs.get("briefs") or []]:
        for item in container:
            if not isinstance(item, Mapping):
                continue
            for ref in item.get("source_refs") or []:
                if isinstance(ref, Mapping):
                    _append_source_ref(result, seen, dict(ref))

    return result


def _append_source_ref(result: list[dict[str, Any]], seen: set[tuple[str, str]], ref: dict[str, Any]) -> None:
    key = (str(ref.get("source") or ref.get("source_type") or ""), str(ref.get("source_ref") or ref.get("ref") or ""))
    if key in seen:
        return
    seen.add(key)
    result.append(ref)
