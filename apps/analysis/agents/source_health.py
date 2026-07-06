from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


P0_SOURCE_IDS = [
    "xauusd_price",
    "dxy",
    "treasury_2y",
    "treasury_10y",
    "tips_10y",
    "fed_macro_events",
    "brent_wti",
    "geopolitical_news",
    "technical_levels",
]

P1_SOURCE_IDS = [
    "breakeven_inflation",
    "fedwatch_ois",
    "gold_etf_flows",
    "comex_cot",
    "cme_options",
    "vix_risk_assets",
    "eia_inventory",
]

P2_SOURCE_IDS = [
    "central_bank_buying",
    "pboc_gold_reserves",
    "shanghai_gold_premium",
    "usdcnh",
    "india_physical_demand",
    "asia_etf_flows",
]


SOURCE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "xauusd_price": {
        "priority": "P0",
        "label": "XAUUSD / gold spot",
        "aliases": {"xauusd", "gold_spot", "market_context", "xauusd_price"},
        "mainlines": ["gold_technical_levels"],
        "allowed_staleness_seconds": 60 * 60,
    },
    "dxy": {
        "priority": "P0",
        "label": "DXY",
        "aliases": {"dxy", "DXY"},
        "mainlines": ["real_rates_usd"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "treasury_2y": {
        "priority": "P0",
        "label": "2Y Treasury",
        "aliases": {"treasury_2y", "DGS2", "us2y"},
        "mainlines": ["fed_policy_path", "real_rates_usd"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "treasury_10y": {
        "priority": "P0",
        "label": "10Y Treasury",
        "aliases": {"treasury_10y", "US10Y", "DGS10", "us10y"},
        "mainlines": ["real_rates_usd"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "tips_10y": {
        "priority": "P0",
        "label": "10Y TIPS real yield",
        "aliases": {"tips_10y", "REAL_10Y", "DFII10", "real_rates"},
        "mainlines": ["real_rates_usd"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "fed_macro_events": {
        "priority": "P0",
        "label": "Fed / FOMC / CPI / PCE / NFP",
        "aliases": {"fed_macro_events", "official_data", "policy_context", "macro_snapshot"},
        "mainlines": ["fed_policy_path"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
    "brent_wti": {
        "priority": "P0",
        "label": "Brent / WTI",
        "aliases": {"brent_wti", "brent", "wti", "oil_context", "oil_price"},
        "mainlines": ["oil_prices", "geopolitical_war_risk"],
        "allowed_staleness_seconds": 60 * 60,
    },
    "geopolitical_news": {
        "priority": "P0",
        "label": "Jin10 / geopolitical news",
        "aliases": {"geopolitical_news", "jin10", "news_sources", "geopolitical_context"},
        "mainlines": ["geopolitical_war_risk"],
        "allowed_staleness_seconds": 60 * 60 * 6,
    },
    "technical_levels": {
        "priority": "P0",
        "label": "technical levels",
        "aliases": {"technical_levels", "market_candles", "gold_technical_levels"},
        "mainlines": ["gold_technical_levels"],
        "allowed_staleness_seconds": 60 * 60,
    },
    "breakeven_inflation": {
        "priority": "P1",
        "label": "breakeven inflation",
        "aliases": {"breakeven_inflation", "BREAKEVEN_10Y", "T10YIE", "inflation_expectations"},
        "mainlines": ["real_rates_usd", "oil_prices"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "fedwatch_ois": {
        "priority": "P1",
        "label": "FedWatch / OIS",
        "aliases": {"fedwatch_ois", "fed_funds_futures", "ois"},
        "mainlines": ["fed_policy_path"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "gold_etf_flows": {
        "priority": "P1",
        "label": "WGC ETF / GLD / IAU flows",
        "aliases": {"gold_etf_flows", "etf_flows", "flow_context"},
        "mainlines": ["etf_flows"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
    "comex_cot": {
        "priority": "P1",
        "label": "COMEX COT",
        "aliases": {"comex_cot", "cot_report", "positioning_data"},
        "mainlines": ["institutional_sentiment"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
    "cme_options": {
        "priority": "P1",
        "label": "CME options",
        "aliases": {"cme_options", "options_analysis", "positioning_context"},
        "mainlines": ["institutional_sentiment"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "vix_risk_assets": {
        "priority": "P1",
        "label": "VIX / S&P 500 / Nasdaq",
        "aliases": {"vix_risk_assets", "vix", "equity_reaction"},
        "mainlines": ["geopolitical_war_risk"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "eia_inventory": {
        "priority": "P1",
        "label": "EIA inventory",
        "aliases": {"eia_inventory", "energy_inventory"},
        "mainlines": ["oil_prices"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
    "central_bank_buying": {
        "priority": "P2",
        "label": "central bank buying",
        "aliases": {"central_bank_buying", "central_bank_reserves", "reserve_context", "wgc_data"},
        "mainlines": ["central_bank_gold"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 45,
    },
    "pboc_gold_reserves": {
        "priority": "P2",
        "label": "PBOC gold reserves",
        "aliases": {"pboc_gold_reserves", "pboc_gold_holdings"},
        "mainlines": ["central_bank_gold"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 45,
    },
    "shanghai_gold_premium": {
        "priority": "P2",
        "label": "Shanghai gold premium",
        "aliases": {"shanghai_gold_premium"},
        "mainlines": ["china_asia_demand"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
    "usdcnh": {
        "priority": "P2",
        "label": "USD/CNH",
        "aliases": {"usdcnh", "USDCNH", "fx_market"},
        "mainlines": ["china_asia_demand"],
        "allowed_staleness_seconds": 60 * 60 * 24,
    },
    "india_physical_demand": {
        "priority": "P2",
        "label": "India physical demand",
        "aliases": {"india_physical_demand"},
        "mainlines": ["china_asia_demand"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 30,
    },
    "asia_etf_flows": {
        "priority": "P2",
        "label": "Asia ETF flows",
        "aliases": {"asia_etf_flows", "regional_etf_flows", "asia_context"},
        "mainlines": ["china_asia_demand", "etf_flows"],
        "allowed_staleness_seconds": 60 * 60 * 24 * 7,
    },
}


MAINLINE_REQUIRED_SOURCES: dict[str, list[str]] = {
    "fed_policy_path": ["treasury_2y", "fed_macro_events", "fedwatch_ois"],
    "real_rates_usd": ["dxy", "treasury_10y", "tips_10y", "breakeven_inflation"],
    "oil_prices": ["brent_wti", "eia_inventory"],
    "geopolitical_war_risk": ["geopolitical_news", "brent_wti", "vix_risk_assets"],
    "etf_flows": ["gold_etf_flows", "asia_etf_flows"],
    "institutional_sentiment": ["comex_cot", "cme_options"],
    "central_bank_gold": ["central_bank_buying", "pboc_gold_reserves"],
    "china_asia_demand": ["shanghai_gold_premium", "usdcnh", "india_physical_demand", "asia_etf_flows"],
    "gold_technical_levels": ["xauusd_price", "technical_levels"],
}

CORE_RATE_USD_STACK_SOURCE_IDS = ("dxy", "treasury_10y", "tips_10y")


@dataclass(frozen=True)
class SourceFreshness:
    status: str
    last_updated: str | None = None
    freshness_seconds: int | None = None
    allowed_staleness_seconds: int | None = None
    source_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", [])}


@dataclass(frozen=True)
class MainlineHealthImpact:
    status: str
    missing_required_data: list[str]
    stale_required_data: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceHealthSnapshot:
    overall_status: str
    as_of: str
    p0_missing: list[str]
    p1_missing: list[str]
    p2_missing: list[str]
    stale_sources: list[str]
    fresh_sources: list[str]
    source_freshness: dict[str, SourceFreshness]
    mainline_impact: dict[str, MainlineHealthImpact]
    can_build_gold_macro_overview: bool
    can_emit_strong_conclusion: bool
    blocked_mainlines: list[str]
    degraded_mainlines: list[str]
    blocking_reasons: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "as_of": self.as_of,
            "p0_missing": self.p0_missing,
            "p1_missing": self.p1_missing,
            "p2_missing": self.p2_missing,
            "stale_sources": self.stale_sources,
            "fresh_sources": self.fresh_sources,
            "source_freshness": {key: value.to_dict() for key, value in self.source_freshness.items()},
            "mainline_impact": {key: value.to_dict() for key, value in self.mainline_impact.items()},
            "can_build_gold_macro_overview": self.can_build_gold_macro_overview,
            "can_emit_strong_conclusion": self.can_emit_strong_conclusion,
            "blocked_mainlines": self.blocked_mainlines,
            "degraded_mainlines": self.degraded_mainlines,
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
        }


def build_gold_v3_source_health(
    source_statuses: Any,
    *,
    as_of: str | None = None,
    gold_macro_overview: Any | None = None,
) -> SourceHealthSnapshot:
    """Build deterministic SourceHealthAgent output from existing source status cards."""

    now = _parse_dt(as_of) or datetime.now(timezone.utc)
    as_of_value = as_of or now.isoformat()
    by_alias = _index_sources(source_statuses)
    source_freshness: dict[str, SourceFreshness] = {}
    p0_missing: list[str] = []
    p1_missing: list[str] = []
    p2_missing: list[str] = []
    stale_sources: list[str] = []
    fresh_sources: list[str] = []

    for source_id, requirement in SOURCE_REQUIREMENTS.items():
        source = _lookup_source(requirement=requirement, by_alias=by_alias)
        freshness = _source_freshness(source_id=source_id, requirement=requirement, source=source, now=now)
        source_freshness[source_id] = freshness
        if freshness.status == "missing":
            _append_missing(source_id=source_id, priority=str(requirement["priority"]), p0=p0_missing, p1=p1_missing, p2=p2_missing)
        elif freshness.status == "stale":
            stale_sources.append(source_id)
        else:
            fresh_sources.append(source_id)

    mainline_impact = {
        mainline_id: _mainline_health_impact(
            source_ids=source_ids,
            source_freshness=source_freshness,
        )
        for mainline_id, source_ids in MAINLINE_REQUIRED_SOURCES.items()
    }

    blocked_mainlines = [
        mainline_id
        for mainline_id, impact in mainline_impact.items()
        if impact.status == "blocked"
    ]
    degraded_mainlines = [
        mainline_id
        for mainline_id, impact in mainline_impact.items()
        if impact.status == "degraded"
    ]
    core_unavailable = [
        source_id
        for source_id in CORE_RATE_USD_STACK_SOURCE_IDS
        if source_freshness[source_id].status in {"missing", "stale"}
    ]
    blocking_reasons: list[str] = []
    if source_freshness["xauusd_price"].status in {"missing", "stale"}:
        blocking_reasons.append("global P0 source unavailable: xauusd_price")
    if len(core_unavailable) == len(CORE_RATE_USD_STACK_SOURCE_IDS):
        blocking_reasons.append(f"core rate/USD stack unavailable: {', '.join(core_unavailable)}")
    blocking_reasons.extend(
        _strong_conclusion_blockers(
            gold_macro_overview=gold_macro_overview,
            has_global_blocker=bool(blocking_reasons),
        )
    )

    warnings = [f"Mainline-scoped P0 source missing: {source_id}" for source_id in p0_missing]
    warnings.extend(f"Mainline-scoped P0 source stale: {source_id}" for source_id in stale_sources if source_id in P0_SOURCE_IDS)
    warnings.extend(f"P1 source missing: {source_id}" for source_id in p1_missing)
    warnings.extend(f"P2 source missing: {source_id}" for source_id in p2_missing)
    warnings.extend(f"Non-P0 source stale: {source_id}" for source_id in stale_sources if source_id not in P0_SOURCE_IDS)

    if blocking_reasons:
        overall_status = "blocked"
    elif p0_missing or p1_missing or p2_missing or stale_sources:
        overall_status = "degraded"
    else:
        overall_status = "ready"

    return SourceHealthSnapshot(
        overall_status=overall_status,
        as_of=as_of_value,
        p0_missing=p0_missing,
        p1_missing=p1_missing,
        p2_missing=p2_missing,
        stale_sources=stale_sources,
        fresh_sources=fresh_sources,
        source_freshness=source_freshness,
        mainline_impact=mainline_impact,
        can_build_gold_macro_overview=not blocking_reasons,
        can_emit_strong_conclusion=not blocked_mainlines,
        blocked_mainlines=blocked_mainlines,
        degraded_mainlines=degraded_mainlines,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
    )


def _index_sources(source_statuses: Any) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]]
    if isinstance(source_statuses, dict):
        raw_rows = source_statuses.get("sources") if isinstance(source_statuses.get("sources"), list) else None
        if raw_rows is None:
            raw_rows = [
                {**dict(value), "source_key": key} if isinstance(value, dict) else {"source_key": key, "status": value}
                for key, value in source_statuses.items()
            ]
    elif isinstance(source_statuses, list):
        raw_rows = source_statuses
    else:
        raw_rows = []
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        keys = {
            row.get("source_id"),
            row.get("source_key"),
            row.get("key"),
            row.get("symbol"),
            row.get("name"),
            row.get("artifact_type"),
        }
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        keys.update({metadata.get("source_id"), metadata.get("source_key"), metadata.get("symbol")})
        for key in keys:
            if key not in {None, ""}:
                index[str(key).strip()] = row
                index[str(key).strip().lower()] = row
    return index


def _lookup_source(*, requirement: dict[str, Any], by_alias: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for alias in requirement.get("aliases") or []:
        source = by_alias.get(str(alias)) or by_alias.get(str(alias).lower())
        if source:
            return source
    return None


def _source_freshness(*, source_id: str, requirement: dict[str, Any], source: dict[str, Any] | None, now: datetime) -> SourceFreshness:
    allowed = int(requirement.get("allowed_staleness_seconds") or 0)
    if not source:
        return SourceFreshness(status="missing", allowed_staleness_seconds=allowed)

    source_status = _source_status(source)
    updated_at = _updated_at(source)
    freshness_seconds = _freshness_seconds(updated_at=updated_at, now=now)
    if source_status == "missing":
        status = "missing"
    elif source_status == "stale" or (freshness_seconds is not None and allowed and freshness_seconds > allowed):
        status = "stale"
    elif source_status in {"ready", "fresh"}:
        status = "fresh"
    else:
        status = "stale"

    return SourceFreshness(
        status=status,
        last_updated=updated_at,
        freshness_seconds=freshness_seconds,
        allowed_staleness_seconds=allowed,
        source_ref=_source_ref(source, fallback=source_id),
    )


def _source_status(source: dict[str, Any]) -> str:
    values = [
        source.get("readiness_state"),
        source.get("health_state"),
        source.get("freshness_status"),
        source.get("status"),
        (source.get("metadata") or {}).get("readiness_state") if isinstance(source.get("metadata"), dict) else None,
        (source.get("metadata") or {}).get("health_state") if isinstance(source.get("metadata"), dict) else None,
    ]
    normalized = {str(value).strip().lower() for value in values if value not in {None, ""}}
    if normalized & {"missing", "not_connected", "unavailable", "error", "failed", "blocked", "not_configured"}:
        return "missing"
    if normalized & {"stale", "degraded", "partial", "warn", "cooldown", "manual"}:
        return "stale"
    if normalized & {"ready", "healthy", "fresh", "ok", "success", "available", "enabled", "active", "configured", "connected"}:
        return "ready"
    if source.get("analysis_ready") or source.get("parsed") or source.get("raw_ingested"):
        return "ready"
    return "missing"


def _updated_at(source: dict[str, Any]) -> str | None:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    for key in ("last_updated", "updated_at", "as_of", "latest_health_at", "data_date"):
        value = source.get(key) or metadata.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _freshness_seconds(*, updated_at: str | None, now: datetime) -> int | None:
    parsed = _parse_dt(updated_at)
    if not parsed:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _source_ref(source: dict[str, Any], *, fallback: str) -> str:
    refs = source.get("source_refs")
    if isinstance(refs, list) and refs and isinstance(refs[0], dict):
        value = refs[0].get("source_ref") or refs[0].get("path")
        if value not in {None, ""}:
            return str(value)
    return str(source.get("source_ref") or source.get("artifact_path") or source.get("path") or fallback)


def _append_missing(*, source_id: str, priority: str, p0: list[str], p1: list[str], p2: list[str]) -> None:
    if priority == "P0":
        p0.append(source_id)
    elif priority == "P1":
        p1.append(source_id)
    else:
        p2.append(source_id)


def _mainline_health_impact(*, source_ids: list[str], source_freshness: dict[str, SourceFreshness]) -> MainlineHealthImpact:
    missing = [source_id for source_id in source_ids if source_freshness[source_id].status == "missing"]
    stale = [source_id for source_id in source_ids if source_freshness[source_id].status == "stale"]
    has_p0_missing = any(source_id in P0_SOURCE_IDS for source_id in missing)
    has_p0_stale = any(source_id in P0_SOURCE_IDS for source_id in stale)
    if has_p0_missing or has_p0_stale:
        status = "blocked"
        reason = "P0 数据缺失或过期，不能输出完整主线判断。"
    elif missing or stale:
        status = "degraded"
        reason = "P1/P2 数据缺失或过期，只能降级分析。"
    else:
        status = "ready"
        reason = "关键数据源新鲜且可用。"
    return MainlineHealthImpact(
        status=status,
        missing_required_data=missing,
        stale_required_data=stale,
        reason=reason,
    )


def _strong_conclusion_blockers(*, gold_macro_overview: Any | None, has_global_blocker: bool) -> list[str]:
    if not gold_macro_overview or not has_global_blocker:
        return []
    overview = gold_macro_overview.to_dict() if hasattr(gold_macro_overview, "to_dict") else dict(gold_macro_overview)
    strong_values = {"strong_uptrend", "strong_bullish", "strong_downtrend", "strong_bearish"}
    values = {
        str(overview.get("phase") or "").lower(),
        str(overview.get("net_bias") or "").lower(),
        str(overview.get("one_line_conclusion") or "").lower(),
    }
    if values & strong_values or any("strong" in value for value in values):
        return ["P0 source gap conflicts with strong GoldMacroOverview conclusion"]
    return []
