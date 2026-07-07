from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.contracts.gold import GOLD_MAINLINE_IDS

SCHEMA_VERSION = "gold-event-mainlines-v1"
RULE_VERSION = "gold-event-mainlines-rules-v2"

MAINLINE_ORDER = list(GOLD_MAINLINE_IDS)

MAINLINE_META: dict[str, dict[str, Any]] = {
    "fed_policy_path": {
        "label": "美联储利率路径",
        "pricing_layer": "pricing_center",
        "summary": "通胀、就业和 FOMC 通过美联储预期影响美债与黄金机会成本。",
        "missing_data": ["official_data"],
    },
    "real_rates_usd": {
        "label": "实际利率与美元",
        "pricing_layer": "pricing_center",
        "summary": "10Y TIPS、名义利率和 DXY 是黄金估值压力的核心变量。",
        "missing_data": ["real_rates"],
    },
    "oil_prices": {
        "label": "石油价格",
        "pricing_layer": "external_shock",
        "summary": "Brent/WTI 与能源库存决定战争事件是否传导为通胀和利率压力。",
        "missing_data": ["oil_price"],
    },
    "geopolitical_war_risk": {
        "label": "地缘战争风险",
        "pricing_layer": "external_shock",
        "summary": "战争和航运风险同时影响避险买盘与能源通胀链。",
        "missing_data": ["news_sources"],
    },
    "etf_flows": {
        "label": "ETF资金流",
        "pricing_layer": "capital_confirmation",
        "summary": "全球、北美和亚洲 ETF 流入/流出验证趋势资金是否回归黄金。",
        "missing_data": ["etf_flows"],
    },
    "institutional_sentiment": {
        "label": "COMEX / 期权 / 机构情绪",
        "pricing_layer": "capital_confirmation",
        "summary": "COT、COMEX 净多、期权 Call/Put、波动率和机构目标价反映拥挤度与短线结构。",
        "missing_data": ["positioning_data"],
    },
    "central_bank_gold": {
        "label": "央行买金与货币信用重估",
        "pricing_layer": "structural_support",
        "summary": "央行储备重配与去美元化构成长期底层买盘。",
        "missing_data": ["central_bank_reserves"],
    },
    "china_asia_demand": {
        "label": "中国与亚洲需求",
        "pricing_layer": "structural_support",
        "summary": "上海金溢价、人民币黄金与亚洲实物需求反映区域买盘。",
        "missing_data": ["asia_physical_demand"],
    },
    "gold_technical_levels": {
        "label": "黄金关键技术位与阶段判断",
        "pricing_layer": "price_confirmation",
        "summary": "3900 / 4000 / 4100-4120 / 4300 等关键位用于确认宏观逻辑是否被市场接受。",
        "missing_data": ["xauusd_price"],
    },
}

VERIFICATION_SOURCE_MAP: dict[str, str] = {
    "multi_source_confirmation_needed": "news_sources",
    "oil_price_reaction_needed": "oil_price",
    "real_rate_response_needed": "real_rates",
    "flow_data_confirmation_needed": "etf_flows",
    "price_level_confirmation_needed": "xauusd_price",
    "official_release_needed": "official_data",
    "official_reserve_data_needed": "central_bank_reserves",
    "positioning_confirmation_needed": "positioning_data",
    "macro_data_confirmation_needed": "macro_data",
    "fx_market_confirmation_needed": "fx_market",
}


