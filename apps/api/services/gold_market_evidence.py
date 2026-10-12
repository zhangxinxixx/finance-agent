"""Readable mechanisms and existing CME levels; these are not trade decisions."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def macro_effect(row: dict, *, key: str, status: str, mechanism: str, unit: str) -> dict:
    """Separate the holding-cost level from its short-term change.

    Positive yield is a cost constraint, not a threshold proving that gold
    must fall. Monthly comparisons remain trend references, not that level.
    """
    change = number(row.get("monthly_change"))
    value = number(row.get("value"))
    ready = status in {"fresh", "recent"}
    if ready and value is not None and key in {"US02Y", "US10Y", "US30Y", "REAL10Y"}:
        impact = "pressure" if value > 0 else "supportive" if value < 0 else "neutral"
        cost = "持金机会成本仍形成约束" if value > 0 else "负收益率缓解持金机会成本" if value < 0 else "收益水平暂未形成额外机会成本"
        monthly = f"近月{'上升' if change > 0 else '下降' if change < 0 else '持平'}{abs(change * 100):g}bp。" if change is not None else ""
        return {"impact": impact, "summary": f"收益水平{value:g}%；{cost}。{monthly}",
                "change": round(change * 100, 6) if change is not None else None,
                "unit": "bp", "window": "1mo" if change is not None else None, "basis": "holding_cost_level"}
    if change is None or not ready:
        return {"impact": "unconfirmed", "summary": "长期方向需补齐可比数据。", "change": None,
                "unit": unit, "window": None, "basis": "unavailable"}
    change_unit = "bp" if unit in {"%", "percent", "percentage_points"} else unit
    change = round(change * 100, 6) if change_unit == "bp" else change
    movement = "上升" if change > 0 else "下降" if change < 0 else "持平"
    display_unit = {"bp": "bp", "index": "点", "USD/bbl": "美元/桶", "B": "十亿美元"}.get(change_unit, change_unit)
    if change == 0:
        impact, meaning = "neutral", "长期影响还取决于当前水平与其他驱动。"
    elif mechanism in {"inverse", "nominal"}:
        impact = "pressure" if change > 0 else "supportive"
        meaning = ("美元或资金成本仍对黄金形成压力。" if change > 0
                   else "美元或资金成本压力减轻，持续转向仍需确认。")
    else:
        impact, meaning = "mixed", "通胀、需求与资金传导需共同判断。"
    return {"impact": impact, "summary": f"近月{movement}{abs(change):g}{display_unit}；{meaning}",
            "change": change, "unit": change_unit, "window": "1mo", "basis": "monthly_comparison"}


def short_effect(*, status: str, mechanism: str, change: float | None, window: str | None) -> str:
    if status not in {"fresh", "recent"}:
        return "数据需更新，当前短线影响未确认。"
    if change is None:
        return "缺少可比变动，短线影响未确认。"
    period = {"1d": "日度", "1w": "周度", "intraday": "日内"}.get(window, "本窗口")
    if change == 0:
        return f"{period}持平，暂未提供新的方向驱动。"
    direction = "上升" if change > 0 else "下降"
    if mechanism == "nominal":
        return f"收益率{period}{direction}，黄金{'承压' if change > 0 else '短线压力缓解'}。"
    if mechanism == "inverse":
        return f"{period}{direction}，黄金{'承压' if change > 0 else '短线压力缓解'}。"
    if mechanism == "flows":
        return f"{period}资金参与{'增加' if change > 0 else '减少'}，{'支持' if change > 0 else '削弱'}配置承接；不证明日内买卖盘。"
    if mechanism == "oil":
        return f"原油{period}{direction}，成本与避险作用需分开验证。"
    return f"{period}{direction}，多条传导并存，尚不能确定黄金方向。"


def environment_watch(factors: list[dict]) -> dict:
    """Publish explicit comparison baselines, not invented reversal thresholds."""
    rows = []
    for key in ("US10Y", "US30Y", "REAL10Y", "DXY"):
        fact = next((row for row in factors if row["key"] == key), {})
        if fact.get("status") not in {"fresh", "recent"} or number(fact.get("value")) is None:
            continue
        value, unit = fact["value"], "%" if fact["unit"] == "%" else "点"
        boundary = f"{value:g}{unit}"
        rows.append({"key": key, "label": fact["label"], "value": value, "unit": fact["unit"],
                     "supportive_condition": f"低于{boundary}并持续回落",
                     "pressure_condition": f"高于{boundary}并持续上行",
                     "observed_at": fact["observed_at"], "source_refs": deepcopy(fact["source_refs"])})
    return {"status": "available" if len(rows) == 4 else "partial" if rows else "unavailable",
            "basis": "latest_observation_comparison", "conditions": rows,
            "note": "以上数值为下一轮同口径比较基准，不是已确认的趋势反转或入场阈值。需连续变化、黄金价格收复与美元/实际利率共同验证。"}


_CME_ROLES = {
    "primary_support": ("主要支撑墙", "报告参考价下方的Put结构集中区，需看GC实际承接。"),
    "primary_resistance": ("主要阻力墙", "报告参考价上方的Call结构集中区，需看GC能否持续突破。"),
    "secondary_support": ("次级支撑墙", "下方期权结构观察区，跌破后需重验角色。"),
    "secondary_resistance": ("次级阻力墙", "上方期权结构观察区，突破后需重验角色。"),
    "magnet_pin": ("磁吸／钉住观察", "持仓集中不保证价格被吸引，需看接近该位后的成交与波动。"),
    "volatility_hub": ("波动枢纽", "双侧模型暴露集中，关注该区突破与回收能力。"),
    "gamma_flip": ("Gamma切换区", "模型Gamma符号切换区域，不是黄金现货买卖信号。"),
    "tail_protection": ("尾部保护观察", "Put结构集中不等于机构已确认看空。"),
}


def cme_structure(value: Any, *, now: datetime) -> dict:
    raw = value if isinstance(value, dict) else {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    quality = raw.get("data_quality") if isinstance(raw.get("data_quality"), dict) else {}
    context = raw.get("price_context") if isinstance(raw.get("price_context"), dict) else {}
    refs = [deepcopy(ref) for ref in raw.get("source_refs", []) if isinstance(ref, dict)] if isinstance(raw.get("source_refs"), list) else []
    result = {"status": "unavailable", "coordinate": "GC futures", "product": "OG",
              "trade_date": meta.get("current_trade_date"), "version_type": quality.get("cme_status"),
              "reference_price": number(context.get("report_p0")), "levels": [], "source_refs": refs,
              "basis_status": "unvalidated", "note": "CME为GC期货结构参考，不能直接换成XAUUSD现货支撑或入场价。"}
    try:
        day = date.fromisoformat(str(meta.get("current_trade_date")))
    except ValueError:
        return result
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    if (raw.get("status") not in {"available", "partial"} or meta.get("product") != "OG"
            or context.get("structure_coordinate_space") != "GC futures" or day > today
            or quality.get("cme_status") not in {"PRELIM", "PRELIMINARY", "FINAL"} or not refs):
        return result
    for row in raw.get("key_levels", []) if isinstance(raw.get("key_levels"), list) else []:
        if not isinstance(row, dict) or row.get("coordinate_space") != "GC futures" or row.get("role") not in _CME_ROLES:
            continue
        strike = number(row.get("strike"))
        band = row.get("band") if isinstance(row.get("band"), dict) else {}
        lower, upper = number(band.get("lower")), number(band.get("upper"))
        valid_band = lower is not None and upper is not None and 0 < lower <= upper
        if not (strike is not None and strike > 0 or valid_band):
            continue
        label, meaning = _CME_ROLES[row["role"]]
        result["levels"].append({"price": strike if strike is not None and strike > 0 else None,
                                 "lower": lower if valid_band else None, "upper": upper if valid_band else None,
                                 "role": row["role"], "label": label, "meaning": meaning,
                                 "expiry": row.get("expiry_scope"), "coordinate": "GC futures",
                                 "invalidation": deepcopy(row.get("invalidation") or [])})
    earliest = today - timedelta(days=1)
    while earliest.weekday() >= 5:
        earliest -= timedelta(days=1)
    if result["levels"]:
        result["status"] = "reference" if day >= earliest else "historical"
    return result
