from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apps.features.news.gold_event_mainlines import MAINLINE_META, MAINLINE_ORDER

SCHEMA_VERSION = "gold-macro-overview-v1"

DRIVER_PRIORITY = [
    "higher_for_longer_rate_pressure",
    "oil_inflation_rate_pressure",
    "usd_strength_pressure",
    "rate_cut_expectation_support",
    "safe_haven_bid",
    "usd_weakness_support",
]


@dataclass(frozen=True)
class DriverConflict:
    status: str
    dominant_driver: str | None
    bullish_drivers: list[str]
    bearish_drivers: list[str]
    net_effect: str
    explanation: str
    verification_needed: list[str]
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransmissionChainStep:
    id: str
    label: str
    status: str = "partial"
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransmissionChainSummary:
    path_id: str
    label: str
    status: str
    conclusion_code: str
    conclusion_label: str
    net_effect: str
    dominant_driver: str | None
    summary: str
    steps: list[TransmissionChainStep]
    source_refs: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "steps": [item.to_dict() for item in self.steps],
        }


@dataclass(frozen=True)
class VerificationItem:
    id: str
    label: str
    status: str
    mainline_id: str | None
    event_id: str | None
    required_source: str | None
    reason: str | None
    source_refs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MainlineRequirement:
    mainline_id: str
    label: str
    pricing_layer: str
    asset_principle: str
    analysis_chain: list[str]
    required_sources: list[str]
    required_fields: list[str]
    developed_sources: list[str]
    missing_sources: list[str]
    missing_fields: list[str]
    readiness_status: str
    page_targets: list[str]
    verification_requirements: list[str]
    development_gaps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisReadiness:
    status: str
    ready_count: int
    partial_count: int
    missing_count: int
    total_count: int
    coverage_ratio: float
    next_gaps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PriorityDecision:
    regime: str
    reason: str
    mainline_ids: list[str]


@dataclass(frozen=True)
class GoldMacroOverview:
    status: str
    asset: str
    as_of: str | None
    phase: str
    dominant_mainline: str | None
    priority_regime: str
    priority_reason: str
    net_bias: str
    risk_score: int | None
    one_line_conclusion: str
    theme_rankings: list[dict[str, Any]]
    driver_conflict: DriverConflict | None
    war_oil_rate_chain: TransmissionChainSummary | None
    verification_matrix: list[VerificationItem]
    mainline_requirements: list[MainlineRequirement]
    analysis_readiness: AnalysisReadiness
    architecture_gaps: list[str]
    key_events: list[str]
    source_refs: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "asset": self.asset,
            "as_of": self.as_of,
            "phase": self.phase,
            "dominant_mainline": self.dominant_mainline,
            "priority_regime": self.priority_regime,
            "priority_reason": self.priority_reason,
            "net_bias": self.net_bias,
            "risk_score": self.risk_score,
            "one_line_conclusion": self.one_line_conclusion,
            "theme_rankings": self.theme_rankings,
            "driver_conflict": self.driver_conflict.to_dict() if self.driver_conflict else None,
            "war_oil_rate_chain": self.war_oil_rate_chain.to_dict() if self.war_oil_rate_chain else None,
            "verification_matrix": [item.to_dict() for item in self.verification_matrix],
            "mainline_requirements": [item.to_dict() for item in self.mainline_requirements],
            "analysis_readiness": self.analysis_readiness.to_dict(),
            "architecture_gaps": self.architecture_gaps,
            "key_events": self.key_events,
            "source_refs": self.source_refs,
            "artifact_refs": self.artifact_refs,
            "warnings": self.warnings,
        }


def build_gold_macro_overview(
    gold_event_mainlines: Any,
    *,
    macro_context: Any | None = None,
    market_context: Any | None = None,
    oil_context: Any | None = None,
    flow_context: Any | None = None,
    reserve_context: Any | None = None,
    asia_context: Any | None = None,
    positioning_context: Any | None = None,
    policy_context: Any | None = None,
    geopolitical_context: Any | None = None,
) -> GoldMacroOverview:
    payload = _dict(gold_event_mainlines)
    links = [_dict(item) for item in payload.get("event_links") or []]
    mainlines = [_dict(item) for item in payload.get("mainlines") or []]
    asset = str(payload.get("asset") or "XAUUSD")
    as_of = str(payload.get("as_of")) if payload.get("as_of") else None
    source_refs = _merge_source_refs(
        [
            payload.get("source_refs") or [],
            *(link.get("source_refs") or [] for link in links),
        ]
    )
    artifact_refs = [dict(ref) for ref in payload.get("artifact_refs") or [] if isinstance(ref, dict)]

    if not mainlines:
        mainlines = _missing_mainline_rows()

    mainlines = _apply_context_features(
        mainlines=mainlines,
        macro_context=_dict(macro_context),
        market_context=_dict(market_context),
        oil_context=_dict(oil_context),
        flow_context=_dict(flow_context),
        reserve_context=_dict(reserve_context),
        asia_context=_dict(asia_context),
        positioning_context=_dict(positioning_context),
        policy_context=_dict(policy_context),
        geopolitical_context=_dict(geopolitical_context),
    )
    theme_rankings = _theme_rankings(mainlines)
    covered_rows = [row for row in theme_rankings if row.get("coverage_status") == "covered"]
    net_bias = _net_bias(links)
    conflict = _driver_conflict(links=links, net_bias=net_bias, source_refs=source_refs)
    chain = _war_oil_rate_chain(
        links,
        macro_context=_dict(macro_context),
        oil_context=_dict(oil_context),
    )
    priority_decision = _priority_decision(theme_rankings=theme_rankings, links=links, chain=chain)
    dominant_mainline = _dominant_mainline(covered_rows, priority_mainline_ids=priority_decision.mainline_ids)
    verification_matrix = _verification_matrix(links=links, rankings=theme_rankings)
    mainline_requirements = _mainline_requirements(rankings=theme_rankings, verification_matrix=verification_matrix)
    analysis_readiness = _analysis_readiness(mainline_requirements)
    architecture_gaps = _architecture_gaps(mainline_requirements)
    key_events = [str(link.get("event_id")) for link in links if link.get("event_id")]
    status = _overview_status(payload=payload, covered_rows=covered_rows)
    return GoldMacroOverview(
        status=status,
        asset=asset,
        as_of=as_of,
        phase=_phase_for_bias(net_bias=net_bias, links=links),
        dominant_mainline=dominant_mainline,
        priority_regime=priority_decision.regime,
        priority_reason=priority_decision.reason,
        net_bias=net_bias,
        risk_score=_risk_score(net_bias=net_bias, links=links, verification_matrix=verification_matrix),
        one_line_conclusion=_one_line_conclusion(dominant_mainline=dominant_mainline, net_bias=net_bias, conflict=conflict),
        theme_rankings=theme_rankings,
        driver_conflict=conflict,
        war_oil_rate_chain=chain,
        verification_matrix=verification_matrix,
        mainline_requirements=mainline_requirements,
        analysis_readiness=analysis_readiness,
        architecture_gaps=architecture_gaps,
        key_events=key_events,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        warnings=[str(item) for item in payload.get("warnings") or []],
    )


def archive_gold_macro_overview(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    overview: GoldMacroOverview,
    input_snapshot_ids: dict[str, Any] | None = None,
) -> str:
    target = storage_root / "analysis" / "gold_mainlines" / retrieved_date / run_id / "gold_macro_overview.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "input_snapshot_ids": dict(input_snapshot_ids or {}),
        **overview.to_dict(),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _theme_rankings(mainlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("mainline_id") or item.get("mainline")): dict(item) for item in mainlines}
    rows: list[dict[str, Any]] = []
    for idx, mainline_id in enumerate(MAINLINE_ORDER, 1):
        row = dict(by_id.get(mainline_id) or {})
        meta = MAINLINE_META[mainline_id]
        row.setdefault("mainline_id", mainline_id)
        row.setdefault("mainline", mainline_id)
        row.setdefault("label", meta["label"])
        row.setdefault("pricing_layer", meta["pricing_layer"])
        row.setdefault("rank", idx)
        row.setdefault("coverage_status", "missing")
        row.setdefault("score", None)
        row.setdefault("theme_score", row.get("score"))
        row.setdefault("direction_score", _direction_score_from_direction(str(row.get("direction") or "unknown")))
        row.setdefault("impact_score", 1 if row.get("coverage_status") == "missing" else 2)
        row.setdefault("confidence_score", _confidence_bucket(row.get("confidence")))
        row.setdefault("freshness_score", 1)
        row.setdefault("direction", "unknown")
        row.setdefault("confidence", None)
        row.setdefault("verification_status", "pending")
        row.setdefault("trend", "unknown")
        row.setdefault("dominant", False)
        row.setdefault("summary", meta["summary"])
        row.setdefault("bullish_drivers", [])
        row.setdefault("bearish_drivers", [])
        row.setdefault("event_ids", [])
        row.setdefault("related_event_ids", row.get("event_ids") or [])
        row.setdefault("source_refs", [])
        row.setdefault("evidence_count", len(row.get("source_refs") or []))
        row.setdefault("missing_data", meta["missing_data"])
        row.setdefault("feature_fields", {})
        row.setdefault("freshness", "stale")
        row.setdefault("impact_strength", "none")
        row.setdefault("verification_needed", [])
        rows.append(row)
    return rows


def _missing_mainline_rows() -> list[dict[str, Any]]:
    return [{"mainline_id": mainline_id} for mainline_id in MAINLINE_ORDER]


def _apply_context_features(
    *,
    mainlines: list[dict[str, Any]],
    macro_context: dict[str, Any],
    market_context: dict[str, Any],
    oil_context: dict[str, Any],
    flow_context: dict[str, Any],
    reserve_context: dict[str, Any],
    asia_context: dict[str, Any],
    positioning_context: dict[str, Any],
    policy_context: dict[str, Any],
    geopolitical_context: dict[str, Any],
) -> list[dict[str, Any]]:
    feature_updates = {
        "fed_policy_path": _fed_policy_features(policy_context=policy_context),
        "real_rates_usd": _real_rates_usd_features(macro_context),
        "oil_prices": _oil_price_features(oil_context=oil_context, macro_context=macro_context),
        "geopolitical_war_risk": _geopolitical_war_risk_features(geopolitical_context=geopolitical_context),
        "etf_flows": _etf_flow_features(flow_context=flow_context),
        "central_bank_gold": _central_bank_gold_features(reserve_context=reserve_context),
        "china_asia_demand": _china_asia_demand_features(asia_context=asia_context),
        "institutional_sentiment": _institutional_sentiment_features(positioning_context=positioning_context),
        "gold_technical_levels": _technical_level_features(market_context),
    }
    rows: list[dict[str, Any]] = []
    applied: set[str] = set()
    for item in mainlines:
        row = dict(item)
        mainline_id = str(row.get("mainline_id") or row.get("mainline") or "")
        update = feature_updates.get(mainline_id)
        if update:
            _merge_context_update(row, update)
            applied.add(mainline_id)
        rows.append(row)
    for mainline_id, update in feature_updates.items():
        if update and mainline_id not in applied:
            row = {"mainline_id": mainline_id, "mainline": mainline_id}
            _merge_context_update(row, update)
            rows.append(row)
    return rows


