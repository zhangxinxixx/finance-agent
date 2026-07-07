from __future__ import annotations

from typing import Any

from apps.event_sla.schemas import EventSnapshot


def build_trading_strategy(*, event: EventSnapshot, evidence_level: str) -> dict[str, Any]:
    if evidence_level != "full":
        return {
            "bias": "event_risk",
            "confidence": "low",
            "strategy_mode": "observe",
            "evidence_level": evidence_level,
            "key_levels": _key_levels(event),
            "entry_conditions": [],
            "invalidation_conditions": [],
            "risk_notes": ["actionable strategy is blocked until full content and quality gates are available"],
            "positioning_suggestion": "仅做情景参考，不构成投资建议",
        }
    if event.source_key == "cme_gold_options_bulletin":
        return {
            "bias": "range",
            "confidence": "medium",
            "strategy_mode": "wait_breakout",
            "evidence_level": "full",
            "key_levels": _key_levels(event),
            "entry_conditions": ["等待现货价格有效突破主要期权墙并观察 OI 是否同步迁移"],
            "invalidation_conditions": ["OI 墙迁移或 parsed CME 结构与当前价格区间不再匹配"],
            "risk_notes": ["已排除 OMG Micro Gold 与 OG1/OG2/OG3/OG4/OG5 weekly options；仅作为结构观察"],
            "positioning_suggestion": "仅做情景参考，不构成投资建议",
        }
    return {
        "bias": "range",
        "confidence": "medium",
        "strategy_mode": "wait_breakout",
        "evidence_level": "full",
        "key_levels": _key_levels(event),
        "entry_conditions": ["等待关键位突破/收复并由美元、利率或资金流证据确认"],
        "invalidation_conditions": ["跌破报告给出的下沿或质量闸门转为 blocked"],
        "risk_notes": ["策略为事件分析输出，不构成投资建议；需结合实时行情确认"],
        "positioning_suggestion": "仅做情景参考，不构成投资建议",
    }


def render_strategy_markdown(strategy: dict[str, Any]) -> str:
    lines = [
        "# Trading Strategy",
        "",
        f"- Bias: {strategy.get('bias')}",
        f"- Confidence: {strategy.get('confidence')}",
        f"- Strategy mode: {strategy.get('strategy_mode')}",
        f"- Evidence level: {strategy.get('evidence_level')}",
        "",
        "## Key Levels",
    ]
    for item in strategy.get("key_levels", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('level')}: {item.get('type')} - {item.get('meaning')}")
    lines.extend(["", "## Entry Conditions"])
    lines.extend(f"- {item}" for item in strategy.get("entry_conditions", []))
    lines.extend(["", "## Invalidation Conditions"])
    lines.extend(f"- {item}" for item in strategy.get("invalidation_conditions", []))
    lines.extend(["", "## Risk Notes"])
    lines.extend(f"- {item}" for item in strategy.get("risk_notes", []))
    lines.append("")
    lines.append(str(strategy.get("positioning_suggestion") or "仅做情景参考，不构成投资建议"))
    return "\n".join(lines).rstrip() + "\n"


def _key_levels(event: EventSnapshot) -> list[dict[str, Any]]:
    if event.source_key == "cme_gold_options_bulletin":
        levels = event.payload.get("key_levels") if isinstance(event.payload.get("key_levels"), list) else []
        return [{"level": level, "type": "option_wall", "meaning": "CME OG options open-interest wall"} for level in levels]
    raw_levels = event.payload.get("key_levels") if isinstance(event.payload.get("key_levels"), list) else []
    normalized = []
    for item in raw_levels:
        if isinstance(item, dict):
            normalized.append(
                {
                    "level": item.get("level") or item.get("value"),
                    "type": item.get("type") or item.get("label") or "trigger",
                    "meaning": item.get("meaning") or "报告关键位",
                }
            )
    return normalized
