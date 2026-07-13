from __future__ import annotations

import re

from apps.documents.schemas import DailyReportAnalysisSnapshot, ParsedDocument, ReportFact


def build_daily_report_analysis_snapshot(parsed: ParsedDocument, facts: list[ReportFact]) -> DailyReportAnalysisSnapshot:
    market_prices = _market_prices(facts)
    logic_chains = _logic_chains(facts)
    watch_variables = _watch_variables(facts)
    key_levels = _key_levels(facts)
    scenario_matrix = _scenario_matrix(facts)
    risks = _risks(facts)
    core_conclusion = _core_conclusion(parsed, facts)
    return DailyReportAnalysisSnapshot(
        document_id=parsed.document_id,
        trade_date=parsed.trade_date,
        article_id=parsed.article_id,
        title=parsed.title,
        core_conclusion=core_conclusion,
        market_prices=market_prices,
        logic_chains=logic_chains,
        watch_variables=watch_variables,
        key_levels=key_levels,
        scenario_matrix=scenario_matrix,
        risks=risks,
        facts=facts,
        source_refs=parsed.source_refs,
    )


def _market_prices(facts: list[ReportFact]) -> list[dict[str, object]]:
    rows = []
    for fact in facts:
        if fact.fact_type != "price":
            continue
        rows.append(
            {
                "label": fact.label,
                "value": fact.value,
                "instrument": fact.metadata.get("instrument"),
                "field": fact.metadata.get("field"),
                "source_block_id": fact.source_block_id,
            }
        )
    return rows


def _logic_chains(facts: list[ReportFact]) -> list[dict[str, object]]:
    rows = []
    for fact in facts:
        if fact.fact_type not in {"macro_driver", "author_view"}:
            continue
        rows.append(
            {
                "label": fact.label,
                "summary": str(fact.value),
                "source_block_id": fact.source_block_id,
                "source_page": fact.source_page,
            }
        )
    return rows or [{"label": "证据不足", "summary": "未从正文中提取到可用逻辑链。", "source_block_id": "unavailable"}]


def _watch_variables(facts: list[ReportFact]) -> list[dict[str, object]]:
    rows = []
    seen: set[str] = set()
    for fact in facts:
        if fact.fact_type != "macro_driver":
            continue
        if fact.label in seen:
            continue
        seen.add(fact.label)
        rows.append({"label": fact.label, "status": "watch", "source_block_id": fact.source_block_id})
    return rows or [{"label": "证据不足", "status": "unavailable", "source_block_id": "unavailable"}]


def _key_levels(facts: list[ReportFact]) -> list[dict[str, object]]:
    levels = []
    for fact in facts:
        if fact.fact_type != "price":
            continue
        if fact.metadata.get("field") in {"gold_high", "gold_close", "silver_close", "gold_target_range"}:
            levels.append({"label": fact.label, "value": fact.value, "source_block_id": fact.source_block_id})
    return levels or [{"label": "关键位未提及", "value": None, "source_block_id": "unavailable"}]


def _scenario_matrix(facts: list[ReportFact]) -> list[dict[str, object]]:
    view_texts = [str(fact.value) for fact in facts if fact.fact_type == "author_view"]
    macro_texts = [str(fact.value) for fact in facts if fact.fact_type == "macro_driver"]
    bearish = any(any(token in text for token in ("打压", "施压", "承压", "回落", "压制")) for text in view_texts)
    bullish = any(any(token in text for token in ("配置支撑", "配置机会", "反弹", "修复", "支撑")) for text in view_texts)
    rows = [
        {
            "scenario": "偏空",
            "summary": _scenario_summary("偏空", view_texts, macro_texts) if bearish else "证据有限，暂未形成稳定偏空路径。",
            "confidence": "medium" if bearish else "low",
        },
        {
            "scenario": "中性",
            "summary": _scenario_summary("中性", view_texts, macro_texts),
            "confidence": "medium" if any(f.fact_type == "macro_driver" for f in facts) else "low",
        },
        {
            "scenario": "偏多",
            "summary": _scenario_summary("偏多", view_texts, macro_texts) if bullish else "证据有限，暂未形成稳定偏多路径。",
            "confidence": "medium" if bullish else "low",
        },
    ]
    return rows