def _merge_context_update(row: dict[str, Any], update: dict[str, Any]) -> None:
    feature_fields = dict(row.get("feature_fields") or {})
    feature_fields.update(update.get("feature_fields") or {})
    row["feature_fields"] = feature_fields
    source_refs = _merge_source_refs([row.get("source_refs") or [], update.get("source_refs") or []])
    if source_refs:
        row["source_refs"] = source_refs
        row["evidence_count"] = len(source_refs)
        if row.get("coverage_status") in {None, "", "missing"}:
            row["coverage_status"] = "covered"
    if update.get("direction") and str(row.get("direction") or "unknown") in {"", "unknown", "neutral"}:
        row["direction"] = update["direction"]
        row["direction_score"] = _direction_score_from_direction(str(update["direction"]))
    if update.get("summary"):
        row["summary"] = update["summary"]
    if update.get("missing_data") is not None:
        row["missing_data"] = update["missing_data"]
    if update.get("verification_status"):
        row["verification_status"] = update["verification_status"]
    if update.get("freshness"):
        row["freshness"] = update["freshness"]


def _real_rates_usd_features(macro_context: dict[str, Any]) -> dict[str, Any] | None:
    indicators = _dict(macro_context.get("indicators"))
    real_10y = _indicator(indicators, "REAL_10Y", "DFII10")
    dxy = _indicator(indicators, "DXY")
    us10y = _indicator(indicators, "US10Y", "DGS10")
    breakeven = _indicator(indicators, "BREAKEVEN_10Y", "T10YIE")
    short_curve = _indicator(indicators, "YIELD_SPREAD_2Y_3M")
    if not any([real_10y, dxy, us10y, breakeven, short_curve]):
        return None
    real_rate_level = _number(real_10y.get("value") if real_10y else None)
    real_rate_change = _number(real_10y.get("weekly_change") if real_10y else None)
    real_rate_monthly_change = _number(real_10y.get("monthly_change") if real_10y else None)
    dxy_change = _number(dxy.get("weekly_change") if dxy else None)
    dxy_monthly_change = _number(dxy.get("monthly_change") if dxy else None)
    nominal_yield_change = _number(us10y.get("weekly_change") if us10y else None)
    nominal_yield_monthly_change = _number(us10y.get("monthly_change") if us10y else None)
    breakeven_change = _number(breakeven.get("weekly_change") if breakeven else None)
    breakeven_monthly_change = _number(breakeven.get("monthly_change") if breakeven else None)
    short_curve_level = _number(short_curve.get("value") if short_curve else None)
    short_curve_change = _number(short_curve.get("weekly_change") if short_curve else None)
    short_curve_monthly_change = _number(short_curve.get("monthly_change") if short_curve else None)
    real_rate_resolved_change, real_rate_basis = _resolved_change(weekly=real_rate_change, monthly=real_rate_monthly_change)
    dxy_resolved_change, dxy_basis = _resolved_change(weekly=dxy_change, monthly=dxy_monthly_change)
    nominal_yield_resolved_change, nominal_yield_basis = _resolved_change(
        weekly=nominal_yield_change,
        monthly=nominal_yield_monthly_change,
    )
    breakeven_resolved_change, breakeven_basis = _resolved_change(
        weekly=breakeven_change,
        monthly=breakeven_monthly_change,
    )
    short_curve_resolved_change, short_curve_basis = _resolved_change(
        weekly=short_curve_change,
        monthly=short_curve_monthly_change,
    )
    short_curve_trend = _trend_from_change(short_curve_resolved_change)
    fields = {
        "real_rate_level": real_rate_level,
        "real_rate_weekly_change": real_rate_change,
        "real_rate_monthly_change": real_rate_monthly_change,
        "real_rate_trend": _trend_from_change(real_rate_resolved_change),
        "real_rate_trend_basis": real_rate_basis,
        "dxy_trend": _trend_from_change(dxy_resolved_change),
        "dxy_weekly_change": dxy_change,
        "dxy_monthly_change": dxy_monthly_change,
        "dxy_trend_basis": dxy_basis,
        "nominal_yield_level": _number(us10y.get("value") if us10y else None),
        "nominal_yield_weekly_change": nominal_yield_change,
        "nominal_yield_monthly_change": nominal_yield_monthly_change,
        "nominal_yield_trend": _trend_from_change(nominal_yield_resolved_change),
        "nominal_yield_trend_basis": nominal_yield_basis,
        "nominal_yield_pressure": _yield_pressure(nominal_yield_resolved_change),
        "dollar_liquidity_pressure": _dollar_pressure(dxy_resolved_change),
        "us10y_level": _number(us10y.get("value") if us10y else None),
        "breakeven_10y_level": _number(breakeven.get("value") if breakeven else None),
        "breakeven_10y_weekly_change": breakeven_change,
        "breakeven_10y_monthly_change": breakeven_monthly_change,
        "breakeven_10y_trend": _trend_from_change(breakeven_resolved_change),
        "breakeven_10y_trend_basis": breakeven_basis,
        "yield_spread_2y_3m_level": short_curve_level,
        "yield_spread_2y_3m_weekly_change": short_curve_change,
        "yield_spread_2y_3m_monthly_change": short_curve_monthly_change,
        "yield_spread_2y_3m_trend": short_curve_trend,
        "yield_spread_2y_3m_trend_basis": short_curve_basis,
        "yield_curve_2y3m_signal": _yield_curve_2y3m_signal(
            level=short_curve_level,
            trend=short_curve_trend,
        ),
        "yield_curve_2y3m_market_meaning": _yield_curve_2y3m_market_meaning(
            level=short_curve_level,
            trend=short_curve_trend,
        ),
    }
    available_sources = []
    if real_rate_level is not None:
        available_sources.append("real_rates")
    if fields["breakeven_10y_level"] is not None:
        available_sources.append("inflation_expectations")
    if _number(dxy.get("value") if dxy else None) is not None:
        available_sources.append("dxy")
    if short_curve_level is not None:
        available_sources.append("yield_curve")
    direction = (
        "bearish"
        if fields["real_rate_trend"] == "rising" or fields["dxy_trend"] == "rising"
        else "bullish"
        if (
            fields["real_rate_trend"] == "falling"
            and fields["dxy_trend"] != "rising"
            and fields["yield_curve_2y3m_signal"] != "inversion_deepening_hard_landing_risk"
        )
        else "neutral"
    )
    return {
        "feature_fields": fields,
        "source_refs": _macro_source_refs(macro_context=macro_context, symbols=["REAL_10Y", "DFII10", "DXY", "US10Y", "DGS10", "BREAKEVEN_10Y", "T10YIE", "YIELD_SPREAD_2Y_3M", "DGS2", "DGS3MO"]),
        "missing_data": [item for item in ["real_rates", "inflation_expectations", "dxy", "yield_curve"] if item not in available_sources],
        "verification_status": (
            "official_confirmed"
            if "real_rates" in available_sources
            and "dxy" in available_sources
            and "yield_curve" in available_sources
            and real_rate_change is not None
            and dxy_change is not None
            and short_curve_change is not None
            else "multi_source"
        ),
        "freshness": "fresh",
        "direction": direction,
        "summary": "实际利率、名义利率、通胀预期、DXY 与 2Y-3M 利差已由宏观快照接入；2Y-3M 用于确认短端政策拐点定价和黄金低点窗口。",
    }


def _oil_price_features(*, oil_context: dict[str, Any], macro_context: dict[str, Any]) -> dict[str, Any] | None:
    brent_price = _number(oil_context.get("brent_price"))
    wti_price = _number(oil_context.get("wti_price"))
    brent_weekly_change = _number(oil_context.get("brent_weekly_change"))
    brent_monthly_change = _number(oil_context.get("brent_monthly_change"))
    wti_weekly_change = _number(oil_context.get("wti_weekly_change"))
    wti_monthly_change = _number(oil_context.get("wti_monthly_change"))
    inventory_weekly_change = _number(oil_context.get("inventory_weekly_change"))
    inventory_monthly_change = _number(oil_context.get("inventory_monthly_change"))
    if not any(
        value is not None
        for value in [
            brent_price,
            wti_price,
            brent_weekly_change,
            brent_monthly_change,
            wti_weekly_change,
            wti_monthly_change,
            inventory_weekly_change,
            inventory_monthly_change,
        ]
    ):
        return None

    brent_change, brent_basis = _resolved_change(weekly=brent_weekly_change, monthly=brent_monthly_change)
    wti_change, wti_basis = _resolved_change(weekly=wti_weekly_change, monthly=wti_monthly_change)
    oil_change, oil_basis = _resolved_change(
        weekly=_average_changes(brent_weekly_change, wti_weekly_change),
        monthly=_average_changes(brent_monthly_change, wti_monthly_change),
    )
    inventory_change, inventory_basis = _resolved_change(
        weekly=inventory_weekly_change,
        monthly=inventory_monthly_change,
    )
    inflation_change = _macro_indicator_change(macro_context=macro_context, symbol="BREAKEVEN_10Y")
    real_rate_change = _macro_indicator_change(macro_context=macro_context, symbol="REAL_10Y")
    nominal_yield_change = _macro_indicator_change(macro_context=macro_context, symbol="US10Y")
    brent_wti_spread = _spread(brent_price, wti_price)
    oil_price_trend = _trend_from_change(oil_change)
    oil_supply_shock = _oil_supply_shock(inventory_change)
    energy_inflation_risk = _energy_inflation_risk(
        oil_price_trend=oil_price_trend,
        oil_supply_shock=oil_supply_shock,
        inflation_change=inflation_change,
    )
    oil_to_fed_pressure = _oil_to_fed_pressure(
        oil_price_trend=oil_price_trend,
        real_rate_change=real_rate_change,
        nominal_yield_change=nominal_yield_change,
    )
    missing_data: list[str] = []
    if brent_change is None and wti_change is None:
        missing_data.append("oil_price")
    if inventory_change is None:
        missing_data.append("energy_inventory")
    if _macro_indicator_level(macro_context=macro_context, symbol="BREAKEVEN_10Y") is None:
        missing_data.append("inflation_expectations")
    fields = {
        "brent_price": brent_price,
        "wti_price": wti_price,
        "brent_weekly_change": brent_weekly_change,
        "wti_weekly_change": wti_weekly_change,
        "oil_price_trend": oil_price_trend,
        "oil_price_trend_basis": oil_basis,
        "brent_wti_spread": brent_wti_spread,
        "brent_wti_status": _brent_wti_status(brent_wti_spread),
        "oil_supply_shock": oil_supply_shock,
        "oil_supply_shock_basis": inventory_basis,
        "energy_inflation_risk": energy_inflation_risk,
        "oil_to_fed_pressure": oil_to_fed_pressure,
        "breakeven_10y_level": _macro_indicator_level(macro_context=macro_context, symbol="BREAKEVEN_10Y"),
        "inflation_expectation_change": inflation_change,
        "real_rate_change_context": real_rate_change,
        "nominal_yield_change_context": nominal_yield_change,
        "inventory_weekly_change": inventory_weekly_change,
        "inventory_monthly_change": inventory_monthly_change,
        "brent_trend_basis": brent_basis,
        "wti_trend_basis": wti_basis,
    }
    return {
        "feature_fields": fields,
        "source_refs": _oil_source_refs(oil_context=oil_context),
        "missing_data": missing_data,
        "verification_status": "official_confirmed" if not missing_data else "multi_source",
        "freshness": "fresh",
        "direction": "bearish" if oil_to_fed_pressure == "inflation_reacceleration_risk" else "bullish" if oil_to_fed_pressure == "safe_haven_offset" else "neutral",
        "summary": "Brent/WTI、库存与通胀预期已接入，用于判断战争风险是否转化为通胀和利率压力。",
    }


