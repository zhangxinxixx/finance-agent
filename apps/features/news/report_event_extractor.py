from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from apps.collectors.news.base import RawNewsItem, stable_news_item_id, utc_now_iso

SOURCE_KEY = "jin10_report_events"
SOURCE_NAME = "Jin10 report-derived events"
SOURCE_TYPE = "supplemental"


@dataclass(frozen=True)
class Jin10ReportEventExtraction:
    source_key: str
    status: str
    items: list[RawNewsItem]
    source_refs: list[dict[str, Any]]
    data_quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "source_refs": self.source_refs,
            "data_quality": self.data_quality,
            "warnings": self.warnings,
        }


def extract_jin10_report_events(
    *,
    raw_article_report: Mapping[str, Any],
    daily_analysis: Mapping[str, Any] | None = None,
    agent_analysis_report: Mapping[str, Any] | None = None,
    artifact_paths: Mapping[str, str | Path] | None = None,
    fetched_at: str | None = None,
) -> Jin10ReportEventExtraction:
    raw_report = dict(raw_article_report)
    daily_report = dict(daily_analysis or {})
    agent_report = dict(agent_analysis_report or {})
    artifact_path_map = {key: str(value) for key, value in dict(artifact_paths or {}).items()}

    report_title = _first_text(raw_report.get("title"), daily_report.get("title"), agent_report.get("title"), "Jin10 report")
    article_id = _first_text(raw_report.get("article_id"), daily_report.get("article_id"), agent_report.get("article_id"), "")
    report_run_id = _first_text(raw_report.get("run_id"), daily_report.get("run_id"), agent_report.get("run_id"), article_id)
    document_id = _first_text(raw_report.get("document_id"), daily_report.get("document_id"), agent_report.get("document_id"), "")
    report_type = _first_text(raw_report.get("report_type"), daily_report.get("report_type"), "daily")
    published_at = _report_datetime(raw_report, daily_report)
    source_url = _source_url(raw_report, daily_report)
    source_refs = _collect_source_refs(
        raw_report=raw_report,
        daily_report=daily_report,
        agent_report=agent_report,
        artifact_paths=artifact_path_map,
    )
    quality_audit = _quality_audit(raw_report, daily_report, agent_report)
    quality_status = str(quality_audit.get("status") or "unknown")
    warnings = _warnings_for_quality(quality_status)
    text_sources = _text_sources(raw_report, daily_report, agent_report)

    items: list[RawNewsItem] = []
    for rule in _EVENT_RULES:
        if not rule["matches"](text_sources.joined):
            continue
        evidence = _evidence_for_rule(text_sources.sentences, rule["markers"])
        item_title = f"{report_title} | {rule['label']}"
        event_url = f"{source_url}#event={rule['event_type']}" if source_url else f"jin10://report/{report_run_id}#{rule['event_type']}"
        items.append(
            RawNewsItem(
                source_key=SOURCE_KEY,
                source_name=SOURCE_NAME,
                source_type=SOURCE_TYPE,
                feed_key=str(rule["feed_key"]),
                title=item_title,
                url=event_url,
                domain=_domain(source_url),
                published_at=published_at,
                fetched_at=fetched_at or utc_now_iso(),
                summary=evidence,
                source_country="CN",
                source_language="zh",
                event_type=str(rule["event_type"]),
                verification_status="single_source",
                duplicate_key=stable_news_item_id(source_key=SOURCE_KEY, title=item_title, url=event_url),
                raw_path=artifact_path_map.get("raw_article_report"),
                parsed_path=artifact_path_map.get("daily_analysis") or artifact_path_map.get("agent_analysis_report"),
                raw_payload={
                    "article_id": article_id,
                    "report_run_id": report_run_id,
                    "document_id": document_id,
                    "report_type": report_type,
                    "report_title": report_title,
                    "report_date": _first_text(raw_report.get("trade_date"), daily_report.get("trade_date"), ""),
                    "data_category": "external_opinion",
                    "quality_audit_status": quality_status,
                    "quality_audit": quality_audit,
                    "source_refs": source_refs,
                    "artifact_paths": artifact_path_map,
                    "evidence_kind": rule["evidence_kind"],
                },
            )
        )

    status = _status(items=items, quality_status=quality_status)
    data_quality = {
        "article_id": article_id,
        "report_run_id": report_run_id,
        "document_id": document_id,
        "quality_audit_status": quality_status,
        "event_count": len(items),
        "source_ref_count": len(source_refs),
        "has_daily_analysis": bool(daily_report),
        "has_agent_analysis": bool(agent_report),
    }
    if not items:
        warnings.append("No report-derived news events matched deterministic P0 rules.")

    return Jin10ReportEventExtraction(
        source_key=SOURCE_KEY,
        status=status,
        items=items,
        source_refs=source_refs,
        data_quality=data_quality,
        warnings=warnings,
    )


