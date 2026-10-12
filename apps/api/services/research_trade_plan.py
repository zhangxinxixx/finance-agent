"""Pure reader projection of verified research; never an execution decision."""
from __future__ import annotations

import re
from typing import Any


_COLUMNS = {
    "name": {"路径", "情景", "场景", "路径名称", "Scenario", "Path"},
    "macro_conditions": {"宏观条件", "宏观确认", "宏观确认条件", "Macro Confirmation"},
    "price_conditions": {"价格条件", "价格与资金条件", "价格确认", "价格路径", "价格触发条件", "Price Path"},
    "invalidation": {"失效", "失效条件", "失效条件/风险", "Invalidation"},
}


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _detailed_paths(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    """Read the actual v4 renderer's vertical condition table without inventing fields."""
    names = ("路径 / 持仓", "条件项目", "模型条件（external_opinion）")
    clean_headers = [header.strip("*` ") for header in headers]
    if len(clean_headers) != 3 or set(clean_headers) != set(names):
        return []
    columns = [clean_headers.index(name) for name in names]
    fields = ("宏观确认", "资金确认", "价格", "观察区域", "触发", "失效条件", "观察窗口")
    grouped: dict[str, dict[str, str]] = {}
    rejected = set()
    for cells in rows:
        name, field, value = (cells[column] for column in columns)
        if name not in {"主路径", "上行路径", "下行路径"}:
            continue
        path = grouped.setdefault(name, {})
        if field not in fields or field in path or not value.strip():
            rejected.add(name)
        path[field] = value
    result = []
    for name, path in grouped.items():
        if name in rejected or set(path) != set(fields):
            continue
        result.append({"name": name,
                       "macro_conditions": "\n".join(field + "：" + path[field] for field in fields[:2]),
                       "price_conditions": "\n".join(field + "：" + path[field] for field in ("价格", "观察区域", "触发", "观察窗口")),
                       "invalidation": path["失效条件"]})
    return result


def _scenarios(narrative: str) -> list[dict[str, str]]:
    lines = narrative.splitlines()
    result = []
    in_fence = False
    for index, line in enumerate(lines[:-1]):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if in_fence or "|" not in line:
            continue
        headers = _cells(line)
        separator = _cells(lines[index + 1])
        if len(separator) != len(headers) or not all(re.fullmatch(r":?-{3,}:?", c) for c in separator):
            continue
        rows = []
        for row in lines[index + 2:]:
            if "|" not in row or not row.strip():
                break
            cells = _cells(row)
            if len(cells) != len(headers):
                break
            rows.append(cells)
        detailed = _detailed_paths(headers, rows)
        if detailed:
            result.extend(detailed)
            continue
        columns = {}
        for key, names in _COLUMNS.items():
            matches = [i for i, header in enumerate(headers) if header.strip("*` ") in names]
            if len(matches) == 1:
                columns[key] = matches[0]
        if len(columns) != len(_COLUMNS):
            continue
        for cells in rows:
            scenario = {key: cells[column] for key, column in columns.items()}
            # The existing renderer separates Trigger from Price Path. Keep
            # both original cells as conditions, without relabelling targets.
            if "Trigger" in headers:
                trigger = cells[headers.index("Trigger")]
                if trigger:
                    scenario["price_conditions"] = trigger + "\n" + scenario["price_conditions"]
            result.append(scenario)
    return result


def _summary(narrative: str) -> str:
    # Keep the complete first paragraph, including its inline Markdown.
    match = re.search(r"(?m)^#{1,6}\s+(?:\d+[.、．]\s*)?一句话结论\s*[:：]?\s*$", narrative)
    if not match:
        return ""
    paragraphs = re.split(r"\n\s*\n", narrative[match.end():].strip())
    paragraph = paragraphs[0] if paragraphs else ""
    if not paragraph or paragraph.startswith(("#", "|", "```", "~~~")):
        return ""
    return paragraph


def project_research_trade_plan(*, narrative: str, snapshot: dict[str, Any],
                                report_id: str, run_id: str, snapshot_id: str,
                                trade_date: str) -> dict[str, Any]:
    """Caller owns identity/quality gates; this helper only copies reader facts."""
    from apps.api.services.research_identity import build_research_identity
    execution = (snapshot.get("gold_workflow") or {}).get("execution") or {}
    frames = {str(row.get("timeframe", "")).lower(): row
              for row in execution.get("timeframe_features", []) if isinstance(row, dict)}
    attention = []
    for timeframe in ("4H", "1H", "15m"):
        row = frames.get(timeframe.lower()) or {}
        if row.get("status") != "available":
            reason = row.get("reason") or row.get("execution_reason")
            if reason == "missing_stale_or_gapped_bars":
                reason = "缺少新鲜、连续的完整 K 线，无法完成方向过滤。"
            attention.append(f"{timeframe} 数据缺口：" + (str(reason) if reason else "同快照未提供可用的完整结构。"))
    if execution.get("event_rule"):
        attention.append(execution["event_rule"])
    else:
        attention.append("不追事件后的第一根 15m K 线，等待扫单后的回踩与结构确认。")
    attention.extend([
        "4H/1H 用于过滤，15m 用于确认；当前路径尚未确认入场。",
        "合理的结构止损超过 20 美元/盎司就等待或跳过，不为进场而强行缩小止损。",
        "GC 期货价位不可当作 XAUUSD 现货价位。",
    ])
    return {
        "schema_version": "research_trade_plan.v1",
        "report_id": report_id, "run_id": run_id, "snapshot_id": snapshot_id,
        "trade_date": trade_date, "as_of": snapshot.get("snapshot_time"),
        "research_identity": build_research_identity(report_id=report_id, run_id=run_id,
            snapshot_id=snapshot_id, trade_date=trade_date, snapshot=snapshot),
        "status": "waiting", "execution_ready": False, "is_trade_instruction": False,
        "current_action": "等待确认，暂不开新单", "summary": _summary(narrative),
        "reason": execution.get("reason"), "scenarios": _scenarios(narrative),
        "position_guidance": {key: execution.get(key) for key in ("flat", "long", "short")},
        "entry": None, "stop_loss": None, "targets": [], "attention_points": attention,
    }