def _technical_level_features(market_context: dict[str, Any]) -> dict[str, Any] | None:
    price = _extract_gold_price(market_context)
    if price is None:
        return None
    fields = {
        "gold_spot_price": price,
        "level_3900_status": _level_status(price, 3900),
        "level_4000_status": _level_status(price, 4000),
        "level_4100_4120_status": _range_status(price, 4100, 4120),
        "level_4300_status": _level_status(price, 4300),
        "gold_phase": _technical_phase(price),
        "technical_confirmation": _technical_confirmation(price),
    }
    return {
        "feature_fields": fields,
        "source_refs": _market_source_refs(market_context=market_context),
        "missing_data": [],
        "verification_status": "multi_source" if _market_source_refs(market_context=market_context) else "single_source",
        "freshness": "fresh",
        "direction": _technical_direction(price),
        "summary": f"XAUUSD 当前价格 {price:g} 已接入，关键位 3900 / 4000 / 4100-4120 / 4300 可用于阶段确认。",
    }


def _fed_policy_features(*, policy_context: dict[str, Any]) -> dict[str, Any] | None:
    fed_policy_bias = _context_text(policy_context, "fed_policy_bias", "policy_bias", "fed_regime")
    fomc_tone = _context_text(policy_context, "fomc_tone", "fed_tone", "statement_tone")
    policy_surprise = _context_text(policy_context, "policy_surprise", "surprise_signal")
    rate_expectation_delta = _context_metric(
        policy_context,
        "rate_expectation_delta",
        "fed_funds_delta",
        "terminal_rate_delta",
    )
    cut_hike_probability = _context_metric(
        policy_context,
        "cut_hike_probability",
        "fed_watch_probability",
        "policy_probability",
    )
    treasury_2y_change = _context_metric(policy_context, "treasury_2y_change", "us02y_change", "two_year_change")
    treasury_10y_change = _context_metric(policy_context, "treasury_10y_change", "us10y_change", "ten_year_change")
    if all(
        value in {None, ""}
        for value in [
            fed_policy_bias,
            fomc_tone,
            policy_surprise,
            rate_expectation_delta,
            cut_hike_probability,
            treasury_2y_change,
            treasury_10y_change,
        ]
    ):
        return None

    missing_data: list[str] = []
    if fed_policy_bias in {None, ""} or fomc_tone in {None, ""}:
        missing_data.append("official_data")
    if rate_expectation_delta is None or cut_hike_probability is None:
        missing_data.append("fed_funds_futures")
    if treasury_2y_change is None or treasury_10y_change is None:
        missing_data.append("treasury_yields")

    return {
        "feature_fields": {
            "fed_policy_bias": fed_policy_bias,
            "rate_expectation_delta": rate_expectation_delta,
            "cut_hike_probability": cut_hike_probability,
            "fomc_tone": fomc_tone,
            "policy_surprise": policy_surprise,
            "treasury_2y_change": treasury_2y_change,
            "treasury_10y_change": treasury_10y_change,
        },
        "source_refs": _policy_source_refs(policy_context=policy_context),
        "missing_data": missing_data,
        "verification_status": "official_confirmed" if not missing_data else "multi_source",
        "freshness": "fresh",
        "direction": _fed_policy_direction(fed_policy_bias=fed_policy_bias, fomc_tone=fomc_tone),
        "summary": "FOMC 语气、利率预期和 2Y/10Y 利率变化已接入，用于确认黄金机会成本是否被重新定价。",
    }


def _etf_flow_features(*, flow_context: dict[str, Any]) -> dict[str, Any] | None:
    global_flow = _context_metric(
        flow_context,
        "global_etf_flow",
        "global_flow",
        "global_net_flow",
        "world_etf_flow",
    )
    north_america_flow = _context_metric(
        flow_context,
        "north_america_etf_flow",
        "north_america_flow",
        "north_america_gold_etf_flow",
        "na_etf_flow",
        "us_etf_flow",
    )
    asia_flow = _context_metric(
        flow_context,
        "asia_etf_flow",
        "asia_flow",
        "asia_gold_etf_flow",
        "apac_etf_flow",
    )
    if global_flow is None and north_america_flow is None and asia_flow is None:
        return None

    aggregate_flow = _average_changes(global_flow, north_america_flow, asia_flow)
    flow_trend = _flow_trend(aggregate_flow)
    confirmation_status = _flow_confirmation_status(
        global_flow=global_flow,
        north_america_flow=north_america_flow,
        asia_flow=asia_flow,
    )
    missing_data: list[str] = []
    if global_flow is None:
        missing_data.append("etf_flows")
    if north_america_flow is None or asia_flow is None:
        missing_data.append("regional_etf_flows")

    return {
        "feature_fields": {
            "global_etf_flow": global_flow,
            "north_america_etf_flow": north_america_flow,
            "asia_etf_flow": asia_flow,
            "etf_flow_trend": flow_trend,
            "flow_confirmation_status": confirmation_status,
            "aggregate_etf_flow": aggregate_flow,
        },
        "source_refs": _flow_source_refs(flow_context=flow_context),
        "missing_data": missing_data,
        "verification_status": (
            "official_confirmed"
            if not missing_data and confirmation_status in {"confirmed_inflow", "confirmed_outflow"}
            else "multi_source"
        ),
        "freshness": "fresh",
        "direction": _flow_direction(flow_trend=flow_trend, confirmation_status=confirmation_status),
        "summary": "全球、北美与亚洲黄金 ETF 流向已接入，用于确认宏观叙事是否转化为真实配置资金。",
    }


def _geopolitical_war_risk_features(*, geopolitical_context: dict[str, Any]) -> dict[str, Any] | None:
    geopolitical_status = _context_text(
        geopolitical_context,
        "geopolitical_status",
        "conflict_status",
        "war_status",
    )
    war_escalation_level = _context_text(
        geopolitical_context,
        "war_escalation_level",
        "escalation_level",
        "conflict_level",
    )
    energy_channel_risk = _context_text(
        geopolitical_context,
        "energy_channel_risk",
        "oil_channel_risk",
        "shipping_risk",
    )
    war_oil_rate_chain_status = _context_text(
        geopolitical_context,
        "war_oil_rate_chain_status",
        "chain_status",
    )
    safe_haven_score = _context_metric(
        geopolitical_context,
        "safe_haven_score",
        "haven_score",
        "risk_off_score",
    )
    vix_reaction = _context_text(geopolitical_context, "vix_reaction", "volatility_reaction")
    equity_reaction = _context_text(geopolitical_context, "equity_reaction", "equity_market_reaction")
    treasury_yield_reaction = _context_text(
        geopolitical_context,
        "treasury_yield_reaction",
        "rates_reaction",
        "treasury_reaction",
    )
    if all(
        value in {None, ""}
        for value in [
            geopolitical_status,
            war_escalation_level,
            energy_channel_risk,
            war_oil_rate_chain_status,
            safe_haven_score,
            vix_reaction,
            equity_reaction,
            treasury_yield_reaction,
        ]
    ):
        return None

    missing_data: list[str] = []
    if geopolitical_status in {None, ""} or war_escalation_level in {None, ""}:
        missing_data.append("news_sources")
    if vix_reaction in {None, ""}:
        missing_data.append("vix")
    if equity_reaction in {None, ""}:
        missing_data.append("equity_reaction")
    if treasury_yield_reaction in {None, ""}:
        missing_data.append("treasury_yields")
    if energy_channel_risk in {None, ""} or war_oil_rate_chain_status in {None, ""}:
        missing_data.append("oil_price")

    return {
        "feature_fields": {
            "geopolitical_status": geopolitical_status,
            "war_escalation_level": war_escalation_level,
            "safe_haven_score": safe_haven_score,
            "energy_channel_risk": energy_channel_risk,
            "war_oil_rate_chain_status": war_oil_rate_chain_status,
            "vix_reaction": vix_reaction,
            "equity_reaction": equity_reaction,
            "treasury_yield_reaction": treasury_yield_reaction,
        },
        "source_refs": _geopolitical_source_refs(geopolitical_context=geopolitical_context),
        "missing_data": missing_data,
        "verification_status": "multi_source" if not missing_data else "single_source",
        "freshness": "fresh",
        "direction": _geopolitical_direction(safe_haven_score=safe_haven_score, energy_channel_risk=energy_channel_risk),
        "summary": "地缘冲突状态、避险反应与能源链风险已接入，用于区分避险利多和通胀利空两条路径。",
    }


def _central_bank_gold_features(*, reserve_context: dict[str, Any]) -> dict[str, Any] | None:
    net_buying = _context_metric(
        reserve_context,
        "central_bank_net_buying",
        "global_central_bank_net_buying",
        "net_gold_purchases",
    )
    pboc_change = _context_metric(
        reserve_context,
        "pboc_gold_holdings_change",
        "pboc_holdings_change",
        "china_central_bank_gold_change",
    )
    support_score = _context_metric(
        reserve_context,
        "long_term_support_score",
        "reserve_support_score",
        "support_score",
    )
    diversification_signal = _context_text(
        reserve_context,
        "reserve_diversification_signal",
        "diversification_signal",
    )
    monetary_repricing = _context_text(
        reserve_context,
        "monetary_credit_repricing",
        "credit_repricing_signal",
        "usd_credit_repricing",
    )
    if all(
        value in {None, ""}
        for value in [net_buying, pboc_change, support_score, diversification_signal, monetary_repricing]
    ):
        return None

    missing_data: list[str] = []
    if net_buying is None or pboc_change is None:
        missing_data.append("central_bank_reserves")

    return {
        "feature_fields": {
            "central_bank_net_buying": net_buying,
            "pboc_gold_holdings_change": pboc_change,
            "reserve_diversification_signal": diversification_signal,
            "monetary_credit_repricing": monetary_repricing,
            "long_term_support_score": support_score,
        },
        "source_refs": _reserve_source_refs(reserve_context=reserve_context),
        "missing_data": missing_data,
        "verification_status": "official_confirmed" if not missing_data else "multi_source",
        "freshness": "fresh",
        "direction": "bullish" if (support_score or 0) > 0 else "neutral",
        "summary": "央行净买金、PBOC 持仓变化与储备重配信号已接入，用于识别长期结构性底层支撑。",
    }


