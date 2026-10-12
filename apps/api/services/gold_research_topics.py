"""Read complete topic reasoning from the same verified research; never analyse anew."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from apps.analysis.agents.research_input import DETAILED_REASONING_FIELDS
from apps.analysis.agents.research_synthesis import validate_report_sections
from apps.api.services.gold_research_horizons import _lead, _sections

IDENTITY_FIELDS = ("report_id", "run_id", "snapshot_id", "trade_date", "as_of")
TOPIC_GROUPS = {
    "changes": ("market_evolution", "continuity"),
    "macro": ("growth_inflation", "labor", "curve_policy", "real_rates", "treasury_turn", "dollar"),
    "funds": ("oil", "flows", "liquidity", "credit", "options"),
    "price": ("gold_response", "levels", "scenarios", "observation"),
    "risk": ("calendar", "state", "risks"),
}
TOPIC_LABELS = {
    "market_evolution": "相比前次，新增了什么", "continuity": "日报与周报的接续、改判",
    "growth_inflation": "增长、消费与通胀约束", "labor": "就业、工资与政策反应",
    "curve_policy": "Fed政策路径与长端成本", "real_rates": "实际利率与通胀补偿",
    "treasury_turn": "美债拐点、供给与拍卖承接", "dollar": "美元与黄金定价压力",
    "oil": "能源、成品油与地缘传导", "flows": "黄金需求：央行、ETF与CFTC",
    "liquidity": "美元流动性与融资压力", "credit": "信用与风险偏好",
    "options": "CME持仓、期权结构与到期", "gold_response": "黄金自身承接与宏观传导",
    "levels": "关键位角色与验证条件", "scenarios": "未来1—3日：主、上、下路径",
    "observation": "执行结构与20美元止损约束", "calendar": "事件日历与结果传导",
    "state": "当前阶段与升级、撤回条件", "risks": "反证、失效与关键风险",
}
_HEADINGS = {
    "market_evolution": r"新增|行情演化|行情变化", "continuity": r"接续|前序|相比",
    "growth_inflation": r"消费|增长|PCE|通胀约束", "labor": r"就业|工资|非农",
    "curve_policy": r"Fed|美联储|政策路径|长端.*成本", "real_rates": r"实际利率|通胀补偿|Breakeven",
    "treasury_turn": r"美债|长端|收益率|拍卖", "dollar": r"美元|DXY",
    "oil": r"能源|原油|成品油|地缘", "flows": r"黄金需求|资金|央行|ETF|CFTC|仓位",
    "liquidity": r"流动性|融资压力", "credit": r"信用|风险偏好",
    "options": r"CME|期权", "gold_response": r"黄金自身|黄金价格|承接|背离|传导.*黄金",
    "levels": r"关键位|价格地图", "scenarios": r"未来.*交易日|三条路径|情景",
    "observation": r"交易上|观察卡|执行|交易策略", "calendar": r"日历|今晚.*开关|事件.*传导",
    "state": r"最终判断|阶段|最终结论", "risks": r"风险|反证|局限",
}


def verified_report_topics(*, synthesis: Any, narrative: str, identity: dict[str, Any]) -> dict[str, Any] | None:
    """Called only after the registered report, task and snapshot have been verified."""
    if not isinstance(synthesis, dict) or synthesis.get("status") != "success" or synthesis.get("report_profile_version") != "gold_reader.v4":
        return None
    analysis = synthesis.get("analysis")
    if not isinstance(analysis, dict):
        return None
    reader = analysis.get("reader_narrative")
    if not isinstance(reader, str) or not reader.strip() or reader not in narrative:
        return None
    if any(not isinstance(identity.get(key), str) or not identity[key].strip() for key in IDENTITY_FIELDS):
        return None
    if synthesis.get("prompt_input_snapshot_id") != identity["snapshot_id"]:
        return None
    catalog = synthesis.get("evidence_catalog_ids")
    if not isinstance(catalog, list) or any(not isinstance(item, str) for item in catalog):
        return None
    try:
        modules = validate_report_sections(analysis.get("report_sections"), allowed_ids=set(catalog))
    except (ValueError, TypeError, KeyError):
        return None
    return {"schema_version": "gold_research_topics.v1", "status": "available", **identity,
            "modules": deepcopy(modules)}


def project_research_topics(research: dict[str, Any], source: Any) -> list[dict[str, Any]]:
    usable = research.get("status") in {"current", "historical"}
    source = source if isinstance(source, dict) else {}
    bound = (usable and source.get("schema_version") == "gold_research_topics.v1"
             and source.get("status") == "available"
             and all(research.get(key) and source.get(key) == research.get(key) for key in IDENTITY_FIELDS))
    modules = source.get("modules") if bound and isinstance(source.get("modules"), dict) else {}
    passages = _sections(research.get("narrative") or "") if usable else []
    results = []
    for group, keys in TOPIC_GROUPS.items():
        for key in keys:
            module = modules.get(key)
            valid = (isinstance(module, dict)
                     and all(isinstance(module.get(field), str) and module[field].strip() for field in DETAILED_REASONING_FIELDS)
                     and isinstance(module.get("pending"), list) and all(isinstance(p, str) for p in module["pending"]))
            # Older readers keep original prose, rather than fabricated six-field reasoning.
            excerpts = [] if valid else [row for row in passages if re.search(_HEADINGS[key], row["title"], re.IGNORECASE)]
            ready = bool(valid or excerpts)
            row = {**{field: research.get(field) for field in IDENTITY_FIELDS}, "key": key,
                   "label": TOPIC_LABELS[key], "group": group,
                   "status": research["status"] if ready else "unavailable",
                   "basis": "verified_report_topics" if valid else "report_excerpt" if excerpts else "unavailable",
                   **{field: module[field] if valid else "" for field in DETAILED_REASONING_FIELDS},
                   "pending": deepcopy(module["pending"]) if valid else [], "sections": excerpts,
                   "note": "同一报告的完整主题观点，不代表已确认的涨跌贡献或入场信号。" if valid
                           else "同一报告原文；未补造独立主题判断。" if excerpts
                           else "本报告未提供这一分析点，更新分析时需补齐证据与判断。"}
            if excerpts:
                row["judgment"] = _lead(excerpts[0]["content"])
            results.append(row)
    return results