@dataclass(frozen=True)
class GoldMainlineRule:
    mainline_ids: list[str]
    primary_mainline: str
    transmission_path_ids: list[str]
    bullish_drivers: list[str] = field(default_factory=list)
    bearish_drivers: list[str] = field(default_factory=list)
    dominant_driver: str | None = None
    verification_checks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldEventMainlineLink:
    event_id: str
    mainline_ids: list[str]
    primary_mainline: str
    transmission_path_ids: list[str]
    direction_by_asset: dict[str, str]
    pricing_status: str | None
    verification_status: str | None
    market_validation_ref: str | None
    bullish_drivers: list[str]
    bearish_drivers: list[str]
    dominant_driver: str | None
    verification_needed: list[str]
    verification_chain: dict[str, Any]
    changed_dominant_theme: bool
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoldMainlineSummary:
    mainline_id: str
    mainline: str
    label: str
    pricing_layer: str
    rank: int
    score: float | None
    theme_score: int | None
    direction_score: int
    impact_score: int
    confidence_score: int
    freshness_score: int
    direction: str
    confidence: float | None
    verification_status: str
    coverage_status: str
    trend: str
    dominant: bool
    summary: str
    bullish_drivers: list[str]
    bearish_drivers: list[str]
    event_ids: list[str]
    related_event_ids: list[str]
    source_refs: list[dict[str, Any]]
    evidence_count: int
    missing_data: list[str]
    freshness: str
    impact_strength: str
    verification_needed: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoldEventMainlinesBundle:
    schema_version: str
    rule_version: str
    asset: str
    as_of: str | None
    status: str
    mainlines: list[GoldMainlineSummary]
    event_links: list[GoldEventMainlineLink]
    dominant_forces: list[str]
    source_refs: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "asset": self.asset,
            "as_of": self.as_of,
            "status": self.status,
            "mainlines": [item.to_dict() for item in self.mainlines],
            "event_links": [item.to_dict() for item in self.event_links],
            "dominant_forces": self.dominant_forces,
            "source_refs": self.source_refs,
            "warnings": self.warnings,
        }


def build_gold_event_mainlines(
    events: list[Any],
    *,
    impact_assessments: list[Any] | None = None,
    as_of: str | None = None,
    asset: str = "XAUUSD",
) -> GoldEventMainlinesBundle:
    created_at = as_of or datetime.now(timezone.utc).isoformat()
    impacts = [_dict(item) for item in impact_assessments or []]
    impact_by_event_id = {str(item.get("event_id") or ""): item for item in impacts}
    event_dicts = [_dict(item) for item in events]
    links = [
        _build_event_link(event, impact=impact_by_event_id.get(str(event.get("event_id") or "")))
        for event in event_dicts
    ]
    mainlines = _aggregate_mainlines(links=links, events=event_dicts)
    dominant_forces = [
        item.mainline_id
        for item in sorted(
            [item for item in mainlines if item.coverage_status == "covered"],
            key=lambda item: (-(item.score or 0), item.rank),
        )[:2]
    ]
    return GoldEventMainlinesBundle(
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        asset=asset,
        as_of=created_at,
        status=_bundle_status(links),
        mainlines=mainlines,
        event_links=links,
        dominant_forces=dominant_forces,
        source_refs=_merge_source_refs(link.source_refs for link in links),
        warnings=[],
    )