def _china_asia_demand_features(*, asia_context: dict[str, Any]) -> dict[str, Any] | None:
    usdcnh_weekly_change = _context_metric(
        asia_context,
        "usdcnh_weekly_change",
        "usdcnh_change",
        "cnh_weekly_change",
    )
    usdcnh_monthly_change = _context_metric(
        asia_context,
        "usdcnh_monthly_change",
        "cnh_monthly_change",
    )
    usdcnh_change, usdcnh_basis = _resolved_change(
        weekly=usdcnh_weekly_change,
        monthly=usdcnh_monthly_change,
    )
    shanghai_premium = _context_metric(
        asia_context,
        "shanghai_gold_premium",
        "shanghai_premium",
        "sge_premium",
    )
    china_etf_flow = _context_metric(
        asia_context,
        "china_gold_etf_flow",
        "china_etf_flow",
        "asia_etf_flow",
    )
    asia_demand_score = _context_metric(
        asia_context,
        "asia_demand_score",
        "regional_demand_score",
    )
    india_physical_demand = _context_metric(
        asia_context,
        "india_physical_demand",
        "india_demand_score",
    )
    cny_relative_strength = _context_text(
        asia_context,
        "cny_gold_relative_strength",
        "regional_relative_strength",
    )
    if cny_relative_strength in {None, ""}:
        cny_relative_strength = _cny_gold_relative_strength(
            usdcnh_trend=_trend_from_change(usdcnh_change),
            shanghai_gold_premium=shanghai_premium,
            china_gold_etf_flow=china_etf_flow,
        )
    if all(
        value in {None, ""}
        for value in [
            usdcnh_change,
            shanghai_premium,
            china_etf_flow,
            asia_demand_score,
            india_physical_demand,
            cny_relative_strength,
        ]
    ):
        return None

    missing_data: list[str] = []
    if usdcnh_change is None:
        missing_data.append("fx_market")
    if shanghai_premium is None:
        missing_data.append("shanghai_gold_premium")
    if china_etf_flow is None:
        missing_data.append("china_gold_etf")
    if asia_demand_score is None:
        missing_data.append("asia_physical_demand")
    if india_physical_demand is None:
        missing_data.append("india_physical_demand")

    return {
        "feature_fields": {
            "usdcnh_trend": _trend_from_change(usdcnh_change),
            "usdcnh_weekly_change": usdcnh_weekly_change,
            "usdcnh_monthly_change": usdcnh_monthly_change,
            "usdcnh_trend_basis": usdcnh_basis,
            "shanghai_gold_premium": shanghai_premium,
            "china_gold_etf_flow": china_etf_flow,
            "asia_demand_score": asia_demand_score,
            "india_physical_demand": india_physical_demand,
            "cny_gold_relative_strength": cny_relative_strength,
        },
        "source_refs": _asia_source_refs(asia_context=asia_context),
        "missing_data": missing_data,
        "verification_status": "official_confirmed" if not missing_data else "multi_source",
        "freshness": "fresh",
        "direction": "bullish" if cny_relative_strength == "supportive" else "neutral",
        "summary": "人民币汇率、上海金溢价、中国 ETF 与印度实物需求已接入，用于判断亚洲区域买盘是否形成支撑。",
    }


def _institutional_sentiment_features(*, positioning_context: dict[str, Any]) -> dict[str, Any] | None:
    comex_net_long = _context_metric(
        positioning_context,
        "comex_net_long",
        "net_long",
        "comex_gold_net_long",
        "cot_net_long",
    )
    option_skew = _context_metric(
        positioning_context,
        "option_skew",
        "gold_option_skew",
        "skew",
    )
    call_put_oi_ratio = _context_metric(
        positioning_context,
        "call_put_oi_ratio",
        "cp_oi_ratio",
        "call_put_ratio",
    )
    cot_positioning = _context_text(
        positioning_context,
        "cot_positioning",
        "cot_signal",
        "positioning_regime",
    )
    institutional_sentiment = _context_text(
        positioning_context,
        "institutional_sentiment",
        "forecast_consensus",
        "street_sentiment",
    )
    positioning_crowding = _context_text(
        positioning_context,
        "positioning_crowding",
        "crowding_signal",
        "crowding_status",
    )
    if all(
        value in {None, ""}
        for value in [
            comex_net_long,
            option_skew,
            call_put_oi_ratio,
            cot_positioning,
            institutional_sentiment,
            positioning_crowding,
        ]
    ):
        return None

    missing_data: list[str] = []
    if comex_net_long is None or cot_positioning in {None, ""}:
        missing_data.append("positioning_data")
    if option_skew is None or call_put_oi_ratio is None:
        missing_data.append("cme_options")
    if institutional_sentiment in {None, ""}:
        missing_data.append("institutional_forecasts")

    return {
        "feature_fields": {
            "comex_net_long": comex_net_long,
            "cot_positioning": cot_positioning,
            "option_skew": option_skew,
            "call_put_oi_ratio": call_put_oi_ratio,
            "institutional_sentiment": institutional_sentiment,
            "positioning_crowding": positioning_crowding,
        },
        "source_refs": _positioning_source_refs(positioning_context=positioning_context),
        "missing_data": missing_data,
        "verification_status": "official_confirmed" if not missing_data else "multi_source",
        "freshness": "fresh",
        "direction": _institutional_direction(
            institutional_sentiment=institutional_sentiment,
            positioning_crowding=positioning_crowding,
            call_put_oi_ratio=call_put_oi_ratio,
        ),
        "summary": "COT、COMEX 净多、期权偏度与机构观点已接入，用于判断拥挤度和短线结构风险。",
    }


def _indicator(indicators: dict[str, Any], *symbols: str) -> dict[str, Any] | None:
    for symbol in symbols:
        value = indicators.get(symbol)
        if isinstance(value, dict):
            return dict(value)
    return None


def _macro_source_refs(*, macro_context: dict[str, Any], symbols: list[str]) -> list[dict[str, Any]]:
    refs_payload = _dict(macro_context.get("source_refs"))
    refs: list[dict[str, Any]] = []
    for symbol in symbols:
        ref = refs_payload.get(symbol)
        if isinstance(ref, dict):
            refs.append({"source": ref.get("source") or "macro_snapshot", "source_ref": symbol, **dict(ref)})
    if not refs and macro_context:
        refs.append({"source": "macro_snapshot", "source_ref": str(macro_context.get("as_of") or "latest")})
    return refs


def _extract_gold_price(market_context: dict[str, Any]) -> float | None:
    for key in ("gold_spot_price", "xauusd_price", "price", "close"):
        price = _number(market_context.get(key))
        if price is not None:
            return price
    tickers = _dict(market_context.get("tickers"))
    for key in ("xauusd", "XAUUSD", "gold"):
        ticker = tickers.get(key)
        if isinstance(ticker, dict):
            price = _number(ticker.get("price") or ticker.get("close") or ticker.get("latest_value"))
            if price is not None:
                return price
    metrics = market_context.get("metrics")
    if isinstance(metrics, list):
        for item in metrics:
            if isinstance(item, dict) and str(item.get("key") or item.get("asset") or "").upper() == "XAUUSD":
                price = _number(item.get("latest_value") or item.get("price") or item.get("close"))
                if price is not None:
                    return price
    series = market_context.get("series")
    if isinstance(series, list) and series:
        latest = next((item for item in reversed(series) if isinstance(item, dict)), None)
        if latest:
            ohlc = latest.get("xauusd_ohlc")
            if isinstance(ohlc, dict):
                price = _number(ohlc.get("close"))
                if price is not None:
                    return price
            return _number(latest.get("XAUUSD") or latest.get("xauusd"))
    return None


def _market_source_refs(*, market_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = market_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="market_context", default_lineage_type="market_snapshot")
    trace = market_context.get("source_trace")
    if isinstance(trace, list):
        return _annotated_source_refs(trace, evidence_role="market_context", default_lineage_type="market_snapshot")
    source = market_context.get("source") or market_context.get("interpretation")
    return _annotated_source_refs(
        [{"source": str(source or "market_context"), "source_ref": "XAUUSD"}],
        evidence_role="market_context",
        default_lineage_type="market_snapshot",
    ) if market_context else []


def _oil_source_refs(*, oil_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = oil_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="oil_context", default_lineage_type="context_artifact")
    source = oil_context.get("source") or oil_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "oil_context"), "source_ref": "Brent/WTI"}],
        evidence_role="oil_context",
        default_lineage_type="context_artifact",
    ) if oil_context else []


def _flow_source_refs(*, flow_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = flow_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="flow_context", default_lineage_type="context_artifact")
    trace = flow_context.get("source_trace")
    if isinstance(trace, list):
        return _annotated_source_refs(trace, evidence_role="flow_context", default_lineage_type="context_artifact")
    source = flow_context.get("source") or flow_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "flow_context"), "source_ref": "gold_etf_flow"}],
        evidence_role="flow_context",
        default_lineage_type="context_artifact",
    ) if flow_context else []


def _reserve_source_refs(*, reserve_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = reserve_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="reserve_context", default_lineage_type="context_artifact")
    source = reserve_context.get("source") or reserve_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "reserve_context"), "source_ref": "central_bank_gold"}],
        evidence_role="reserve_context",
        default_lineage_type="context_artifact",
    ) if reserve_context else []


def _asia_source_refs(*, asia_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = asia_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="asia_context", default_lineage_type="context_artifact")
    source = asia_context.get("source") or asia_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "asia_context"), "source_ref": "china_asia_demand"}],
        evidence_role="asia_context",
        default_lineage_type="context_artifact",
    ) if asia_context else []


def _positioning_source_refs(*, positioning_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = positioning_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="positioning_context", default_lineage_type="context_artifact")
    source = positioning_context.get("source") or positioning_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "positioning_context"), "source_ref": "institutional_sentiment"}],
        evidence_role="positioning_context",
        default_lineage_type="context_artifact",
    ) if positioning_context else []


def _policy_source_refs(*, policy_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = policy_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="policy_context", default_lineage_type="context_artifact")
    source = policy_context.get("source") or policy_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "policy_context"), "source_ref": "fed_policy_path"}],
        evidence_role="policy_context",
        default_lineage_type="context_artifact",
    ) if policy_context else []


def _geopolitical_source_refs(*, geopolitical_context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = geopolitical_context.get("source_refs")
    if isinstance(refs, list):
        return _annotated_source_refs(refs, evidence_role="geopolitical_context", default_lineage_type="context_artifact")
    source = geopolitical_context.get("source") or geopolitical_context.get("provider")
    return _annotated_source_refs(
        [{"source": str(source or "geopolitical_context"), "source_ref": "geopolitical_war_risk"}],
        evidence_role="geopolitical_context",
        default_lineage_type="context_artifact",
    ) if geopolitical_context else []


def _annotated_source_refs(refs: Any, *, evidence_role: str, default_lineage_type: str) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        item = dict(ref)
        item.setdefault("source_tier", _source_tier(item))
        item.setdefault("evidence_role", evidence_role)
        item.setdefault("lineage_type", _lineage_type(item, default_lineage_type=default_lineage_type))
        annotated.append(item)
    return annotated


def _source_tier(ref: dict[str, Any]) -> str:
    explicit = str(ref.get("source_tier") or "").strip()
    if explicit:
        return explicit
    role = str(ref.get("provider_role") or ref.get("source_type") or "").lower()
    if role in {"official", "official_source"}:
        return "official"
    if role in {"supplemental", "supplemental_source"}:
        return "supplemental"
    if role in {"market", "market_data", "market_derived", "derived"}:
        return "market_derived"
    source = str(ref.get("source") or ref.get("provider") or ref.get("source_key") or "").lower()
    if any(marker in source for marker in ("jin10", "gdelt", "reuters", "ap", "news")):
        return "supplemental"
    if any(marker in source for marker in ("cme_options", "market", "openbb", "sge", "cnbc", "energy", "oil")):
        return "market_derived"
    if any(marker in source for marker in ("fed", "fred", "treasury", "bls", "bea", "eia", "wgc", "imf", "pboc", "cme_cot")):
        return "official"
    return "manual"


def _lineage_type(ref: dict[str, Any], *, default_lineage_type: str) -> str:
    explicit = str(ref.get("lineage_type") or "").strip()
    if explicit:
        return explicit
    if ref.get("parsed_path"):
        return "parsed_artifact"
    if ref.get("path"):
        return "analysis_artifact"
    if ref.get("raw_path") or ref.get("raw_js_path"):
        return "raw_artifact"
    return default_lineage_type


def _context_metric(context: dict[str, Any], *aliases: str) -> float | None:
    for alias in aliases:
        value = _number(context.get(alias))
        if value is not None:
            return value

    containers = [
        _dict(context.get("flows")),
        _dict(context.get("regional_flows")),
        _dict(context.get("regions")),
        _dict(context.get("metrics")),
    ]
    for container in containers:
        for alias in aliases:
            value = _nested_metric(container, alias)
            if value is not None:
                return value

    metrics = context.get("metrics")
    if isinstance(metrics, list):
        for item in metrics:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("name") or item.get("region") or "").strip()
            if key in aliases:
                value = _nested_metric(item, key)
                if value is not None:
                    return value
    return None


