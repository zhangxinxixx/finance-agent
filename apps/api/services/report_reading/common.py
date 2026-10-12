"""Shared, side-effect-free helpers for report read models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPORT_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _mtime_to_iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _generated_at_from_paths(*paths: Path | None) -> str | None:
    latest_mtime: float | None = None
    for path in paths:
        if path is None or not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest_mtime = mtime if latest_mtime is None else max(latest_mtime, mtime)
    if latest_mtime is None:
        return None
    return _mtime_to_iso_utc(latest_mtime)


def _generated_at_from_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return None


def _parse_report_timestamp(value: Any) -> datetime | None:
    """Return a comparable UTC timestamp for an indexed report value."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _report_index_sort_key(item: dict[str, Any]) -> tuple[str, datetime, str, str, str]:
    """Order same-day versions by generated/registered time before ID."""

    return (
        str(item.get("trade_date") or ""),
        _parse_report_timestamp(item.get("generated_at")) or _REPORT_EPOCH,
        str(item.get("run_id") or ""),
        str(item.get("report_id") or ""),
        str(item.get("type") or ""),
    )


def _report_index_family(report_type: str) -> str:
    return {
        "final_report": "final_report_markdown",
        "macro_report": "macro_report",
        "macro_event_followup": "macro_event_followup_supplement",
        "weekly_context_revision": "weekly_context_revision_supplement",
        "strategy_card": "strategy_card",
        "observation_report": "observation_report_markdown",
        "observation_strategy_card": "observation_strategy_card",
        "options_report": "options_report_markdown",
        "options_visual_report": "cme_options_visual",
    }.get(report_type, report_type)


def _report_index_title(report_type: str, trade_date: str) -> str:
    return {
        "final_report": f"XAUUSD 综合报告（{trade_date}）",
        "macro_report": f"XAUUSD 宏观分析报告（{trade_date}）",
        "macro_event_followup": f"XAUUSD 宏观事件跟进补充（{trade_date}）",
        "weekly_context_revision": f"XAUUSD 周报最新上下文修正（{trade_date}）",
        "strategy_card": f"XAUUSD 策略卡片（{trade_date}）",
        "observation_report": f"XAUUSD 研究观察报告（{trade_date}）",
        "observation_strategy_card": f"XAUUSD 观察策略卡（{trade_date}）",
        "options_report": f"黄金期权结构报告（{trade_date}）",
        "options_visual_report": f"黄金期权可视报告（{trade_date}）",
    }.get(report_type, f"{report_type}（{trade_date}）")
