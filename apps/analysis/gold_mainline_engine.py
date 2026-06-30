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
class GoldMacroOverview:
    status: str
    asset: str
    as_of: str | None
    phase: str
    dominant_mainline: str | None
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
    )
    theme_rankings = _theme_rankings(mainlines)
    covered_rows = [row for row in theme_rankings if row.get("coverage_status") == "covered"]
    dominant_mainline = _dominant_mainline(covered_rows)
    net_bias = _net_bias(links)
    conflict = _driver_conflict(links=links, net_bias=net_bias, source_refs=source_refs)
    chain = _war_oil_rate_chain(links)
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


def _apply_context_features(*, mainlines: list[dict[str, Any]], macro_context: dict[str, Any], market_context: dict[str, Any]) -> list[dict[str, Any]]:
    feature_updates = {
        "real_rates_usd": _real_rates_usd_features(macro_context),
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
    if not any([real_10y, dxy, us10y, breakeven]):
        return None
    real_rate_level = _number(real_10y.get("value") if real_10y else None)
    real_rate_change = _number(real_10y.get("weekly_change") if real_10y else None)
    dxy_change = _number(dxy.get("weekly_change") if dxy else None)
    fields = {
        "real_rate_level": real_rate_level,
        "real_rate_trend": _trend_from_change(real_rate_change),
        "dxy_trend": _trend_from_change(dxy_change),
        "nominal_yield_pressure": _yield_pressure(_number(us10y.get("weekly_change") if us10y else None)),
        "dollar_liquidity_pressure": _dollar_pressure(dxy_change),
        "us10y_level": _number(us10y.get("value") if us10y else None),
        "breakeven_10y_level": _number(breakeven.get("value") if breakeven else None),
    }
    available_sources = []
    if real_10y:
        available_sources.append("real_rates")
    if breakeven:
        available_sources.append("inflation_expectations")
    if dxy:
        available_sources.append("dxy")
    direction = "bearish" if fields["real_rate_trend"] == "rising" or fields["dxy_trend"] == "rising" else "bullish" if fields["real_rate_trend"] == "falling" and fields["dxy_trend"] != "rising" else "neutral"
    return {
        "feature_fields": fields,
        "source_refs": _macro_source_refs(macro_context=macro_context, symbols=["REAL_10Y", "DFII10", "DXY", "US10Y", "DGS10", "BREAKEVEN_10Y", "T10YIE"]),
        "missing_data": [item for item in ["real_rates", "inflation_expectations", "dxy"] if item not in available_sources],
        "verification_status": "official_confirmed" if "real_rates" in available_sources and "dxy" in available_sources else "multi_source",
        "freshness": "fresh",
        "direction": direction,
        "summary": "实际利率、通胀预期与 DXY 已由宏观快照接入，用于判断黄金估值压力。",
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
        return [dict(ref) for ref in refs if isinstance(ref, dict)]
    source = market_context.get("source") or market_context.get("interpretation")
    return [{"source": str(source or "market_context"), "source_ref": "XAUUSD"}] if market_context else []


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


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dominant_mainline(covered_rows: list[dict[str, Any]]) -> str | None:
    if not covered_rows:
        return None
    sorted_rows = sorted(
        covered_rows,
        key=lambda row: (-(float(row.get("theme_score") or row.get("score") or 0.0)), int(row.get("rank") or 99)),
    )
    return str(sorted_rows[0].get("mainline_id") or sorted_rows[0].get("mainline"))


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


def _war_oil_rate_chain(links: list[dict[str, Any]]) -> TransmissionChainSummary | None:
    chain_links = [link for link in links if "geopolitics_to_oil_to_rates" in (link.get("transmission_path_ids") or [])]
    if not chain_links:
        return None
    source_refs = _merge_source_refs(link.get("source_refs") or [] for link in chain_links)
    conclusion_code, conclusion_label, net_effect = _war_oil_rate_conclusion(chain_links)
    return TransmissionChainSummary(
        path_id="geopolitics_to_oil_to_rates",
        label="战争-石油-通胀预期-美联储-实际利率-黄金",
        status="partial" if any(str(link.get("verification_status")) != "official_confirmed" for link in chain_links) else "available",
        conclusion_code=conclusion_code,
        conclusion_label=conclusion_label,
        net_effect=net_effect,
        dominant_driver=_dominant_driver_value(
            _unique(driver for link in chain_links for driver in [*(link.get("bearish_drivers") or []), *(link.get("bullish_drivers") or [])])
        ),
        summary=f"{conclusion_label}：地缘事件通过油价和通胀预期影响美联储路径，同时保留避险买盘。",
        steps=[
            TransmissionChainStep("geopolitical_status", "地缘战争事件", source_refs=source_refs),
            TransmissionChainStep("oil_status", "Brent / WTI 与供应风险", source_refs=source_refs),
            TransmissionChainStep("inflation_expectation_status", "通胀预期", source_refs=source_refs),
            TransmissionChainStep("fed_expectation_status", "美联储预期", source_refs=source_refs),
            TransmissionChainStep("real_rate_status", "实际利率", source_refs=source_refs),
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


def _war_oil_rate_conclusion(chain_links: list[dict[str, Any]]) -> tuple[str, str, str]:
    bullish = _unique(driver for link in chain_links for driver in link.get("bullish_drivers") or [])
    bearish = _unique(driver for link in chain_links for driver in link.get("bearish_drivers") or [])
    has_safe_haven = "safe_haven_bid" in bullish
    has_rate_pressure = bool({"oil_inflation_rate_pressure", "higher_for_longer_rate_pressure", "usd_strength_pressure"} & set(bearish))
    directions = [str((link.get("direction_by_asset") or {}).get("XAUUSD") or "unknown") for link in chain_links]
    if not chain_links or all(direction in {"", "unknown"} for direction in directions):
        return "D", "数据不足，待验证", "unknown"
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
    return "D", "数据不足，待验证", net_effect


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
        "analysis_chain": ["名义利率", "通胀预期", "实际利率", "DXY/美元流动性", "黄金估值压力"],
        "required_sources": ["real_rates", "inflation_expectations", "dxy"],
        "required_fields": ["real_rate_level", "real_rate_trend", "dxy_trend", "nominal_yield_pressure", "dollar_liquidity_pressure"],
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
    if isinstance(feature_fields, dict):
        explicit_missing = {
            source
            for source in explicit_missing
            if not _source_satisfied_by_features(source=source, feature_fields=feature_fields)
        }
    if coverage_status == "missing":
        return [
            source
            for source in required_sources
            if not _source_satisfied_by_features(source=source, feature_fields=feature_fields if isinstance(feature_fields, dict) else {})
        ]
    return [source for source in required_sources if source in explicit_missing or _source_family_missing(source, explicit_missing)]


def _source_satisfied_by_features(*, source: str, feature_fields: dict[str, Any]) -> bool:
    source_fields = {
        "real_rates": ["real_rate_level", "real_rate_trend"],
        "inflation_expectations": ["breakeven_10y_level"],
        "dxy": ["dxy_trend"],
        "xauusd_price": ["gold_spot_price"],
        "market_candles": ["gold_spot_price"],
        "technical_levels": ["level_3900_status", "level_4000_status", "level_4100_4120_status", "level_4300_status"],
    }
    required = source_fields.get(source)
    if not required:
        return False
    return all(feature_fields.get(field) not in {None, "", "unknown", "unavailable"} for field in required)


def _source_family_missing(source: str, explicit_missing: set[str]) -> bool:
    aliases = {
        "fed_funds_futures": {"official_data", "macro_data"},
        "treasury_yields": {"real_rates", "macro_data"},
        "inflation_expectations": {"real_rates", "macro_data"},
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