def _nested_metric(payload: dict[str, Any], key: str) -> float | None:
    candidate = payload.get(key)
    if isinstance(candidate, dict):
        for field in ("value", "net_flow", "latest_value", "weekly_change", "monthly_change"):
            value = _number(candidate.get(field))
            if value is not None:
                return value
    value = _number(candidate)
    if value is not None:
        return value
    return None


def _context_text(context: dict[str, Any], *aliases: str) -> str | None:
    for alias in aliases:
        value = context.get(alias)
        if isinstance(value, str) and value.strip():
            return value.strip()
    containers = [
        _dict(context.get("signals")),
        _dict(context.get("features")),
        _dict(context.get("metrics")),
    ]
    for container in containers:
        for alias in aliases:
            value = container.get(alias)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                candidate = value.get("value") or value.get("signal") or value.get("status")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return None


def _macro_indicator_change(*, macro_context: dict[str, Any], symbol: str) -> float | None:
    indicators = _dict(macro_context.get("indicators"))
    indicator = _indicator(indicators, symbol)
    if indicator is None:
        return None
    resolved, _basis = _resolved_change(
        weekly=_number(indicator.get("weekly_change")),
        monthly=_number(indicator.get("monthly_change")),
    )
    return resolved


def _macro_indicator_level(*, macro_context: dict[str, Any], symbol: str) -> float | None:
    indicators = _dict(macro_context.get("indicators"))
    indicator = _indicator(indicators, symbol)
    return _number(indicator.get("value")) if indicator else None


def _average_changes(*values: float | None) -> float | None:
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return round(sum(observed) / len(observed), 6)


def _spread(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 6)


def _brent_wti_status(spread: float | None) -> str:
    if spread is None:
        return "unknown"
    if spread >= 3:
        return "backwardation_risk"
    if spread <= -3:
        return "oversupplied"
    return "balanced"


def _oil_supply_shock(inventory_change: float | None) -> str:
    if inventory_change is None:
        return "unknown"
    if inventory_change <= -2:
        return "supply_draw"
    if inventory_change >= 2:
        return "inventory_build"
    return "balanced"


def _energy_inflation_risk(*, oil_price_trend: str, oil_supply_shock: str, inflation_change: float | None) -> str:
    if oil_price_trend == "rising" and oil_supply_shock == "supply_draw":
        if inflation_change is None or inflation_change >= 0:
            return "building"
    if oil_price_trend == "falling":
        return "easing"
    return "mixed"


def _oil_to_fed_pressure(*, oil_price_trend: str, real_rate_change: float | None, nominal_yield_change: float | None) -> str:
    if oil_price_trend == "rising" and (
        _trend_from_change(real_rate_change) == "rising" or _trend_from_change(nominal_yield_change) == "rising"
    ):
        return "inflation_reacceleration_risk"
    if oil_price_trend == "rising" and _trend_from_change(real_rate_change) == "falling":
        return "safe_haven_offset"
    if oil_price_trend == "falling":
        return "disinflation_relief"
    return "mixed"


def _flow_trend(flow_value: float | None) -> str:
    if flow_value is None:
        return "unknown"
    if flow_value > 0:
        return "inflow"
    if flow_value < 0:
        return "outflow"
    return "flat"


def _flow_confirmation_status(
    *,
    global_flow: float | None,
    north_america_flow: float | None,
    asia_flow: float | None,
) -> str:
    nonzero_signs = [sign for sign in [_flow_sign(global_flow), _flow_sign(north_america_flow), _flow_sign(asia_flow)] if sign]
    if global_flow is not None and north_america_flow is not None and asia_flow is not None:
        if nonzero_signs and len(set(nonzero_signs)) == 1:
            return "confirmed_inflow" if nonzero_signs[0] > 0 else "confirmed_outflow"
        return "regional_divergence"
    if global_flow is not None and (north_america_flow is not None or asia_flow is not None):
        if nonzero_signs and len(set(nonzero_signs)) == 1:
            return "partial_confirmation"
        return "mixed"
    if global_flow is not None:
        return "global_only"
    return "regional_only"


def _flow_direction(*, flow_trend: str, confirmation_status: str) -> str:
    if flow_trend == "inflow" and confirmation_status in {"confirmed_inflow", "partial_confirmation", "global_only"}:
        return "bullish"
    if flow_trend == "outflow" and confirmation_status in {"confirmed_outflow", "partial_confirmation", "global_only"}:
        return "bearish"
    return "neutral"


def _flow_sign(value: float | None) -> int:
    if value is None:
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _cny_gold_relative_strength(*, usdcnh_trend: str, shanghai_gold_premium: float | None, china_gold_etf_flow: float | None) -> str:
    if (shanghai_gold_premium or 0) > 0 and (china_gold_etf_flow or 0) > 0:
        return "supportive"
    if usdcnh_trend == "falling" and (shanghai_gold_premium or 0) > 0:
        return "supportive"
    if usdcnh_trend == "rising" and (china_gold_etf_flow or 0) < 0:
        return "weakening"
    return "mixed"


def _institutional_direction(
    *,
    institutional_sentiment: str | None,
    positioning_crowding: str | None,
    call_put_oi_ratio: float | None,
) -> str:
    sentiment = (institutional_sentiment or "").lower()
    crowding = (positioning_crowding or "").lower()
    if "bear" in sentiment:
        return "bearish"
    if "bull" in sentiment and crowding not in {"crowded_long", "overcrowded_long"}:
        return "bullish"
    if call_put_oi_ratio is not None and call_put_oi_ratio < 0.9 and "long" in crowding:
        return "bearish"
    return "neutral"


def _fed_policy_direction(*, fed_policy_bias: str | None, fomc_tone: str | None) -> str:
    bias = (fed_policy_bias or "").lower()
    tone = (fomc_tone or "").lower()
    if "higher" in bias or "hawk" in bias or "hawk" in tone:
        return "bearish"
    if "cut" in bias or "dov" in bias or "dov" in tone:
        return "bullish"
    return "neutral"


def _geopolitical_direction(*, safe_haven_score: float | None, energy_channel_risk: str | None) -> str:
    if (safe_haven_score or 0) >= 6 and str(energy_channel_risk or "") not in {"extreme", "severe"}:
        return "bullish"
    if str(energy_channel_risk or "") in {"elevated", "extreme", "severe"}:
        return "mixed"
    return "neutral"


def _level_status(price: float, level: float) -> str:
    if price >= level:
        return "above"
    return "below"


def _range_status(price: float, lower: float, upper: float) -> str:
    if price > upper:
        return "above"
    if lower <= price <= upper:
        return "inside"
    return "below"


def _technical_phase(price: float) -> str:
    if price >= 4300:
        return "strong_uptrend"
    if price >= 4120:
        return "trend_recovery_watch"
    if price >= 4000:
        return "weak_repair_watch"
    if price >= 3900:
        return "correction_escalation"
    return "trend_failure"


def _technical_confirmation(price: float) -> str:
    if price >= 4300:
        return "trend_recovery_confirmed"
    if price >= 4100:
        return "repair_confirming"
    if price >= 4000:
        return "support_holding"
    if price >= 3900:
        return "support_lost_watch"
    return "trend_failure_confirmed"


def _technical_direction(price: float) -> str:
    if price >= 4120:
        return "bullish"
    if price < 4000:
        return "bearish"
    return "neutral"


def _trend_from_change(change: float | None) -> str:
    if change is None:
        return "unknown"
    if change > 0.02:
        return "rising"
    if change < -0.02:
        return "falling"
    return "stable"


def _resolved_change(*, weekly: float | None, monthly: float | None) -> tuple[float | None, str]:
    if weekly is not None:
        return weekly, "weekly"
    if monthly is not None:
        return monthly, "monthly"
    return None, "unavailable"


def _yield_pressure(change: float | None) -> str:
    trend = _trend_from_change(change)
    if trend == "rising":
        return "rising_pressure"
    if trend == "falling":
        return "easing_pressure"
    return trend


def _dollar_pressure(change: float | None) -> str:
    trend = _trend_from_change(change)
    if trend == "rising":
        return "stronger_dollar_pressure"
    if trend == "falling":
        return "weaker_dollar_support"
    return trend


def _yield_curve_2y3m_signal(*, level: float | None, trend: str) -> str:
    if level is None:
        return "unavailable"
    if level < 0 and trend == "rising":
        return "pivot_window_improving"
    if level < 0 and trend == "falling":
        return "inversion_deepening_hard_landing_risk"
    if level < 0:
        return "inverted_curve_policy_pivot_watch"
    if trend == "falling":
        return "curve_flattening_short_rate_pressure"
    return "positive_curve_no_near_term_easing"


def _yield_curve_2y3m_market_meaning(*, level: float | None, trend: str) -> str:
    if level is None:
        return "2Y-3M 利差缺失，无法判断短端政策拐点定价。"
    if level < 0 and trend == "rising":
        return "2Y-3M 仍倒挂但正在改善，代表短端政策拐点/降息预期升温；若 10Y 实际利率同步回落，黄金低点确认概率提高。"
    if level < 0 and trend == "falling":
        return "2Y-3M 倒挂加深，代表短端压力或硬着陆风险仍未解除；黄金修复需要实际利率和美元进一步确认。"
    if level < 0:
        return "2Y-3M 处于倒挂区间，市场仍在定价周期后段和潜在政策转向，但方向尚未确认。"
    if trend == "falling":
        return "2Y-3M 正斜率收窄，短端利率压力仍需观察；黄金低点确认不能只靠曲线信号。"
    return "2Y-3M 维持正斜率或继续走阔，短端衰退/降息定价不足，黄金主要仍看实际利率和美元。"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dominant_mainline(covered_rows: list[dict[str, Any]], *, priority_mainline_ids: list[str] | None = None) -> str | None:
    if not covered_rows:
        return None
    if priority_mainline_ids:
        priority_set = set(priority_mainline_ids)
        priority_rows = [row for row in covered_rows if str(row.get("mainline_id") or row.get("mainline")) in priority_set]
        if priority_rows:
            covered_rows = priority_rows
    sorted_rows = sorted(
        covered_rows,
        key=lambda row: (-(float(row.get("theme_score") or row.get("score") or 0.0)), int(row.get("rank") or 99)),
    )
    return str(sorted_rows[0].get("mainline_id") or sorted_rows[0].get("mainline"))


