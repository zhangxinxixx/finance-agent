from __future__ import annotations

import re

from apps.documents.schemas import ParsedDocument, ReportFact


_NUMBER_PATTERN = r"(?P<value>\d+(?:\.\d+)?)"


def extract_report_facts(parsed: ParsedDocument) -> list[ReportFact]:
    facts: list[ReportFact] = []
    for block in parsed.blocks:
        if block.block_type != "paragraph":
            continue
        text = block.text
        facts.extend(_extract_price_facts(parsed.document_id, block.block_id, block.page, text))
        facts.extend(_extract_macro_facts(parsed.document_id, block.block_id, block.page, text))
        facts.extend(_extract_view_facts(parsed.document_id, block.block_id, block.page, text))
        facts.extend(_extract_weekly_natural_language_facts(parsed.document_id, block.block_id, block.page, text))
        if "风险提示" in text:
            facts.append(
                ReportFact(
                    fact_id=f"{parsed.document_id}:risk:{len(facts) + 1}",
                    fact_type="risk",
                    label="风险提示",
                    value="市场有风险，投资需谨慎。",
                    source_block_id=block.block_id,
                    source_page=block.page,
                    evidence_text=text,
                )
            )
    return facts


def _extract_weekly_natural_language_facts(
    document_id: str,
    block_id: str,
    page: int | None,
    text: str,
) -> list[ReportFact]:
    facts: list[ReportFact] = []
    target_ranges = _extract_target_ranges(text)
    for index, target_range in enumerate(target_ranges, start=1):
        facts.append(
            ReportFact(
                fact_id=f"{document_id}:weekly:price_target:{block_id}:{index}",
                fact_type="price",
                label="黄金目标区间" if "黄金" in text or "金价" in text else "目标区间",
                value=target_range,
                source_block_id=block_id,
                source_page=page,
                evidence_text=text,
                metadata={"instrument": "XAUUSD", "field": "gold_target_range"},
            )
        )

    macro_labels = _weekly_macro_labels(text)
    for index, label in enumerate(macro_labels, start=1):
        facts.append(
            ReportFact(
                fact_id=f"{document_id}:weekly:macro:{block_id}:{index}",
                fact_type="macro_driver",
                label=label,
                value=text,
                source_block_id=block_id,
                source_page=page,
                evidence_text=text,
            )
        )

    if _looks_like_weekly_view(text):
        facts.append(
            ReportFact(
                fact_id=f"{document_id}:weekly:view:{block_id}",
                fact_type="author_view",
                label="周报方向判断",
                value=text,
                source_block_id=block_id,
                source_page=page,
                evidence_text=text,
            )
        )
    return facts


def _extract_target_ranges(text: str) -> list[str]:
    ranges: list[str] = []
    for match in re.finditer(r"(?P<low>\d{3,5}(?:\.\d+)?)\s*(?:至|到|-|~|—|–|－)\s*(?P<high>\d{3,5}(?:\.\d+)?)\s*美元", text):
        value = f"{match.group('low')}-{match.group('high')}"
        if value not in ranges:
            ranges.append(value)
    return ranges


def _weekly_macro_labels(text: str) -> list[str]:
    keyword_labels = [
        ("10年期美债", "10年期美债"),
        ("收益率因子", "收益率因子"),
        ("通胀预期因子", "通胀预期因子"),
        ("期权", "期权结构"),
        ("最大痛", "期权最大痛位"),
        ("COT", "COT持仓"),
        ("未平仓合约", "未平仓合约"),
        ("降息周期", "降息周期"),
        ("支撑/阻力", "支撑阻力区"),
    ]
    labels: list[str] = []
    for keyword, label in keyword_labels:
        if keyword in text and label not in labels:
            labels.append(label)
    return labels


def _looks_like_weekly_view(text: str) -> bool:
    direction_tokens = ("预计", "预期", "基本情景", "目标", "上行", "上涨", "反弹", "推动金价走高", "不太可能进一步下行")
    context_tokens = ("黄金", "金价", "白银", "收益率", "期权", "支撑/阻力", "降息周期")
    return any(token in text for token in direction_tokens) and any(token in text for token in context_tokens)


def _extract_price_facts(document_id: str, block_id: str, page: int | None, text: str) -> list[ReportFact]:
    facts: list[ReportFact] = []
    patterns = [
        ("gold_high", "黄金最高价", rf"现货黄金.*?最高触及{_NUMBER_PATTERN}美元/盎司"),
        ("gold_close", "黄金收盘价", rf"现货黄金.*?报{_NUMBER_PATTERN}美元/盎司"),
        ("silver_close", "白银收盘价", rf"现货白银.*?报{_NUMBER_PATTERN}美元/盎司"),
    ]
    for key, label, pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        facts.append(
            ReportFact(
                fact_id=f"{document_id}:price:{key}",
                fact_type="price",
                label=label,
                value=float(match.group("value")),
                source_block_id=block_id,
                source_page=page,
                evidence_text=text,
                metadata={"instrument": "XAUUSD" if "gold" in key else "XAGUSD", "field": key},
            )
        )
    return facts


def _extract_macro_facts(document_id: str, block_id: str, page: int | None, text: str) -> list[ReportFact]:
    if "关键指标" not in text:
        return []
    labels = []
    for keyword in ("非制造业PMI", "10年期美债收益率", "贝弗里奇曲线", "美联储", "降息"):
        if keyword in text:
            labels.append(keyword)
    return [
        ReportFact(
            fact_id=f"{document_id}:macro:{index}",
            fact_type="macro_driver",
            label=label,
            value=text,
            source_block_id=block_id,
            source_page=page,
            evidence_text=text,
        )
        for index, label in enumerate(labels, start=1)
    ]


def _extract_view_facts(document_id: str, block_id: str, page: int | None, text: str) -> list[ReportFact]:
    if "观点分享" not in text:
        return []
    fragments = [fragment.strip("；。 ") for fragment in re.split(r"[；\n]", text) if "分析师" in fragment]
    return [
        ReportFact(
            fact_id=f"{document_id}:view:{index}",
            fact_type="author_view",
            label=f"分析师观点 {index}",
            value=fragment,
            source_block_id=block_id,
            source_page=page,
            evidence_text=fragment,
        )
        for index, fragment in enumerate(fragments, start=1)
    ]
