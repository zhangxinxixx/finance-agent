from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


SOURCE_KEY = "jin10_technical_levels"
SOURCE_TYPE = "supplemental"
PROVIDER_ROLE = "supplemental_source"
VERIFICATION_STATUS = "single_source"

_PRICE_RE = r"(?<!\d)(?:\d{3,5}(?:\.\d+)?)(?!\d)"


@dataclass(frozen=True)
class Jin10TechnicalLevelExtraction:
    source_key: str
    status: str
    items: list[dict[str, Any]]
    source_refs: list[dict[str, Any]]
    data_quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "status": self.status,
            "items": self.items,
            "source_refs": self.source_refs,
            "data_quality": self.data_quality,
            "warnings": self.warnings,
        }


def extract_jin10_technical_levels(
    *,
    raw_article_report: Mapping[str, Any],
    daily_analysis: Mapping[str, Any] | None = None,
    agent_analysis_report: Mapping[str, Any] | None = None,
    artifact_paths: Mapping[str, str | Path] | None = None,
    fetched_at: str | None = None,
) -> Jin10TechnicalLevelExtraction:
    raw_report = dict(raw_article_report)
    daily_report = dict(daily_analysis or {})
    agent_report = dict(agent_analysis_report or {})
    artifact_path_map = {key: str(value) for key, value in dict(artifact_paths or {}).items()}
    source_refs = _collect_source_refs(
        raw_report=raw_report,
        daily_report=daily_report,
        agent_report=agent_report,
        artifact_paths=artifact_path_map,
    )
    report_type = _first_text(raw_report.get("report_type"), daily_report.get("report_type"), "technical_levels")
    article_id = _first_text(raw_report.get("article_id"), daily_report.get("article_id"), agent_report.get("article_id"), "")
    run_id = _first_text(raw_report.get("run_id"), daily_report.get("run_id"), agent_report.get("run_id"), article_id)
    symbol = _symbol_for_text(_joined_text(raw_report, daily_report, agent_report))
    text_sources = _text_sources(raw_report, daily_report, agent_report)
    items = _dedupe_levels(
        [
            item
            for text in text_sources
            for item in _levels_from_text(
                text=text,
                default_symbol=symbol,
                source_refs=source_refs,
                article_id=article_id,
                run_id=run_id,
                report_type=report_type,
                fetched_at=fetched_at,
            )
        ]
    )
    status = "ok" if items else "empty"
    warnings = [] if items else ["No deterministic technical levels with explicit prices or ranges were found."]
    return Jin10TechnicalLevelExtraction(
        source_key=SOURCE_KEY,
        status=status,
        items=items,
        source_refs=source_refs,
        data_quality={
            "article_id": article_id,
            "run_id": run_id,
            "report_type": report_type,
            "level_count": len(items),
            "source_ref_count": len(source_refs),
        },
        warnings=warnings,
    )


def archive_jin10_technical_levels(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    extraction: Jin10TechnicalLevelExtraction,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "technical_levels.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _levels_from_text(
    *,
    text: str,
    default_symbol: str,
    source_refs: list[dict[str, Any]],
    article_id: str,
    run_id: str,
    report_type: str,
    fetched_at: str | None,
) -> list[dict[str, Any]]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    symbol = _symbol_for_text(cleaned, fallback=default_symbol)
    results: list[dict[str, Any]] = []
    results.extend(
        _market_profile_levels(
            text=cleaned,
            symbol=symbol,
            source_refs=source_refs,
            article_id=article_id,
            run_id=run_id,
            report_type=report_type,
            fetched_at=fetched_at,
        )
    )
    for chunk in _split_clauses(cleaned):
        results.extend(
            _directional_levels(
                text=chunk,
                symbol=symbol,
                source_refs=source_refs,
                article_id=article_id,
                run_id=run_id,
                report_type=report_type,
                fetched_at=fetched_at,
            )
        )
        results.extend(
            _volume_profile_levels(
                text=chunk,
                symbol=symbol,
                source_refs=source_refs,
                article_id=article_id,
                run_id=run_id,
                report_type=report_type,
                fetched_at=fetched_at,
            )
        )
    return results