def _risks(facts: list[ReportFact]) -> list[dict[str, object]]:
    rows = [
        {"label": fact.label, "summary": str(fact.value), "source_block_id": fact.source_block_id}
        for fact in facts
        if fact.fact_type == "risk"
    ]
    if not rows:
        rows.append({"label": "证据不足", "summary": "未发现显式风险提示段落。", "source_block_id": "unavailable"})
    return rows


def _core_conclusion(parsed: ParsedDocument, facts: list[ReportFact]) -> str:
    if str(parsed.category_code or "") == "536" or "周报" in str(parsed.category or ""):
        return _weekly_core_conclusion(parsed.title, facts)
    macro = any(f.fact_type == "macro_driver" for f in facts)
    views = _summarize_fact_values(facts, "author_view", limit=3, max_chars=360)
    if views:
        return views
    if macro:
        macro_summary = _summarize_fact_values(facts, "macro_driver", limit=3, max_chars=300)
        return macro_summary if macro_summary else parsed.title
    return "解析已完成，但正文与图表证据仍不足以形成稳定结论。"


def _weekly_core_conclusion(title: str, facts: list[ReportFact]) -> str:
    theme = re.sub(r"\s*-\s*金十数据VIP\s*$", "", str(title or "")).strip()
    range_facts = _weekly_target_range_facts(facts)
    weekly_range = _weekly_range_value(
        range_facts,
        ("未来数周", "短期", "区间震荡", "横盘", "波动", "盘整"),
        fallback_index=0,
    )
    long_term_target = _weekly_range_value(
        range_facts,
        ("周期高点", "中长期", "2027", "目标兑现", "上行目标"),
        fallback_index=-1,
    )
    rate_evidence = _weekly_evidence(facts, ("收益率", "利率", "CPI", "FOMC", "美联储"))
    positioning_evidence = _weekly_positioning_evidence(facts)
    parts = [
        "报告分类：黄金投资者周报",
        f"本期主题：{theme or '未提取'}",
        f"周度判断：{weekly_range}",
        f"利率/催化：{rate_evidence or '未提取'}",
        f"持仓验证：{positioning_evidence or '未提取'}",
        f"中长期目标：{long_term_target}",
    ]
    conclusion = "；".join(parts)
    return conclusion[:420].rstrip("；,，。 ")


def _weekly_target_range_facts(facts: list[ReportFact]) -> list[ReportFact]:
    ranges: list[ReportFact] = []
    seen: set[str] = set()
    for fact in facts:
        if fact.fact_type != "price" or fact.metadata.get("field") != "gold_target_range":
            continue
        value = _compact_text(str(fact.value))
        if value and value not in seen and (fact.label == "黄金目标区间" or "黄金" in fact.evidence_text):
            seen.add(value)
            ranges.append(fact)
    return ranges


def _weekly_range_value(
    facts: list[ReportFact],
    tokens: tuple[str, ...],
    *,
    fallback_index: int,
) -> str:
    if not facts:
        return "未提取"
    ranked = sorted(
        facts,
        key=lambda fact: (
            sum(token in str(fact.evidence_text or "") for token in tokens),
            len(str(fact.evidence_text or "")),
        ),
        reverse=True,
    )
    if any(token in str(ranked[0].evidence_text or "") for token in tokens):
        return _compact_text(str(ranked[0].value))
    return _compact_text(str(facts[fallback_index].value))


def _weekly_evidence(facts: list[ReportFact], tokens: tuple[str, ...]) -> str:
    candidates: list[tuple[int, str]] = []
    for fact in facts:
        if fact.fact_type not in {"macro_driver", "author_view"}:
            continue
        evidence = _compact_text(str(fact.evidence_text or fact.value))
        match_count = sum(token in evidence for token in tokens)
        if match_count:
            candidates.append((match_count, evidence))
    if not candidates:
        return ""
    _, evidence = max(candidates, key=lambda item: (item[0], len(item[1])))
    return _truncate_weekly_evidence(evidence)