def archive_jin10_report_events(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    extraction: Jin10ReportEventExtraction,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "report_events.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


@dataclass(frozen=True)
class _TextSources:
    sentences: list[str]
    joined: str


def _text_sources(
    raw_report: Mapping[str, Any],
    daily_report: Mapping[str, Any],
    agent_report: Mapping[str, Any],
) -> _TextSources:
    values: list[str] = []
    values.extend(_split_text(str(raw_report.get("title") or "")))
    values.extend(_split_text(str(raw_report.get("article_markdown") or "")))
    article_context = dict(dict(raw_report.get("generated_from") or {}).get("article_context") or {})
    for key in ("key_sentences", "level_snippets", "paragraph_snippets", "chart_summaries"):
        values.extend(str(value) for value in article_context.get(key) or [] if value)
    for section in article_context.get("sections") or []:
        if isinstance(section, Mapping):
            values.extend(_split_text(str(section.get("summary") or "")))
    for key in ("title", "core_conclusion"):
        values.extend(_split_text(str(daily_report.get(key) or "")))
    for logic_chain in daily_report.get("logic_chains") or []:
        if isinstance(logic_chain, Mapping):
            values.extend(_split_text(str(logic_chain.get("summary") or "")))
    for key in ("one_line_conclusion", "gold_analysis", "final_summary"):
        values.extend(_split_text(str(agent_report.get(key) or "")))
    evidence_basis = dict(agent_report.get("evidence_basis") or {})
    for view in evidence_basis.get("author_views") or []:
        values.extend(_split_text(str(view)))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        sentence = re.sub(r"\s+", " ", value).strip()
        if not sentence or sentence in seen:
            continue
        seen.add(sentence)
        deduped.append(sentence)
    return _TextSources(sentences=deduped, joined="\n".join(deduped).lower())


def _split_text(value: str) -> list[str]:
    if not value:
        return []
    chunks = re.split(r"[\n。；;!?！？]+", value)
    return [chunk.strip(" #*-") for chunk in chunks if chunk.strip(" #*-")]


def _contains_all(text: str, markers: tuple[str, ...]) -> bool:
    return all(marker.lower() in text for marker in markers)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in text for marker in markers)