def _priority_decision(
    *,
    theme_rankings: list[dict[str, Any]],
    links: list[dict[str, Any]],
    chain: TransmissionChainSummary | None,
) -> PriorityDecision:
    rows = {str(row.get("mainline_id") or row.get("mainline")): row for row in theme_rankings}
    if _has_monetary_credit_repricing(rows):
        return PriorityDecision(
            regime="monetary_credit_repricing",
            reason="央行买金、储备多元化或货币信用重估信号出现，长期结构支撑优先于短线事件分数。",
            mainline_ids=["central_bank_gold", "china_asia_demand"],
        )
    if _has_large_capital_flow(rows):
        return PriorityDecision(
            regime="large_capital_flow",
            reason="ETF 或机构持仓出现大额流入/流出，资金验证主线优先于普通事件排序。",
            mainline_ids=["etf_flows", "institutional_sentiment"],
        )
    if _has_war_escalation(rows, chain):
        return PriorityDecision(
            regime="war_escalation",
            reason="地缘风险升级并触发避险或能源通胀链，优先评估地缘战争风险与油价路径。",
            mainline_ids=["geopolitical_war_risk", "oil_prices"],
        )
    if _has_policy_event_cycle(rows, links):
        return PriorityDecision(
            regime="policy_event_cycle",
            reason="FOMC、CPI、非农或利率预期重定价窗口中，美联储路径优先于普通主题分数。",
            mainline_ids=["fed_policy_path", "real_rates_usd"],
        )
    return PriorityDecision(
        regime="normal_rate_environment",
        reason="未检测到战争升级、政策事件窗口、资金大流动或货币信用重估，按 theme_score 与 v3 主线顺序选择主导因素。",
        mainline_ids=[],
    )


def _has_policy_event_cycle(rows: dict[str, dict[str, Any]], links: list[dict[str, Any]]) -> bool:
    fed_fields = _row_feature_fields(rows, "fed_policy_path")
    if fed_fields.get("policy_surprise") not in {None, "", "none", "neutral", "unknown"}:
        return True
    if fed_fields.get("fomc_tone") not in {None, "", "unknown", "neutral"}:
        return True
    if fed_fields.get("rate_expectation_delta") is not None or fed_fields.get("cut_hike_probability") is not None:
        return True
    policy_event_types = {"fed_hawkish", "fed_dovish", "cpi_release", "nonfarm_payrolls", "fomc"}
    policy_paths = {"strong_data_to_higher_for_longer", "weak_data_to_rate_cut_expectation"}
    for link in links:
        mainline_ids = {str(item) for item in link.get("mainline_ids") or []}
        if str(link.get("primary_mainline") or "") == "fed_policy_path" or "fed_policy_path" in mainline_ids:
            return True
        if str(link.get("event_type") or "") in policy_event_types:
            return True
        if str(link.get("impact_path") or "") in policy_paths:
            return True
    return False


def _has_war_escalation(rows: dict[str, dict[str, Any]], chain: TransmissionChainSummary | None) -> bool:
    geo_fields = _row_feature_fields(rows, "geopolitical_war_risk")
    war_status = str(geo_fields.get("geopolitical_status") or "").lower()
    escalation = str(geo_fields.get("war_escalation_level") or "").lower()
    energy_risk = str(geo_fields.get("energy_channel_risk") or "").lower()
    chain_status = str(geo_fields.get("war_oil_rate_chain_status") or "").lower()
    safe_haven_score = _number(geo_fields.get("safe_haven_score"))
    if war_status in {"escalating", "active", "war", "conflict"}:
        return True
    if any(token in escalation for token in ("regional", "escalat", "high", "war")):
        return True
    if energy_risk in {"elevated", "high", "severe"} or chain_status == "active":
        return True
    if safe_haven_score is not None and safe_haven_score >= 7:
        return True
    return bool(chain and chain.status == "available" and chain.conclusion_code in {"A", "B"})


def _has_large_capital_flow(rows: dict[str, dict[str, Any]]) -> bool:
    flow_fields = _row_feature_fields(rows, "etf_flows")
    positioning_fields = _row_feature_fields(rows, "institutional_sentiment")
    flow_values = [
        _number(flow_fields.get("aggregate_etf_flow")),
        _number(flow_fields.get("global_etf_flow")),
        _number(flow_fields.get("north_america_etf_flow")),
        _number(flow_fields.get("asia_etf_flow")),
    ]
    if any(value is not None and abs(value) >= 5 for value in flow_values):
        return True
    if str(flow_fields.get("flow_confirmation_status") or "") in {"confirmed_inflow", "confirmed_outflow"}:
        return True
    call_put_ratio = _number(positioning_fields.get("call_put_oi_ratio"))
    if call_put_ratio is not None and (call_put_ratio >= 1.5 or call_put_ratio <= 0.7):
        return True
    crowding = str(positioning_fields.get("positioning_crowding") or "")
    return crowding in {"crowded_long", "crowded_short", "squeeze_risk", "liquidation_risk"}


def _has_monetary_credit_repricing(rows: dict[str, dict[str, Any]]) -> bool:
    reserve_fields = _row_feature_fields(rows, "central_bank_gold")
    asia_fields = _row_feature_fields(rows, "china_asia_demand")
    if str(reserve_fields.get("monetary_credit_repricing") or "") in {"active", "confirmed", "reprice", "repricing"}:
        return True
    if str(reserve_fields.get("reserve_diversification_signal") or "") in {"strong", "active", "confirmed"}:
        return True
    support_score = _number(reserve_fields.get("long_term_support_score"))
    if support_score is not None and support_score >= 8:
        return True
    premium = _number(asia_fields.get("shanghai_gold_premium"))
    return premium is not None and premium >= 35 and str(asia_fields.get("cny_gold_relative_strength") or "") == "supportive"


def _row_feature_fields(rows: dict[str, dict[str, Any]], mainline_id: str) -> dict[str, Any]:
    fields = rows.get(mainline_id, {}).get("feature_fields")
    return dict(fields) if isinstance(fields, dict) else {}


def _net_bias(links: list[dict[str, Any]]) -> str:
    directions = [str((link.get("direction_by_asset") or {}).get("XAUUSD") or "unknown") for link in links]
    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    mixed = directions.count("mixed")
    if bearish >= 1 and mixed >= 1:
        return "neutral_bearish"
    if bullish >= 1 and mixed >= 1:
        return "neutral_bullish"
    if mixed:
        return "mixed"
    if bearish > bullish:
        return "bearish"
    if bullish > bearish:
        return "bullish"
    return "neutral"


def _driver_conflict(*, links: list[dict[str, Any]], net_bias: str, source_refs: list[dict[str, Any]]) -> DriverConflict:
    bullish = _unique(driver for link in links for driver in link.get("bullish_drivers") or [])
    bearish = _unique(driver for link in links for driver in link.get("bearish_drivers") or [])
    verification_needed = _unique(item for link in links for item in link.get("verification_needed") or [])
    if bullish and bearish:
        status = "mixed"
        explanation = "黄金事件同时存在避险/资金支撑与利率/美元/通胀压力。"
    elif bullish or bearish:
        status = "aligned"
        explanation = "黄金主线驱动当前方向较一致。"
    else:
        status = "unknown"
        explanation = "黄金主线驱动方向暂未形成可验证结构。"
    return DriverConflict(
        status=status,
        dominant_driver=_dominant_driver_value([*bearish, *bullish]),
        bullish_drivers=bullish,
        bearish_drivers=bearish,
        net_effect=net_bias,
        explanation=explanation,
        verification_needed=verification_needed,
        source_refs=source_refs,
    )


def _war_oil_rate_chain(
    links: list[dict[str, Any]],
    *,
    macro_context: dict[str, Any],
    oil_context: dict[str, Any],
) -> TransmissionChainSummary | None:
    chain_links = [link for link in links if "geopolitics_to_oil_to_rates" in (link.get("transmission_path_ids") or [])]
    if not chain_links:
        return None
    source_refs = _merge_source_refs([*(link.get("source_refs") or [] for link in chain_links), _oil_source_refs(oil_context=oil_context)])
    oil_fields = (_oil_price_features(oil_context=oil_context, macro_context=macro_context) or {}).get("feature_fields") or {}
    real_rate_fields = (_real_rates_usd_features(macro_context) or {}).get("feature_fields") or {}
    conclusion_code, conclusion_label, net_effect = _war_oil_rate_conclusion(
        chain_links,
        oil_fields=oil_fields,
        real_rate_fields=real_rate_fields,
    )
    oil_status = "available" if oil_fields.get("oil_price_trend") not in {None, "", "unknown"} else "partial"
    real_rate_status = "available" if real_rate_fields.get("real_rate_trend") not in {None, "", "unknown"} else "partial"
    return TransmissionChainSummary(
        path_id="geopolitics_to_oil_to_rates",
        label="战争-石油-通胀预期-美联储-实际利率-黄金",
        status="available" if oil_status == "available" and real_rate_status == "available" else "partial",
        conclusion_code=conclusion_code,
        conclusion_label=conclusion_label,
        net_effect=net_effect,
        dominant_driver=_war_oil_rate_dominant_driver(
            chain_links=chain_links,
            conclusion_code=conclusion_code,
            oil_fields=oil_fields,
        ),
        summary=f"{conclusion_label}：地缘事件通过油价、通胀预期和实际利率路径共同作用于黄金。",
        steps=[
            TransmissionChainStep("geopolitical_status", "地缘战争事件", source_refs=source_refs),
            TransmissionChainStep("oil_status", "Brent / WTI 与供应风险", status=oil_status, source_refs=source_refs),
            TransmissionChainStep("inflation_expectation_status", "通胀预期", source_refs=source_refs),
            TransmissionChainStep("fed_expectation_status", "美联储预期", source_refs=source_refs),
            TransmissionChainStep("real_rate_status", "实际利率", status=real_rate_status, source_refs=source_refs),
            TransmissionChainStep("dollar_status", "美元压力", source_refs=source_refs),
            TransmissionChainStep("gold_effect", "黄金方向", source_refs=source_refs),
        ],
        source_refs=source_refs,
    )


def _verification_matrix(*, links: list[dict[str, Any]], rankings: list[dict[str, Any]]) -> list[VerificationItem]:
    items: list[VerificationItem] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for link in links:
        event_id = str(link.get("event_id") or "") or None
        mainline_ids = [str(item) for item in link.get("mainline_ids") or [] if str(item)]
        if not mainline_ids and link.get("primary_mainline"):
            mainline_ids = [str(link.get("primary_mainline"))]
        refs = [dict(ref) for ref in link.get("source_refs") or [] if isinstance(ref, dict)]
        for check in link.get("verification_needed") or []:
            required_source = _required_source(str(check))
            for mainline_id in _verification_mainline_ids(mainline_ids, required_source):
                key = (event_id, mainline_id, required_source)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    _verification_item(
                        event_id=event_id,
                        mainline_id=mainline_id,
                        required_source=required_source,
                        reason=str(check),
                        source_refs=refs,
                    )
                )
    for row in rankings:
        if row.get("coverage_status") != "missing":
            continue
        mainline_id = str(row.get("mainline_id") or row.get("mainline"))
        for required_source in row.get("missing_data") or []:
            key = (None, mainline_id, str(required_source))
            if key in seen:
                continue
            seen.add(key)
            items.append(_verification_item(event_id=None, mainline_id=mainline_id, required_source=str(required_source), reason="missing_mainline_source", source_refs=[]))
    return items


def _verification_item(*, event_id: str | None, mainline_id: str | None, required_source: str | None, reason: str, source_refs: list[dict[str, Any]]) -> VerificationItem:
    item_id = ":".join(part for part in [event_id, mainline_id, required_source] if part)
    return VerificationItem(
        id=item_id or reason,
        label=_verification_label(required_source or reason),
        status="pending",
        mainline_id=mainline_id,
        event_id=event_id,
        required_source=required_source,
        reason=reason,
        source_refs=source_refs,
    )