def _weekly_positioning_evidence(facts: list[ReportFact]) -> str:
    candidates: list[tuple[int, str]] = []
    weights = (
        ("未平仓合约", 8),
        ("增加", 5),
        ("增持", 4),
        ("COT", 2),
        ("交易商持仓报告", 2),
    )
    for fact in facts:
        if fact.fact_type not in {"macro_driver", "author_view"}:
            continue
        evidence = _compact_text(str(fact.evidence_text or fact.value))
        score = sum(weight for token, weight in weights if token in evidence)
        if score:
            score += 3 if re.search(r"\d+(?:\.\d+)?(?:万手|%|手)", evidence) else 0
            candidates.append((score, evidence))
    if not candidates:
        return ""
    _, evidence = max(candidates, key=lambda item: (item[0], len(item[1])))
    return _truncate_weekly_evidence(evidence)


def _truncate_weekly_evidence(evidence: str, *, max_chars: int = 88) -> str:
    value = re.sub(r"^(?:#{1,6}|[-*])\s*", "", _compact_text(evidence)).strip()
    if len(value) <= max_chars:
        return value.rstrip("；,，。 ")
    prefix = value[:max_chars]
    sentence_end = max(prefix.rfind("。"), prefix.rfind("；"))
    if sentence_end >= max_chars // 2:
        prefix = prefix[: sentence_end + 1]
    return prefix.rstrip("；,，。 ")


def fact_type_matches(fact: ReportFact, expected: str) -> bool:
    return fact.fact_type == expected


def _summarize_fact_values(facts: list[ReportFact], fact_type: str, *, limit: int, max_chars: int) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        if not fact_type_matches(fact, fact_type):
            continue
        value = _compact_text(str(fact.value))
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
        if len(values) >= limit:
            break
    summary = "；".join(values)
    return summary[:max_chars].rstrip("；,，。 ") if len(summary) > max_chars else summary


def _compact_text(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _scenario_summary(path: str, view_texts: list[str], macro_texts: list[str]) -> str:
    prioritized_views = _prioritize_views_for_path(path, view_texts)
    context = _dedupe_texts([*prioritized_views[:2], *macro_texts[:2], *view_texts[:2]])
    joined = "；".join(context).strip("；")
    if joined:
        prefix = {
            "偏空": "当前偏空路径更多来自：",
            "中性": "当前中性/拉锯路径更多来自：",
            "偏多": "当前偏多路径更多来自：",
        }.get(path, "当前路径更多来自：")
        return f"{prefix}{joined[:220]}"
    return "解析证据有限，当前仅能确认存在方向分歧，暂不宜放大单一路径。"


def _prioritize_views_for_path(path: str, view_texts: list[str]) -> list[str]:
    if path == "偏空":
        tokens = ("打压", "施压", "承压", "回落", "压制", "降级")
    elif path == "偏多":
        tokens = ("配置支撑", "配置机会", "反弹", "修复", "支撑", "购金", "ETF")
    else:
        tokens = ()
    if not tokens:
        return []
    matched = [text for text in view_texts if any(token in text for token in tokens)]
    return sorted(matched, key=lambda text: _path_view_priority(text, tokens), reverse=True)


def _path_view_priority(text: str, tokens: tuple[str, ...]) -> int:
    compact = _compact_text(text)
    score = sum(3 for token in tokens if token in compact)
    if "分析师" in compact or "认为" in compact or "表示" in compact:
        score += 8
    if compact.startswith("#"):
        score -= 6
    if compact.startswith("2、关键指标") or compact.startswith("风险提示"):
        score -= 4
    return score


def _dedupe_texts(texts: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        compact = _compact_text(text)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    return deduped
