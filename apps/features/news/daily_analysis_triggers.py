from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apps.features.news.event_candidates import EventCandidateBundle, StandardNewsItem
from apps.features.news.impact_classifier import EventImpactAssessment

TRIGGER_TYPE = "jin10_daily_analysis"
RULE_VERSION = "jin10-daily-analysis-trigger-v2"


@dataclass(frozen=True)
class DailyAnalysisTrigger:
    trigger_id: str
    trigger_type: str
    priority: str
    status: str
    source_news_item_id: str
    source_key: str
    source_title: str
    source_url: str
    source_event_id: str
    event_type: str
    impact_path: str
    gold_impact: str
    reason_codes: frozenset[str]
    suggested_actions: list[str]
    evidence_text: str
    asset_tags: list[str]
    topic_tags: list[str]
    source_refs: list[dict[str, Any]]
    data_quality: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reason_codes"] = sorted(self.reason_codes)
        return data


@dataclass(frozen=True)
class DailyAnalysisTriggerBundle:
    as_of: str
    rule_version: str
    triggers: list[DailyAnalysisTrigger]
    data_quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "rule_version": self.rule_version,
            "trigger_count": len(self.triggers),
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "data_quality": self.data_quality,
        }


def build_daily_analysis_triggers(
    *,
    event_bundle: EventCandidateBundle,
    impact_assessments: list[EventImpactAssessment | dict[str, Any]],
    as_of: str,
) -> DailyAnalysisTriggerBundle:
    impact_by_event_id = {
        str(impact.get("event_id") or ""): impact
        for impact in (_impact_dict(item) for item in impact_assessments)
    }
    item_by_id = {item.news_item_id: item for item in event_bundle.raw_news_items}
    triggers: list[DailyAnalysisTrigger] = []
    rejected_event_count = 0

    for event in event_bundle.event_candidates:
        event_dict = event.to_dict()
        impact = impact_by_event_id.get(event.event_id, {})
        event_triggers = [
            trigger
            for item_id in event.related_news_item_ids
            if (trigger := _trigger_for_item(
                item=item_by_id.get(item_id),
                event=event_dict,
                impact=impact,
                as_of=as_of,
            ))
            is not None
        ]
        if event_triggers:
            triggers.extend(event_triggers)
        else:
            rejected_event_count += 1

    triggers = sorted(_dedupe_triggers(triggers), key=lambda trigger: _sort_key(trigger), reverse=True)
    return DailyAnalysisTriggerBundle(
        as_of=as_of,
        rule_version=RULE_VERSION,
        triggers=triggers,
        data_quality={
            "event_candidate_count": len(event_bundle.event_candidates),
            "trigger_count": len(triggers),
            "rejected_event_count": rejected_event_count,
        },
    )