def _verification_mainline_ids(mainline_ids: list[str], required_source: str) -> list[str | None]:
    matched = [
        mainline_id
        for mainline_id in mainline_ids
        if required_source in MAINLINE_META.get(mainline_id, {}).get("missing_data", [])
    ]
    return matched or [mainline_ids[0] if mainline_ids else None]


def _required_source(check_id: str) -> str:
    mapping = {
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
    return mapping.get(check_id, check_id)


def _phase_for_bias(*, net_bias: str, links: list[dict[str, Any]]) -> str:
    if net_bias in {"neutral_bearish", "mixed"}:
        return "weak_repair_watch"
    if net_bias == "bearish":
        return "correction_escalation"
    if net_bias == "bullish":
        return "strong_uptrend"
    if any(str((link.get("direction_by_asset") or {}).get("XAUUSD")) == "mixed" for link in links):
        return "high_level_range"
    return "unknown"


def _overview_status(*, payload: dict[str, Any], covered_rows: list[dict[str, Any]]) -> str:
    if not covered_rows:
        return "unavailable"
    if str(payload.get("status")) == "available" and len(covered_rows) == len(MAINLINE_ORDER):
        return "available"
    return "partial"


def _risk_score(*, net_bias: str, links: list[dict[str, Any]], verification_matrix: list[VerificationItem]) -> int:
    score = 45
    if net_bias in {"neutral_bearish", "bearish"}:
        score += 12
    elif net_bias in {"mixed", "neutral_bullish"}:
        score += 8
    score += min(12, len(verification_matrix))
    if any(str((link.get("direction_by_asset") or {}).get("XAUUSD")) == "mixed" for link in links):
        score += 3
    return min(score, 95)


def _one_line_conclusion(*, dominant_mainline: str | None, net_bias: str, conflict: DriverConflict | None) -> str:
    label = str(MAINLINE_META.get(str(dominant_mainline), {}).get("label") or "黄金主线")
    if conflict and conflict.status == "mixed":
        return f"{label}是当前主导因素，利多与利空驱动并存，净影响为{net_bias}。"
    return f"{label}是当前主导因素，净影响为{net_bias}。"


def _war_oil_rate_conclusion(
    chain_links: list[dict[str, Any]],
    *,
    oil_fields: dict[str, Any],
    real_rate_fields: dict[str, Any],
) -> tuple[str, str, str]:
    bullish = _unique(driver for link in chain_links for driver in link.get("bullish_drivers") or [])
    bearish = _unique(driver for link in chain_links for driver in link.get("bearish_drivers") or [])
    has_safe_haven = "safe_haven_bid" in bullish
    has_rate_pressure = bool({"oil_inflation_rate_pressure", "higher_for_longer_rate_pressure", "usd_strength_pressure"} & set(bearish))
    directions = [str((link.get("direction_by_asset") or {}).get("XAUUSD") or "unknown") for link in chain_links]
    oil_trend = str(oil_fields.get("oil_price_trend") or "unknown")
    real_rate_trend = str(real_rate_fields.get("real_rate_trend") or "unknown")
    if not chain_links or all(direction in {"", "unknown"} for direction in directions):
        return "D", "数据不足，待验证", "unknown"
    if oil_trend == "rising" and real_rate_trend == "rising":
        return "B", "通胀/加息主导，压制黄金", "bearish"
    if oil_trend == "rising" and real_rate_trend == "falling" and has_safe_haven:
        return "A", "避险主导，黄金受支撑", "bullish"
    if has_safe_haven and not has_rate_pressure:
        return "A", "避险主导，利多黄金", "bullish"
    if has_rate_pressure and not has_safe_haven:
        return "B", "通胀/加息主导，压制黄金", "bearish"
    if has_safe_haven and has_rate_pressure:
        return "C", "两者抵消，黄金震荡", "mixed"
    net_effect = _aggregate_direction(directions)
    if net_effect == "bullish":
        return "A", "避险主导，利多黄金", net_effect
    if net_effect == "bearish":
        return "B", "通胀/加息主导，压制黄金", net_effect
    return "C", "两者抵消，黄金震荡", net_effect


def _war_oil_rate_dominant_driver(*, chain_links: list[dict[str, Any]], conclusion_code: str, oil_fields: dict[str, Any]) -> str | None:
    if conclusion_code == "B" and oil_fields.get("oil_to_fed_pressure") == "inflation_reacceleration_risk":
        return "oil_inflation_rate_pressure"
    if conclusion_code == "A":
        return "safe_haven_bid"
    return _dominant_driver_value(
        _unique(driver for link in chain_links for driver in [*(link.get("bearish_drivers") or []), *(link.get("bullish_drivers") or [])])
    )


def _direction_score_from_direction(direction: str) -> int:
    if direction in {"strong_bullish"}:
        return 2
    if direction in {"bullish", "neutral_bullish"}:
        return 1
    if direction in {"bearish", "neutral_bearish"}:
        return -1
    if direction in {"strong_bearish"}:
        return -2
    return 0


def _confidence_bucket(value: Any) -> int:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 1
    if confidence >= 0.72:
        return 3
    if confidence >= 0.45:
        return 2
    return 1


def _aggregate_direction(directions: Any) -> str:
    values = [str(item) for item in directions if str(item) not in {"", "unknown"}]
    if not values:
        return "unknown"
    if len(set(values)) == 1:
        return values[0]
    return "mixed"


def _dominant_driver_value(drivers: list[str]) -> str | None:
    for candidate in DRIVER_PRIORITY:
        if candidate in drivers:
            return candidate
    return drivers[0] if drivers else None


def _verification_label(required_source: str) -> str:
    labels = {
        "news_sources": "多源确认",
        "oil_price": "油价反应确认",
        "real_rates": "实际利率确认",
        "etf_comex_flows": "资金流确认",
        "xauusd_price": "黄金价格确认",
        "official_data": "官方数据确认",
        "central_bank_reserves": "央行储备确认",
        "asia_physical_demand": "亚洲实物需求确认",
        "positioning_data": "持仓确认",
    }
    return labels.get(required_source, required_source)


MAINLINE_REQUIREMENT_META: dict[str, dict[str, Any]] = {
    "fed_policy_path": {
        "asset_principle": "黄金是无息资产，政策利率路径决定持有黄金的机会成本。",
        "analysis_chain": ["通胀/就业/FOMC", "降息或加息概率", "2Y/10Y 美债", "实际利率", "黄金机会成本"],
        "required_sources": ["official_data", "fed_funds_futures", "treasury_yields"],
        "required_fields": ["fed_policy_bias", "rate_expectation_delta", "cut_hike_probability", "fomc_tone", "policy_surprise"],
        "page_targets": ["Dashboard 总览", "黄金主线页", "利率与美元页", "事件流", "报告中心"],
    },
    "real_rates_usd": {
        "asset_principle": "黄金以美元计价且不生息，实际利率和美元共同构成估值中枢。",
        "analysis_chain": ["名义利率", "通胀预期", "实际利率", "2Y-3M 短端曲线", "DXY/美元流动性", "黄金估值压力"],
        "required_sources": ["real_rates", "inflation_expectations", "yield_curve", "dxy"],
        "required_fields": [
            "real_rate_level",
            "real_rate_trend",
            "real_rate_weekly_change",
            "yield_spread_2y_3m_level",
            "yield_curve_2y3m_signal",
            "dxy_trend",
            "dxy_weekly_change",
            "nominal_yield_pressure",
            "dollar_liquidity_pressure",
        ],
        "page_targets": ["Dashboard 总览", "黄金主线页", "利率与美元页", "市场监控", "报告中心"],
    },
    "oil_prices": {
        "asset_principle": "油价把战争风险传导到通胀预期和美联储反应，是避险与利率冲突的桥。",
        "analysis_chain": ["Brent/WTI", "能源供应风险", "通胀预期", "美联储预期", "实际利率/美元", "黄金"],
        "required_sources": ["oil_price", "energy_inventory", "inflation_expectations"],
        "required_fields": ["oil_price_trend", "brent_wti_status", "oil_supply_shock", "energy_inflation_risk", "oil_to_fed_pressure"],
        "page_targets": ["Dashboard 总览", "黄金主线页", "石油与地缘页", "事件流", "报告中心"],
    },
    "geopolitical_war_risk": {
        "asset_principle": "黄金是避险资产，但战争还会经油价推高通胀和利率压力。",
        "analysis_chain": ["地缘战争", "原油价格", "通胀预期", "美联储预期", "实际利率/美元", "黄金方向"],
        "required_sources": ["news_sources", "oil_price", "vix", "equity_reaction", "treasury_yields"],
        "required_fields": ["geopolitical_status", "war_escalation_level", "safe_haven_score", "energy_channel_risk", "war_oil_rate_chain_status"],
        "page_targets": ["Dashboard 总览", "黄金主线页", "石油与地缘页", "事件流", "报告中心"],
    },
    "etf_flows": {
        "asset_principle": "黄金是投资资产，ETF 流向验证宏观叙事是否变成趋势资金。",
        "analysis_chain": ["宏观叙事", "ETF 流入/流出", "趋势资金确认", "黄金反弹质量"],
        "required_sources": ["etf_flows", "regional_etf_flows"],
        "required_fields": ["global_etf_flow", "north_america_etf_flow", "asia_etf_flow", "etf_flow_trend", "flow_confirmation_status"],
        "page_targets": ["Dashboard 总览", "黄金主线页", "资金流监控页", "报告中心"],
    },
    "institutional_sentiment": {
        "asset_principle": "黄金是交易资产，COMEX/期权/机构情绪反映拥挤度和短线风险。",
        "analysis_chain": ["COT 持仓", "COMEX 净多", "期权 Call/Put", "波动率", "机构目标价", "短线风险"],
        "required_sources": ["positioning_data", "cme_options", "cot_report", "institutional_forecasts"],
        "required_fields": ["comex_net_long", "cot_positioning", "option_skew", "call_put_oi_ratio", "institutional_sentiment", "positioning_crowding"],
        "page_targets": ["资金流监控页", "期权结构页", "黄金主线页", "Dashboard 摘要", "报告中心"],
    },
    "central_bank_gold": {
        "asset_principle": "黄金是储备资产，央行买金和去美元化提供长期结构支撑。",
        "analysis_chain": ["美元信用/财政压力", "储备多元化", "央行买金", "黄金长期底层支撑"],
        "required_sources": ["central_bank_reserves", "wgc_data", "imf_reserves", "pboc_gold_holdings"],
        "required_fields": ["central_bank_net_buying", "pboc_gold_holdings_change", "reserve_diversification_signal", "monetary_credit_repricing", "long_term_support_score"],
        "page_targets": ["黄金主线页", "报告中心", "Dashboard 长期支撑摘要", "知识库"],
    },
    "china_asia_demand": {
        "asset_principle": "黄金也是区域需求资产，人民币黄金、沪金溢价和亚洲实物需求提供区域支撑。",
        "analysis_chain": ["人民币汇率", "上海金溢价", "中国黄金 ETF", "A股风险偏好", "印度实物需求", "亚洲买盘"],
        "required_sources": ["fx_market", "shanghai_gold_premium", "china_gold_etf", "asia_physical_demand", "india_physical_demand"],
        "required_fields": ["usdcnh_trend", "shanghai_gold_premium", "china_gold_etf_flow", "asia_demand_score", "india_physical_demand", "cny_gold_relative_strength"],
        "page_targets": ["中国/亚洲需求页", "黄金主线页", "Dashboard 摘要", "报告中心"],
    },
    "gold_technical_levels": {
        "asset_principle": "价格不是独立预测器，而是宏观逻辑和资金流的最终确认器。",
        "analysis_chain": ["价格行为", "关键位防守/突破", "利率/资金/美元确认", "阶段判断", "条件式交易含义"],
        "required_sources": ["xauusd_price", "market_candles", "technical_levels"],
        "required_fields": ["gold_spot_price", "level_4000_status", "level_4100_4120_status", "level_4300_status", "level_3900_status", "gold_phase", "technical_confirmation"],
        "page_targets": ["Dashboard 总览", "技术位监控页", "黄金主线页", "策略中心", "报告中心"],
    },
}


def _mainline_requirements(*, rankings: list[dict[str, Any]], verification_matrix: list[VerificationItem]) -> list[MainlineRequirement]:
    rankings_by_id = {str(row.get("mainline_id") or row.get("mainline")): row for row in rankings}
    verification_by_mainline: dict[str, list[VerificationItem]] = {}
    for item in verification_matrix:
        if item.mainline_id:
            verification_by_mainline.setdefault(item.mainline_id, []).append(item)

    requirements: list[MainlineRequirement] = []
    for mainline_id in MAINLINE_ORDER:
        ranking = rankings_by_id.get(mainline_id, {})
        meta = MAINLINE_META[mainline_id]
        requirement_meta = MAINLINE_REQUIREMENT_META[mainline_id]
        required_sources = [str(item) for item in requirement_meta["required_sources"]]
        missing_sources = _requirement_missing_sources(
            required_sources=required_sources,
            ranking=ranking,
            verification_items=verification_by_mainline.get(mainline_id, []),
        )
        developed_sources = [item for item in required_sources if item not in missing_sources]
        required_fields = [str(item) for item in requirement_meta["required_fields"]]
        missing_fields = _missing_required_fields(required_fields=required_fields, ranking=ranking)
        readiness_status = _requirement_status(
            coverage_status=str(ranking.get("coverage_status") or "missing"),
            missing_sources=missing_sources,
            missing_fields=missing_fields,
        )
        requirements.append(
            MainlineRequirement(
                mainline_id=mainline_id,
                label=str(meta["label"]),
                pricing_layer=str(meta["pricing_layer"]),
                asset_principle=str(requirement_meta["asset_principle"]),
                analysis_chain=[str(item) for item in requirement_meta["analysis_chain"]],
                required_sources=required_sources,
                required_fields=required_fields,
                developed_sources=developed_sources,
                missing_sources=missing_sources,
                missing_fields=missing_fields,
                readiness_status=readiness_status,
                page_targets=[str(item) for item in requirement_meta["page_targets"]],
                verification_requirements=_unique(
                    [
                        *(str(item.reason or item.required_source or item.id) for item in verification_by_mainline.get(mainline_id, [])),
                        *(str(item) for item in ranking.get("verification_needed") or []),
                    ]
                ),
                development_gaps=_development_gaps(
                    mainline_id=mainline_id,
                    missing_sources=missing_sources,
                    missing_fields=missing_fields,
                    readiness_status=readiness_status,
                ),
            )
        )
    return requirements


def _requirement_missing_sources(*, required_sources: list[str], ranking: dict[str, Any], verification_items: list[VerificationItem]) -> list[str]:
    coverage_status = str(ranking.get("coverage_status") or "missing")
    explicit_missing = {str(item) for item in ranking.get("missing_data") or [] if str(item)}
    explicit_missing.update(str(item.required_source) for item in verification_items if item.required_source)
    feature_fields = ranking.get("feature_fields")
    source_refs = [dict(ref) for ref in ranking.get("source_refs") or [] if isinstance(ref, dict)]
    if isinstance(feature_fields, dict):
        explicit_missing = {
            source
            for source in explicit_missing
            if not _source_satisfied_by_requirement(source=source, feature_fields=feature_fields, source_refs=source_refs)
        }
    if coverage_status == "missing":
        return [
            source
            for source in required_sources
            if not _source_satisfied_by_requirement(
                source=source,
                feature_fields=feature_fields if isinstance(feature_fields, dict) else {},
                source_refs=source_refs,
            )
        ]
    return [
        source
        for source in required_sources
        if source in explicit_missing
        or _source_family_missing(source, explicit_missing)
        or (
            isinstance(feature_fields, dict)
            and _source_satisfied_by_features(source=source, feature_fields=feature_fields)
            and not _source_tier_satisfies(source=source, source_refs=source_refs)
        )
    ]


def _source_satisfied_by_requirement(*, source: str, feature_fields: dict[str, Any], source_refs: list[dict[str, Any]]) -> bool:
    return _source_satisfied_by_features(source=source, feature_fields=feature_fields) and _source_tier_satisfies(
        source=source,
        source_refs=source_refs,
    )


def _source_satisfied_by_features(*, source: str, feature_fields: dict[str, Any]) -> bool:
    source_fields = {
        "real_rates": ["real_rate_level", "real_rate_trend"],
        "inflation_expectations": ["breakeven_10y_level"],
        "yield_curve": ["yield_spread_2y_3m_level", "yield_curve_2y3m_signal"],
        "dxy": ["dxy_trend"],
        "oil_price": ["oil_price_trend", "brent_wti_status"],
        "energy_inventory": ["oil_supply_shock"],
        "etf_flows": ["global_etf_flow", "etf_flow_trend"],
        "regional_etf_flows": ["north_america_etf_flow", "asia_etf_flow"],
        "central_bank_reserves": ["central_bank_net_buying", "pboc_gold_holdings_change"],
        "wgc_data": ["central_bank_net_buying"],
        "imf_reserves": ["central_bank_net_buying"],
        "pboc_gold_holdings": ["pboc_gold_holdings_change"],
        "fx_market": ["usdcnh_trend"],
        "shanghai_gold_premium": ["shanghai_gold_premium"],
        "china_gold_etf": ["china_gold_etf_flow"],
        "asia_physical_demand": ["asia_demand_score"],
        "india_physical_demand": ["india_physical_demand"],
        "positioning_data": ["comex_net_long", "cot_positioning"],
        "cme_options": ["option_skew", "call_put_oi_ratio"],
        "cot_report": ["cot_positioning"],
        "institutional_forecasts": ["institutional_sentiment"],
        "official_data": ["fed_policy_bias", "fomc_tone"],
        "fed_funds_futures": ["rate_expectation_delta", "cut_hike_probability"],
        "treasury_yields": ["treasury_2y_change", "treasury_10y_change"],
        "news_sources": ["geopolitical_status", "war_escalation_level"],
        "vix": ["vix_reaction"],
        "equity_reaction": ["equity_reaction"],
        "xauusd_price": ["gold_spot_price"],
        "market_candles": ["gold_spot_price"],
        "technical_levels": ["level_3900_status", "level_4000_status", "level_4100_4120_status", "level_4300_status"],
    }
    required = source_fields.get(source)
    if not required:
        return False
    return all(feature_fields.get(field) not in {None, "", "unknown", "unavailable"} for field in required)


def _source_tier_satisfies(*, source: str, source_refs: list[dict[str, Any]]) -> bool:
    if not source_refs:
        return False
    allowed = _allowed_source_tiers(source)
    if not allowed:
        return True
    return any(str(ref.get("source_tier") or _source_tier(ref)) in allowed for ref in source_refs)


def _allowed_source_tiers(source: str) -> set[str]:
    official_only = {
        "official_data",
        "fed_funds_futures",
        "etf_flows",
        "regional_etf_flows",
        "central_bank_reserves",
        "wgc_data",
        "imf_reserves",
        "pboc_gold_holdings",
        "positioning_data",
        "cot_report",
    }
    market_or_official = {
        "real_rates",
        "inflation_expectations",
        "yield_curve",
        "dxy",
        "oil_price",
        "energy_inventory",
        "fx_market",
        "shanghai_gold_premium",
        "china_gold_etf",
        "asia_physical_demand",
        "india_physical_demand",
        "cme_options",
        "institutional_forecasts",
        "treasury_yields",
        "vix",
        "equity_reaction",
        "xauusd_price",
        "market_candles",
        "technical_levels",
    }
    if source in official_only:
        return {"official"}
    if source in market_or_official:
        return {"official", "market_derived"}
    if source == "news_sources":
        return {"official", "market_derived", "supplemental"}
    return {"official", "market_derived", "supplemental", "manual"}


def _source_family_missing(source: str, explicit_missing: set[str]) -> bool:
    aliases = {
        "fed_funds_futures": {"official_data", "macro_data"},
        "treasury_yields": {"real_rates", "macro_data"},
        "inflation_expectations": {"macro_data"},
        "dxy": {"fx_market", "macro_data"},
        "regional_etf_flows": {"etf_flows"},
        "cme_options": {"positioning_data"},
        "cot_report": {"positioning_data"},
        "institutional_forecasts": {"positioning_data"},
        "wgc_data": {"central_bank_reserves"},
        "imf_reserves": {"central_bank_reserves"},
        "pboc_gold_holdings": {"central_bank_reserves"},
        "china_gold_etf": {"asia_physical_demand", "etf_flows"},
        "india_physical_demand": {"asia_physical_demand"},
        "market_candles": {"xauusd_price"},
        "technical_levels": {"xauusd_price"},
    }
    return bool(aliases.get(source, set()) & explicit_missing)


def _missing_required_fields(*, required_fields: list[str], ranking: dict[str, Any]) -> list[str]:
    feature_fields = ranking.get("feature_fields")
    if not isinstance(feature_fields, dict):
        return list(required_fields)
    return [field for field in required_fields if feature_fields.get(field) in {None, "", "unknown", "unavailable"}]


def _requirement_status(*, coverage_status: str, missing_sources: list[str], missing_fields: list[str]) -> str:
    if coverage_status == "missing":
        return "missing"
    if not missing_sources and not missing_fields:
        return "ready"
    return "partial"


def _development_gaps(*, mainline_id: str, missing_sources: list[str], missing_fields: list[str], readiness_status: str) -> list[str]:
    if readiness_status == "ready":
        return []
    label = str(MAINLINE_META[mainline_id]["label"])
    gaps: list[str] = []
    if missing_sources:
        gaps.append(f"{label}缺少数据源接入：{', '.join(missing_sources)}")
    if missing_fields:
        gaps.append(f"{label}缺少特征字段：{', '.join(missing_fields[:4])}{'...' if len(missing_fields) > 4 else ''}")
    return gaps


def _analysis_readiness(requirements: list[MainlineRequirement]) -> AnalysisReadiness:
    ready_count = sum(1 for item in requirements if item.readiness_status == "ready")
    partial_count = sum(1 for item in requirements if item.readiness_status == "partial")
    missing_count = sum(1 for item in requirements if item.readiness_status == "missing")
    total_count = len(requirements)
    if missing_count:
        status = "partial"
    elif partial_count:
        status = "partial"
    else:
        status = "ready"
    ratio = round((ready_count + (partial_count * 0.5)) / total_count, 2) if total_count else 0.0
    next_gaps = _unique(gap for item in requirements for gap in item.development_gaps)[:8]
    return AnalysisReadiness(
        status=status,
        ready_count=ready_count,
        partial_count=partial_count,
        missing_count=missing_count,
        total_count=total_count,
        coverage_ratio=ratio,
        next_gaps=next_gaps,
    )


def _architecture_gaps(requirements: list[MainlineRequirement]) -> list[str]:
    return _unique(gap for item in requirements for gap in item.development_gaps)[:12]


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
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