def _market_profile_levels(
    *,
    text: str,
    symbol: str,
    source_refs: list[dict[str, Any]],
    article_id: str,
    run_id: str,
    report_type: str,
    fetched_at: str | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for match in re.finditer(r"\b(VAH|VAL|POC)\b\s*[:：=]?\s*(" + _PRICE_RE + r")", text, flags=re.IGNORECASE):
        level_type = match.group(1).upper()
        price = _to_float(match.group(2))
        if price is None:
            continue
        results.append(
            _level_item(
                symbol=symbol,
                level_type=level_type,
                price=price,
                price_range=None,
                evidence_text=text,
                trigger_condition="",
                confidence=0.78,
                source_refs=source_refs,
                article_id=article_id,
                run_id=run_id,
                report_type=report_type,
                fetched_at=fetched_at,
            )
        )
    return results


def _directional_levels(
    *,
    text: str,
    symbol: str,
    source_refs: list[dict[str, Any]],
    article_id: str,
    run_id: str,
    report_type: str,
    fetched_at: str | None,
) -> list[dict[str, Any]]:
    level_type = ""
    if _contains_any(text, ("支撑", "支撑位", "支撑区间", "下方支撑")):
        level_type = "support"
    elif _contains_any(text, ("阻力", "压力", "上方阻力", "压力位")):
        level_type = "resistance"
    if not level_type:
        return []

    price_range = _extract_range(text)
    price = None if price_range else _extract_level_price(text, level_type=level_type)
    if price is None and price_range is None:
        return []
    return [
        _level_item(
            symbol=symbol,
            level_type=level_type,
            price=price,
            price_range=price_range,
            evidence_text=text,
            trigger_condition=_trigger_condition(text),
            confidence=0.72,
            source_refs=source_refs,
            article_id=article_id,
            run_id=run_id,
            report_type=report_type,
            fetched_at=fetched_at,
        )
    ]


def _volume_profile_levels(
    *,
    text: str,
    symbol: str,
    source_refs: list[dict[str, Any]],
    article_id: str,
    run_id: str,
    report_type: str,
    fetched_at: str | None,
) -> list[dict[str, Any]]:
    if not _contains_any(text, ("筹码峰", "成交密集区", "成本峰", "volume profile")):
        return []
    price_range = _extract_range(text)
    price = None if price_range else _extract_first_price(text)
    if price is None and price_range is None:
        return []
    return [
        _level_item(
            symbol=symbol,
            level_type="volume_profile_peak",
            price=price,
            price_range=price_range,
            evidence_text=text,
            trigger_condition=_trigger_condition(text),
            confidence=0.64,
            source_refs=source_refs,
            article_id=article_id,
            run_id=run_id,
            report_type=report_type,
            fetched_at=fetched_at,
        )
    ]


def _level_item(
    *,
    symbol: str,
    level_type: str,
    price: float | None,
    price_range: dict[str, float] | None,
    evidence_text: str,
    trigger_condition: str,
    confidence: float,
    source_refs: list[dict[str, Any]],
    article_id: str,
    run_id: str,
    report_type: str,
    fetched_at: str | None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "level_type": level_type,
        "price": price,
        "range": price_range,
        "evidence_text": evidence_text,
        "trigger_condition": trigger_condition,
        "confidence": confidence,
        "source_refs": source_refs,
        "verification_status": VERIFICATION_STATUS,
        "provider_role": PROVIDER_ROLE,
        "source_key": SOURCE_KEY,
        "source_type": SOURCE_TYPE,
        "article_id": article_id,
        "run_id": run_id,
        "report_type": report_type,
        "fetched_at": fetched_at or "",
    }


def _extract_range(text: str) -> dict[str, float] | None:
    match = re.search(rf"({_PRICE_RE})\s*[-~—–至到]\s*({_PRICE_RE})", text)
    if not match:
        return None
    first = _to_float(match.group(1))
    second = _to_float(match.group(2))
    if first is None or second is None:
        return None
    low, high = sorted((first, second))
    return {"low": low, "high": high}


def _extract_level_price(text: str, *, level_type: str) -> float | None:
    if level_type == "support":
        patterns = (
            r"测试\s*(" + _PRICE_RE + r")\s*(?:一线|附近|支撑)",
            r"(" + _PRICE_RE + r")\s*(?:一线|附近|区域|区间)?\s*支撑",
            r"支撑(?:位|区域|区间)?(?:在|看|为|:|：)?\s*(" + _PRICE_RE + r")",
        )
    else:
        patterns = (
            r"(?:上看|看向|测试)\s*(" + _PRICE_RE + r")\s*(?:一线|附近|阻力|压力)",
            r"(" + _PRICE_RE + r")\s*(?:一线|附近|区域|区间)?\s*(?:阻力|压力)",
            r"(?:阻力|压力)(?:位|区域|区间)?(?:在|看|为|:|：)?\s*(" + _PRICE_RE + r")",
        )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _to_float(match.group(1))
    return None


def _extract_first_price(text: str) -> float | None:
    match = re.search(_PRICE_RE, text)
    return _to_float(match.group(0)) if match else None


def _trigger_condition(text: str) -> str:
    if "未给出明确触发条件" in text or "未标注" in text:
        return ""
    match = re.search(r"(?:若|如果|如)(.+?)(?:，|,)?则", text)
    if match:
        return _clean_text(match.group(1))
    match = re.search(r"(站稳" + _PRICE_RE + r"(?:上方|以上)?|跌破" + _PRICE_RE + r"(?:下方|以下)?|突破" + _PRICE_RE + r"(?:上方|以上)?)", text)
    return _clean_text(match.group(1)) if match else ""


def _collect_source_refs(
    *,
    raw_report: Mapping[str, Any],
    daily_report: Mapping[str, Any],
    agent_report: Mapping[str, Any],
    artifact_paths: Mapping[str, str],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for report in (raw_report, daily_report, agent_report):
        for ref in report.get("source_refs") or []:
            if isinstance(ref, Mapping):
                refs.append(dict(ref))
    for name, path in artifact_paths.items():
        refs.append({"source": "jin10_artifact", "asset_type": name, "path": path})
    return _dedupe_refs(refs)


def _text_sources(
    raw_report: Mapping[str, Any],
    daily_report: Mapping[str, Any],
    agent_report: Mapping[str, Any],
) -> list[str]:
    values: list[str] = []
    for report in (raw_report, daily_report, agent_report):
        for key in ("title", "article_markdown", "vlm_markdown", "core_conclusion", "one_line_conclusion", "final_summary"):
            values.extend(_split_sentences(str(report.get(key) or "")))
    article_context = dict(dict(raw_report.get("generated_from") or {}).get("article_context") or {})
    for key in ("key_sentences", "level_snippets", "paragraph_snippets", "chart_summaries", "vlm_markdown"):
        for value in article_context.get(key) or []:
            values.extend(_split_sentences(str(value)))
    for insight in raw_report.get("image_insights") or []:
        if isinstance(insight, Mapping):
            for key in ("markdown", "text", "summary", "analysis"):
                values.extend(_split_sentences(str(insight.get(key) or "")))
    return _dedupe_texts(values)


def _split_sentences(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip(" #*-") for part in re.split(r"[\n。；;!?！？]+", value) if part.strip(" #*-")]


def _split_clauses(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[；;。]", value) if part.strip()]


def _symbol_for_text(text: str, fallback: str = "XAUUSD") -> str:
    lowered = text.lower()
    if "xauusd" in lowered or "黄金" in text or "金价" in text:
        return "XAUUSD"
    if "xagusd" in lowered or "白银" in text or "银价" in text:
        return "XAGUSD"
    if "dxy" in lowered or "美元指数" in text:
        return "DXY"
    return fallback


def _joined_text(*reports: Mapping[str, Any]) -> str:
    return "\n".join(str(report.get(key) or "") for report in reports for key in ("title", "article_markdown", "vlm_markdown"))


def _dedupe_levels(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        price_range = item.get("range") or {}
        key = (
            item.get("symbol"),
            item.get("level_type"),
            item.get("price"),
            price_range.get("low"),
            price_range.get("high"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