def archive_daily_analysis_triggers(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    bundle: DailyAnalysisTriggerBundle,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "daily_analysis_triggers.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _trigger_for_item(
    *,
    item: StandardNewsItem | None,
    event: dict[str, Any],
    impact: dict[str, Any],
    as_of: str,
) -> DailyAnalysisTrigger | None:
    if item is None or item.source_key != "jin10_feishu":
        return None

    text = " ".join(part for part in (item.title, item.summary, event.get("evidence_text")) if part)
    relevance = item.raw_payload.get("relevance_decision") if isinstance(item.raw_payload, dict) else {}
    relevance = relevance if isinstance(relevance, dict) else {}
    relevance_decision = str(relevance.get("decision") or "")
    relevance_score = _float(relevance.get("score"))
    asset_tags = _dedupe([*event.get("asset_tags", []), *list(relevance.get("asset_tags") or [])])
    topic_tags = _dedupe([*event.get("topic_tags", []), *list(relevance.get("topic_tags") or [])])

    reasons: set[str] = {"jin10_feishu_source"}
    score = 0.20
    if relevance_decision == "high_value":
        score += 0.25
        reasons.add("high_value_relevance")
    elif relevance_decision == "candidate":
        score += 0.12
        reasons.add("candidate_relevance")
    score += min(relevance_score, 1.0) * 0.20

    has_gold = "XAUUSD" in asset_tags or _contains_any(text, ["黄金", "金价", "xau", "gold"])
    has_macro = _contains_any(text, ["美联储", "fed", "fomc", "通胀", "cpi", "pce", "利率", "宽松", "降息", "收益率", "美元"])
    has_energy_inflation = _contains_any(text, ["能源", "原油", "油价", "oil"]) and _contains_any(text, ["通胀", "inflation"])
    has_key_level = _contains_any(text, ["动量", "催化剂", "收复", "关键位", "支撑", "阻力", "破位", "多头", "空头"]) or bool(
        re.search(r"(?<!\d)(?:[34]\d{3}|5\d{3})(?!\d)", text)
    )
    has_detail = item.url.startswith(("http://", "https://"))

    if has_gold:
        score += 0.25
        reasons.add("gold_daily_topic")
    if has_macro:
        score += 0.18
        reasons.add("fed_inflation_path")
    if has_energy_inflation:
        score += 0.08
        reasons.add("energy_inflation_path")
    if has_key_level:
        score += 0.12
        reasons.add("key_level_or_momentum")
    if has_detail:
        score += 0.06
        reasons.add("detail_link_present")
    if event.get("event_type") in {
        "fed_hawkish",
        "fed_dovish",
        "gold_market_narrative",
        "key_level_watchlist",
        "macro_watchlist",
        "oil_supply_shock",
        "hormuz_risk",
    }:
        score += 0.08
        reasons.add("daily_analysis_event_type")

    trigger_score = round(min(score, 1.0), 2)
    if not (trigger_score >= 0.65 and has_gold and (has_macro or has_energy_inflation or has_key_level)):
        return None

    return DailyAnalysisTrigger(
        trigger_id=_trigger_id(item=item, event_id=str(event.get("event_id") or "")),
        trigger_type=TRIGGER_TYPE,
        priority="high" if trigger_score >= 0.82 else "medium",
        status="queued",
        source_news_item_id=item.news_item_id,
        source_key=item.source_key,
        source_title=item.title,
        source_url=item.url,
        source_event_id=str(event.get("event_id") or ""),
        event_type=str(event.get("event_type") or ""),
        impact_path=str(impact.get("impact_path") or ""),
        gold_impact=str(impact.get("gold_impact") or "unknown"),
        reason_codes=frozenset(reasons),
        suggested_actions=[
            "fetch_detail_page",
            "run_browser_profile_fallback_if_access_limited",
            "run_jin10_daily_analysis",
            "keep_single_source_verification_flag",
        ],
        evidence_text=text[:600],
        asset_tags=asset_tags,
        topic_tags=topic_tags,
        source_refs=list(event.get("source_refs") or item.source_refs),
        data_quality={
            "trigger_score": trigger_score,
            "relevance_decision": relevance_decision,
            "relevance_score": relevance_score,
            "verification_status": event.get("verification_status"),
            "source_count": event.get("source_count"),
            "source_type": item.source_type,
        },
        created_at=as_of,
    )


def _impact_dict(impact: EventImpactAssessment | dict[str, Any]) -> dict[str, Any]:
    return impact.to_dict() if isinstance(impact, EventImpactAssessment) else dict(impact)


def _trigger_id(*, item: StandardNewsItem, event_id: str) -> str:
    digest = hashlib.sha256(f"{item.news_item_id}|{event_id}|{TRIGGER_TYPE}".encode("utf-8")).hexdigest()[:16]
    return f"trigger:{TRIGGER_TYPE}:{digest}"


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_triggers(triggers: list[DailyAnalysisTrigger]) -> list[DailyAnalysisTrigger]:
    seen: set[str] = set()
    result: list[DailyAnalysisTrigger] = []
    for trigger in triggers:
        if trigger.trigger_id in seen:
            continue
        seen.add(trigger.trigger_id)
        result.append(trigger)
    return result


def _sort_key(trigger: DailyAnalysisTrigger) -> tuple[float, str]:
    return (
        float(trigger.data_quality.get("trigger_score") or 0.0),
        trigger.created_at,
    )