_EVENT_RULES: tuple[dict[str, Any], ...] = (
    {
        "event_type": "oil_supply_shock",
        "feed_key": "jin10_report_oil_context",
        "label": "原油/通胀风险观点",
        "markers": ("原油", "opec", "供应", "减产", "eia", "库存", "wti", "布伦特", "通胀"),
        "evidence_kind": "external_opinion_oil_context",
        "matches": lambda text: _contains_any(text, ("原油", "wti", "布伦特", "opec", "eia"))
        and _contains_any(text, ("供应", "减产", "库存", "地缘", "油价", "通胀")),
    },
    {
        "event_type": "yen_intervention_risk",
        "feed_key": "jin10_report_fx_yen_intervention",
        "label": "外汇/日元干预风险观点",
        "markers": ("外汇", "日元", "干预", "usdjpy", "美元兑日元"),
        "evidence_kind": "external_opinion_fx_intervention_risk",
        "matches": lambda text: _contains_any(text, ("日元", "usdjpy", "美元兑日元")) and "干预" in text,
    },
    {
        "event_type": "gold_fund_flow",
        "feed_key": "jin10_report_gold_fund_flow",
        "label": "黄金资金/ETF观点",
        "markers": ("黄金", "etf", "资金"),
        "evidence_kind": "external_opinion_fund_flow",
        "matches": lambda text: _contains_all(text, ("黄金", "etf")) and _contains_any(text, ("资金", "流入", "流出", "观望")),
    },
    {
        "event_type": "silver_industrial_demand",
        "feed_key": "jin10_report_silver_view",
        "label": "白银估值/需求观点",
        "markers": ("白银", "低估", "宏观支撑", "公允价格", "工业需求", "光伏"),
        "evidence_kind": "external_opinion_silver_view",
        "matches": lambda text: "白银" in text and _contains_any(text, ("低估", "宏观支撑", "公允价格", "工业需求", "光伏")),
    },
    {
        "event_type": "macro_watchlist",
        "feed_key": "jin10_report_macro_watchlist",
        "label": "宏观催化剂观察",
        "markers": ("催化剂", "cpi", "pce", "fed", "非农", "利率", "美元", "美债"),
        "evidence_kind": "external_opinion_macro_watchlist",
        "matches": lambda text: _contains_any(text, ("催化剂", "cpi", "pce", "fed", "非农", "利率", "美元", "美债")),
    },
    {
        "event_type": "gold_market_narrative",
        "feed_key": "jin10_report_gold_market_narrative",
        "label": "黄金市场观点",
        "markers": ("黄金", "方向", "修复", "承压", "下行", "反弹"),
        "evidence_kind": "external_opinion_gold_view",
        "matches": lambda text: "黄金" in text and _contains_any(text, ("方向", "修复", "承压", "下行", "反弹")),
    },
)


def _evidence_for_rule(sentences: list[str], markers: tuple[str, ...]) -> str:
    lower_markers = tuple(marker.lower() for marker in markers)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in lower_markers):
            return _truncate(sentence, 360)
    return _truncate(sentences[0], 360) if sentences else ""


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "..."


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _source_url(*reports: Mapping[str, Any]) -> str:
    for report in reports:
        url = _first_text(report.get("source_url"))
        if url:
            return url
        for ref in report.get("source_refs") or []:
            if isinstance(ref, Mapping):
                url = _first_text(ref.get("source_url"))
                if url:
                    return url
    return ""


def _domain(source_url: str) -> str:
    if not source_url:
        return "jin10.com"
    domain = urlparse(source_url).netloc.lower()
    return domain or "jin10.com"


def _report_datetime(raw_report: Mapping[str, Any], daily_report: Mapping[str, Any]) -> str | None:
    trade_date = _first_text(raw_report.get("trade_date"), daily_report.get("trade_date"))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date):
        return f"{trade_date}T00:00:00+00:00"
    markdown = str(raw_report.get("article_markdown") or "")
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", markdown)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00+00:00"


def _quality_audit(*reports: Mapping[str, Any]) -> dict[str, Any]:
    for report in reports:
        quality = report.get("quality_audit")
        if isinstance(quality, Mapping):
            return dict(quality)
    return {"status": "unknown", "reasons": []}


def _warnings_for_quality(quality_status: str) -> list[str]:
    if quality_status in {"pass", "ok", "success"}:
        return []
    if quality_status == "unknown":
        return ["Jin10 report quality_audit.status is missing."]
    return [f"Jin10 report quality_audit.status={quality_status}."]


def _status(*, items: list[RawNewsItem], quality_status: str) -> str:
    if not items:
        return "unavailable"
    if quality_status in {"pass", "ok", "success"}:
        return "success"
    return "partial"


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
    for asset_type, path in artifact_paths.items():
        refs.append(
            {
                "source": SOURCE_KEY,
                "asset_type": asset_type,
                "path": path,
            }
        )
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped
