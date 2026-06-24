from __future__ import annotations

from apps.documents.schemas import DailyReportAnalysisSnapshot, ParsedDocument, ReportFact


def build_daily_report_analysis_snapshot(parsed: ParsedDocument, facts: list[ReportFact]) -> DailyReportAnalysisSnapshot:
    market_prices = _market_prices(facts)
    logic_chains = _logic_chains(facts)
    watch_variables = _watch_variables(facts)
    key_levels = _key_levels(facts)
    scenario_matrix = _scenario_matrix(facts)
    risks = _risks(facts)
    core_conclusion = _core_conclusion(parsed.title, facts)
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


def _core_conclusion(title: str, facts: list[ReportFact]) -> str:
    macro = any(f.fact_type == "macro_driver" for f in facts)
    views = _summarize_fact_values(facts, "author_view", limit=3, max_chars=360)
    if views:
        return views
    if macro:
        macro_summary = _summarize_fact_values(facts, "macro_driver", limit=3, max_chars=300)
        return macro_summary if macro_summary else title
    return "解析已完成，但正文与图表证据仍不足以形成稳定结论。"


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
