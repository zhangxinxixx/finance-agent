from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.features.news.event_candidates import EventCandidate

RULE_VERSION = "news-impact-rules-v1"


@dataclass(frozen=True)
class EventImpactAssessment:
    event_id: str
    impact_path: str
    gold_impact: str
    silver_impact: str
    dollar_impact: str
    yield_impact: str
    oil_impact: str
    risk_level: str
    pricing_status: str
    invalidation_condition: str
    model_name: str
    prompt_version_id: str | None
    rule_version: str
    confidence: float
    created_at: str
    source_event: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_impact_assessments(
    events: list[EventCandidate | dict[str, Any]],
    *,
    as_of: str | None = None,
) -> list[EventImpactAssessment]:
    created_at = as_of or datetime.now(timezone.utc).isoformat()
    return [_assess_event(_event_dict(event), created_at=created_at) for event in events]


def archive_impact_assessments(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    assessments: list[EventImpactAssessment],
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "impact_assessments.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "rule_version": RULE_VERSION,
        "impact_assessments": [assessment.to_dict() for assessment in assessments],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _event_dict(event: EventCandidate | dict[str, Any]) -> dict[str, Any]:
    return event.to_dict() if isinstance(event, EventCandidate) else dict(event)


def _assess_event(event: dict[str, Any], *, created_at: str) -> EventImpactAssessment:
    event_type = str(event.get("event_type") or "market_news_candidate")
    event_status = str(event.get("event_status") or "developing")
    rule = _rule_for_event(event_type=event_type, event_status=event_status)
    confidence = _assessment_confidence(event=event, rule=rule)
    return EventImpactAssessment(
        event_id=str(event.get("event_id") or ""),
        impact_path=rule["impact_path"],
        gold_impact=rule["gold_impact"],
        silver_impact=rule["silver_impact"],
        dollar_impact=rule["dollar_impact"],
        yield_impact=rule["yield_impact"],
        oil_impact=rule["oil_impact"],
        risk_level=rule["risk_level"],
        pricing_status=rule["pricing_status"],
        invalidation_condition=rule["invalidation_condition"],
        model_name="deterministic_rules",
        prompt_version_id=None,
        rule_version=RULE_VERSION,
        confidence=confidence,
        created_at=created_at,
        source_event={
            "event_id": event.get("event_id"),
            "event_type": event_type,
            "verification_status": event.get("verification_status"),
            "event_status": event_status,
            "asset_tags": event.get("asset_tags", []),
            "source_count": event.get("source_count"),
        },
    )


def _rule_for_event(*, event_type: str, event_status: str) -> dict[str, str]:
    if event_status == "scheduled" and event_type in {"inflation_release", "labor_release", "pce_release", "gdp_release", "energy_inventory_release"}:
        return {
            "impact_path": "scheduled_macro_release_to_rates" if event_type != "energy_inventory_release" else "scheduled_energy_inventory_to_oil",
            "gold_impact": "unknown",
            "silver_impact": "unknown",
            "dollar_impact": "unknown",
            "yield_impact": "unknown",
            "oil_impact": "unknown",
            "risk_level": "medium",
            "pricing_status": "scheduled",
            "invalidation_condition": "等待官方实际数据和市场反应确认方向",
        }
    if event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"}:
        return {
            "impact_path": "geo_risk_to_oil_to_inflation",
            "gold_impact": "mixed",
            "silver_impact": "mixed",
            "dollar_impact": "dollar_strength",
            "yield_impact": "yield_up",
            "oil_impact": "oil_up",
            "risk_level": "high",
            "pricing_status": "unpriced",
            "invalidation_condition": "官方缓和或停火确认且油价回落至事件前水平",
        }
    if event_type in {"fed_dovish"}:
        return {
            "impact_path": "weak_data_to_rate_cut",
            "gold_impact": "bullish",
            "silver_impact": "bullish",
            "dollar_impact": "dollar_weakness",
            "yield_impact": "yield_down",
            "oil_impact": "unknown",
            "risk_level": "medium",
            "pricing_status": "partially_priced",
            "invalidation_condition": "后续 Fed 讲话或通胀数据重新推高利率预期",
        }
    if event_type in {"fed_hawkish", "fomc_statement", "fed_speech"}:
        return {
            "impact_path": "strong_data_to_higher_for_longer",
            "gold_impact": "bearish",
            "silver_impact": "bearish",
            "dollar_impact": "dollar_strength",
            "yield_impact": "yield_up",
            "oil_impact": "unknown",
            "risk_level": "medium",
            "pricing_status": "partially_priced",
            "invalidation_condition": "经济数据走弱或 Fed 口径转鸽导致收益率回落",
        }
    if event_type == "yen_intervention_risk":
        return {
            "impact_path": "usd_weakness_relief",
            "gold_impact": "bullish",
            "silver_impact": "bullish",
            "dollar_impact": "dollar_weakness",
            "yield_impact": "unknown",
            "oil_impact": "unknown",
            "risk_level": "medium",
            "pricing_status": "unpriced",
            "invalidation_condition": "日本财务省淡化干预风险或 USDJPY 回落",
        }
    if event_type == "silver_industrial_demand":
        return {
            "impact_path": "silver_industrial_outperform",
            "gold_impact": "neutral",
            "silver_impact": "relative_bullish",
            "dollar_impact": "unknown",
            "yield_impact": "unknown",
            "oil_impact": "unknown",
            "risk_level": "low",
            "pricing_status": "unknown",
            "invalidation_condition": "工业需求或光伏需求数据转弱",
        }
    if event_type == "gold_fund_flow":
        return {
            "impact_path": "gold_etf_flow_watchlist",
            "gold_impact": "neutral",
            "silver_impact": "neutral",
            "dollar_impact": "unknown",
            "yield_impact": "unknown",
            "oil_impact": "unknown",
            "risk_level": "low",
            "pricing_status": "unknown",
            "invalidation_condition": "ETF资金从观望转为连续净流入或净流出并被行情确认",
        }
    if event_type in {"macro_watchlist", "gold_market_narrative", "key_level_watchlist"}:
        return {
            "impact_path": "external_report_watchlist",
            "gold_impact": "unknown",
            "silver_impact": "unknown",
            "dollar_impact": "unknown",
            "yield_impact": "unknown",
            "oil_impact": "unknown",
            "risk_level": "low",
            "pricing_status": "unknown",
            "invalidation_condition": "等待官方数据、行情反应或多源确认报告观点",
        }
    return {
        "impact_path": "market_news_watchlist",
        "gold_impact": "unknown",
        "silver_impact": "unknown",
        "dollar_impact": "unknown",
        "yield_impact": "unknown",
        "oil_impact": "unknown",
        "risk_level": "low",
        "pricing_status": "unknown",
        "invalidation_condition": "等待多源确认和市场反应",
    }


def _assessment_confidence(*, event: dict[str, Any], rule: dict[str, str]) -> float:
    base = float(event.get("confidence") or 0.45)
    verification_status = str(event.get("verification_status") or "single_source")
    if verification_status == "official_confirmed":
        base += 0.08
    elif verification_status == "multi_source":
        base += 0.04
    elif verification_status == "single_source":
        base -= 0.08
    if rule["pricing_status"] == "scheduled":
        base += 0.04
    if rule["risk_level"] == "high":
        base += 0.03
    return round(max(0.0, min(base, 0.95)), 2)