def archive_gold_event_mainlines(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    bundle: GoldEventMainlinesBundle,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "gold_event_mainlines.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        **bundle.to_dict(),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _build_event_link(event: dict[str, Any], *, impact: dict[str, Any] | None) -> GoldEventMainlineLink:
    impact = impact or {}
    rule = _rule_for_event(event=event, impact=impact)
    verification_needed = _verification_needed(event=event, impact=impact, rule=rule)
    return GoldEventMainlineLink(
        event_id=str(event.get("event_id") or ""),
        mainline_ids=rule.mainline_ids,
        primary_mainline=rule.primary_mainline,
        transmission_path_ids=rule.transmission_path_ids,
        direction_by_asset=_direction_by_asset(event=event, impact=impact),
        pricing_status=_nullable_str(impact.get("pricing_status") or event.get("pricing_status")),
        verification_status=_nullable_str(event.get("verification_status")),
        market_validation_ref=_market_validation_ref(event),
        bullish_drivers=rule.bullish_drivers,
        bearish_drivers=rule.bearish_drivers,
        dominant_driver=rule.dominant_driver,
        verification_needed=verification_needed,
        verification_chain=_verification_chain(event=event, verification_needed=verification_needed),
        changed_dominant_theme=bool(event.get("changed_dominant_theme") or False),
        source_refs=[dict(ref) for ref in event.get("source_refs") or [] if isinstance(ref, dict)],
    )


def _rule_for_event(*, event: dict[str, Any], impact: dict[str, Any]) -> GoldMainlineRule:
    event_type = str(event.get("event_type") or "market_news_candidate")
    impact_path = str(impact.get("impact_path") or event.get("impact_path") or "")
    gold_impact = str(impact.get("gold_impact") or event.get("direction") or "")

    if impact_path == "geo_risk_to_oil_to_inflation" or event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"}:
        return GoldMainlineRule(
            mainline_ids=["geopolitical_war_risk", "oil_prices", "real_rates_usd"],
            primary_mainline="geopolitical_war_risk",
            transmission_path_ids=["geopolitics_to_oil_to_rates", "haven_bid"],
            bullish_drivers=["safe_haven_bid"],
            bearish_drivers=["oil_inflation_rate_pressure", "usd_strength_pressure"],
            dominant_driver="oil_inflation_rate_pressure",
            verification_checks=["oil_price_reaction_needed", "real_rate_response_needed"],
        )
    if event_type in {"fed_hawkish", "fed_dovish", "fomc_statement", "fed_speech", "inflation_release", "labor_release", "pce_release", "gdp_release"}:
        return _rates_rule(gold_impact)
    if event_type == "energy_inventory_release":
        return GoldMainlineRule(
            mainline_ids=["oil_prices", "real_rates_usd"],
            primary_mainline="oil_prices",
            transmission_path_ids=["inflation_to_real_rates"],
            verification_checks=["oil_price_reaction_needed", "real_rate_response_needed"],
        )
    if event_type == "yen_intervention_risk":
        return GoldMainlineRule(
            mainline_ids=["real_rates_usd"],
            primary_mainline="real_rates_usd",
            transmission_path_ids=["usd_pressure"],
            verification_checks=["fx_market_confirmation_needed"],
        )
    if event_type == "gold_fund_flow":
        return GoldMainlineRule(
            mainline_ids=["etf_flows"],
            primary_mainline="etf_flows",
            transmission_path_ids=["capital_confirmation"],
            verification_checks=["flow_data_confirmation_needed"],
        )
    if event_type == "key_level_watchlist":
        return GoldMainlineRule(
            mainline_ids=["gold_technical_levels"],
            primary_mainline="gold_technical_levels",
            transmission_path_ids=["technical_confirmation"],
            verification_checks=["price_level_confirmation_needed"],
        )
    if event_type in {"central_bank_gold_buying", "reserve_reallocation", "dedollarization_reserve_shift"}:
        return GoldMainlineRule(
            mainline_ids=["central_bank_gold"],
            primary_mainline="central_bank_gold",
            transmission_path_ids=["reserve_reallocation"],
            verification_checks=["official_reserve_data_needed"],
        )
    if event_type in {"china_gold_demand", "asia_gold_demand", "india_gold_demand", "shanghai_gold_premium"}:
        return GoldMainlineRule(
            mainline_ids=["china_asia_demand"],
            primary_mainline="china_asia_demand",
            transmission_path_ids=["asia_demand"],
        )
    if event_type in {"institutional_gold_forecast", "positioning_sentiment", "gold_market_narrative"}:
        return GoldMainlineRule(
            mainline_ids=["institutional_sentiment"],
            primary_mainline="institutional_sentiment",
            transmission_path_ids=["capital_confirmation"],
            verification_checks=["positioning_confirmation_needed"],
        )
    if event_type == "macro_watchlist":
        return GoldMainlineRule(
            mainline_ids=["fed_policy_path", "real_rates_usd", "institutional_sentiment"],
            primary_mainline="real_rates_usd",
            transmission_path_ids=["inflation_to_real_rates", "usd_pressure"],
            verification_checks=["macro_data_confirmation_needed"],
        )
    return GoldMainlineRule(
        mainline_ids=["institutional_sentiment"],
        primary_mainline="institutional_sentiment",
        transmission_path_ids=["capital_confirmation"],
        verification_checks=["multi_source_confirmation_needed"],
    )


def _rates_rule(gold_impact: str) -> GoldMainlineRule:
    normalized = _normalize_gold_direction(gold_impact)
    if normalized == "bullish":
        return GoldMainlineRule(
            mainline_ids=["fed_policy_path", "real_rates_usd"],
            primary_mainline="fed_policy_path",
            transmission_path_ids=["inflation_to_real_rates", "usd_pressure"],
            bullish_drivers=["rate_cut_expectation_support", "usd_weakness_support"],
            dominant_driver="rate_cut_expectation_support",
            verification_checks=["real_rate_response_needed"],
        )
    if normalized == "bearish":
        return GoldMainlineRule(
            mainline_ids=["fed_policy_path", "real_rates_usd"],
            primary_mainline="fed_policy_path",
            transmission_path_ids=["inflation_to_real_rates", "usd_pressure"],
            bearish_drivers=["higher_for_longer_rate_pressure", "usd_strength_pressure"],
            dominant_driver="higher_for_longer_rate_pressure",
            verification_checks=["real_rate_response_needed"],
        )
    return GoldMainlineRule(
        mainline_ids=["fed_policy_path", "real_rates_usd"],
        primary_mainline="fed_policy_path",
        transmission_path_ids=["inflation_to_real_rates", "usd_pressure"],
        verification_checks=["official_release_needed", "real_rate_response_needed"],
    )


def _aggregate_mainlines(*, links: list[GoldEventMainlineLink], events: list[dict[str, Any]]) -> list[GoldMainlineSummary]:
    event_by_id = {str(event.get("event_id") or ""): event for event in events}
    rows: list[GoldMainlineSummary] = []
    for rank, mainline_id in enumerate(MAINLINE_ORDER, 1):
        meta = MAINLINE_META[mainline_id]
        related_links = [link for link in links if mainline_id in link.mainline_ids]
        event_ids = [link.event_id for link in related_links if link.event_id]
        source_refs = _merge_source_refs(link.source_refs for link in related_links)
        verification_needed = _unique(item for link in related_links for item in link.verification_needed)
        missing_data = _missing_data(mainline_id=mainline_id, verification_needed=verification_needed, source_refs=source_refs)
        confidence_values = [
            float(event_by_id[event_id].get("confidence"))
            for event_id in event_ids
            if event_id in event_by_id and event_by_id[event_id].get("confidence") is not None
        ]
        coverage_status = "covered" if related_links else "missing"
        verification_status = _aggregate_verification_status([link.verification_status for link in related_links])
        direction = _aggregate_direction([link.direction_by_asset.get("XAUUSD", "unknown") for link in related_links])
        direction_score = _direction_score(direction=direction, links=related_links)
        impact_score = _impact_score(related_links=related_links)
        confidence_score = _confidence_score(confidence_values)
        freshness_score = _freshness_score(
            coverage_status=coverage_status,
            verification_status=verification_status,
            missing_data=missing_data,
            source_refs=source_refs,
        )
        theme_score = (
            abs(direction_score) * impact_score * confidence_score * freshness_score
            if related_links
            else None
        )
        score = float(theme_score) if theme_score is not None else None
        rows.append(
            GoldMainlineSummary(
                mainline_id=mainline_id,
                mainline=mainline_id,
                label=str(meta["label"]),
                pricing_layer=str(meta["pricing_layer"]),
                rank=rank,
                score=score,
                theme_score=theme_score,
                direction_score=direction_score,
                impact_score=impact_score,
                confidence_score=confidence_score,
                freshness_score=freshness_score,
                direction=direction,
                confidence=round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else None,
                verification_status=verification_status,
                coverage_status=coverage_status,
                trend="unknown",
                dominant=False,
                summary=str(meta["summary"]),
                bullish_drivers=_unique(item for link in related_links for item in link.bullish_drivers),
                bearish_drivers=_unique(item for link in related_links for item in link.bearish_drivers),
                event_ids=event_ids,
                related_event_ids=event_ids,
                source_refs=source_refs,
                evidence_count=len(source_refs),
                missing_data=missing_data,
                freshness=_freshness(coverage_status=coverage_status, missing_data=missing_data, source_refs=source_refs),
                impact_strength=_impact_strength(score=score, direction=direction, coverage_status=coverage_status),
                verification_needed=verification_needed,
            )
        )

    covered_rows = sorted(
        [row for row in rows if row.coverage_status == "covered"],
        key=lambda row: (-(row.score or 0), row.rank),
    )
    dominant_ids = {row.mainline_id for row in covered_rows[:2]}
    return [
        GoldMainlineSummary(**{**row.to_dict(), "dominant": row.mainline_id in dominant_ids})
        for row in rows
    ]


def _direction_by_asset(*, event: dict[str, Any], impact: dict[str, Any]) -> dict[str, str]:
    gold_direction = _normalize_gold_direction(impact.get("gold_impact") or event.get("direction"))
    directions: dict[str, str] = {"XAUUSD": gold_direction}
    dollar_direction = _normalize_factor_direction(impact.get("dollar_impact"))
    yield_direction = _normalize_factor_direction(impact.get("yield_impact"))
    oil_direction = _normalize_factor_direction(impact.get("oil_impact"))
    if oil_direction != "unknown":
        directions["WTI"] = oil_direction
        directions["Brent"] = oil_direction
    if dollar_direction != "unknown":
        directions["DXY"] = dollar_direction
    if yield_direction != "unknown":
        directions["US10Y"] = yield_direction
    return directions


def _verification_needed(*, event: dict[str, Any], impact: dict[str, Any], rule: GoldMainlineRule) -> list[str]:
    checks: list[str] = []
    verification_status = str(event.get("verification_status") or "")
    if verification_status not in {"official_confirmed", "multi_source"}:
        checks.append("multi_source_confirmation_needed")
    pricing_status = str(impact.get("pricing_status") or event.get("pricing_status") or "")
    if pricing_status == "scheduled":
        checks.append("official_release_needed")
    for check in rule.verification_checks:
        if check not in checks:
            checks.append(check)
    if verification_status == "official_confirmed":
        checks = [check for check in checks if check != "multi_source_confirmation_needed"]
    return checks


def _verification_chain(*, event: dict[str, Any], verification_needed: list[str]) -> dict[str, Any]:
    source_refs = [dict(ref) for ref in event.get("source_refs") or [] if isinstance(ref, dict)]
    verification_status = str(event.get("verification_status") or "unverified")
    source_count = _event_source_count(event=event, source_refs=source_refs)
    official_sources = [ref for ref in source_refs if _is_official_source_ref(ref)]
    independent_sources = _independent_source_keys(source_refs)
    has_official_source = verification_status == "official_confirmed" or bool(official_sources)
    has_multi_source = verification_status == "multi_source" or len(independent_sources) >= 2
    missing_confirmations = list(verification_needed)
    if has_official_source or has_multi_source:
        missing_confirmations = [
            item for item in missing_confirmations if item != "multi_source_confirmation_needed"
        ]
    if verification_status == "official_confirmed" or has_official_source:
        required_status = "not_required"
    elif has_multi_source:
        required_status = "not_required"
    else:
        required_status = "needs_multi_source"
    return {
        "status": verification_status,
        "required_status": required_status,
        "source_count": source_count,
        "official_source_count": len(official_sources) if official_sources else (1 if verification_status == "official_confirmed" else 0),
        "independent_source_count": max(len(independent_sources), source_count if verification_status == "multi_source" else 0),
        "has_official_source": has_official_source,
        "has_multi_source": has_multi_source,
        "missing_confirmations": missing_confirmations,
        "source_refs": source_refs,
    }


def _event_source_count(*, event: dict[str, Any], source_refs: list[dict[str, Any]]) -> int:
    try:
        explicit_count = int(event.get("source_count") or 0)
    except (TypeError, ValueError):
        explicit_count = 0
    return max(explicit_count, len(source_refs))


def _is_official_source_ref(ref: dict[str, Any]) -> bool:
    source_type = str(ref.get("source_type") or ref.get("provider_role") or "").lower()
    if source_type == "official":
        return True
    source_text = " ".join(str(ref.get(key) or "") for key in ("source", "provider", "domain")).lower()
    official_markers = ("fed", "bls", "bea", "eia", "treasury", "fred", "cme", "fomc")
    return any(marker in source_text for marker in official_markers)


def _independent_source_keys(source_refs: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for ref in source_refs:
        key = str(ref.get("source") or ref.get("provider") or ref.get("domain") or ref.get("source_ref") or "").strip()
        if key:
            keys.add(_source_family_key(key))
    return keys


def _source_family_key(value: str) -> str:
    normalized = value.lower()
    if "jin10" in normalized or "金十" in normalized:
        return "jin10"
    if "reuters" in normalized:
        return "reuters"
    if "gdelt" in normalized:
        return "gdelt"
    if "google" in normalized:
        return "google_news"
    if "fed" in normalized or "fomc" in normalized:
        return "fed"
    return normalized


def _missing_data(*, mainline_id: str, verification_needed: list[str], source_refs: list[dict[str, Any]]) -> list[str]:
    if not verification_needed and source_refs:
        return []
    missing = [_source for item in verification_needed if (_source := VERIFICATION_SOURCE_MAP.get(item, item))]
    if not source_refs and not missing:
        missing = list(MAINLINE_META[mainline_id]["missing_data"])
    if not source_refs and mainline_id in {"fed_policy_path", "geopolitical_war_risk"} and "news_sources" not in missing:
        missing.append("news_sources")
    return _unique(missing)


def _normalize_gold_direction(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"bullish", "bullish_gold", "gold_bullish", "利多黄金"}:
        return "bullish"
    if normalized in {"bearish", "bearish_gold", "gold_bearish", "利空黄金"}:
        return "bearish"
    if normalized in {"mixed", "混合"}:
        return "mixed"
    if normalized in {"neutral", "neutral_gold", ""}:
        return "neutral"
    return "unknown"


def _normalize_factor_direction(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"dollar_strength", "yield_up", "oil_up", "bullish", "up"}:
        return "bullish"
    if normalized in {"dollar_weakness", "yield_down", "oil_down", "bearish", "down"}:
        return "bearish"
    if normalized in {"neutral", "mixed"}:
        return normalized
    return "unknown"


def _aggregate_direction(directions: list[str]) -> str:
    values = [item for item in directions if item and item != "unknown"]
    if not values:
        return "unknown"
    if len(set(values)) == 1:
        return values[0]
    return "mixed"


def _direction_score(*, direction: str, links: list[GoldEventMainlineLink]) -> int:
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    if direction == "mixed":
        bullish = sum(1 for link in links if "safe_haven_bid" in link.bullish_drivers or "rate_cut_expectation_support" in link.bullish_drivers)
        bearish = sum(1 for link in links if link.bearish_drivers)
        if bullish > bearish:
            return 1
        if bearish > bullish:
            return -1
        return 0
    return 0


def _impact_score(*, related_links: list[GoldEventMainlineLink]) -> int:
    if not related_links:
        return 1
    has_chain = any("geopolitics_to_oil_to_rates" in link.transmission_path_ids for link in related_links)
    has_primary_rate = any(link.primary_mainline in {"fed_policy_path", "real_rates_usd"} for link in related_links)
    has_driver_split = any(link.bullish_drivers and link.bearish_drivers for link in related_links)
    if has_chain or has_primary_rate or has_driver_split:
        return 3
    if len(related_links) >= 2:
        return 2
    return 2


def _confidence_score(confidence_values: list[float]) -> int:
    if not confidence_values:
        return 1
    confidence = sum(confidence_values) / len(confidence_values)
    if confidence >= 0.72:
        return 3
    if confidence >= 0.45:
        return 2
    return 1


def _freshness_score(
    *,
    coverage_status: str,
    verification_status: str,
    missing_data: list[str],
    source_refs: list[dict[str, Any]],
) -> int:
    if coverage_status == "missing" or not source_refs:
        return 1
    if verification_status in {"official_confirmed", "multi_source"} and not missing_data:
        return 3
    return 2


def _aggregate_verification_status(statuses: list[str | None]) -> str:
    values = {str(status or "") for status in statuses}
    if "official_confirmed" in values:
        return "official_confirmed"
    if "multi_source" in values:
        return "multi_source"
    if "single_source" in values:
        return "single_source"
    if "unverified" in values:
        return "unverified"
    return "pending"


def _bundle_status(links: list[GoldEventMainlineLink]) -> str:
    if not links:
        return "unavailable"
    if all(link.verification_status == "official_confirmed" for link in links):
        return "available"
    return "partial"


def _freshness(*, coverage_status: str, missing_data: list[str], source_refs: list[dict[str, Any]]) -> str:
    if coverage_status == "missing" or not source_refs:
        return "stale"
    if missing_data:
        return "partial"
    return "fresh"


def _impact_strength(*, score: float | None, direction: str, coverage_status: str) -> str:
    if coverage_status == "missing":
        return "none"
    numeric_score = float(score or 0.0)
    if numeric_score >= 18:
        return "high" if direction != "mixed" else "medium"
    if numeric_score >= 8:
        return "medium"
    return "low"


def _market_validation_ref(event: dict[str, Any]) -> str | None:
    direct = _nullable_str(event.get("market_validation_ref"))
    if direct:
        return direct
    market_validation = event.get("market_validation")
    if isinstance(market_validation, dict):
        return _nullable_str(market_validation.get("ref") or market_validation.get("artifact_ref"))
    return None


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _merge_source_refs(ref_groups: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in ref_groups:
        for ref in group or []:
            if not isinstance(ref, dict):
                continue
            key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            refs.append(dict(ref))
    return refs


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
