"""Deterministic execution zones around research key levels.

The module uses only observed price-width inputs.  Missing spread or source
dispersion remains missing; neither is replaced by a guessed constant.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping, Sequence

ZONE_SCHEMA_VERSION = "execution_zones.v1"
ZONE_WIDTH_POLICY_VERSION = "execution_zones.width_policy.v1"
_WIDTH_COEFFICIENTS = {
    "atr": 0.10,
    "spread": 1.00,
    "intraday_vol": 0.50,
    "source_dispersion": 1.00,
}
_DEFAULT_ROLE_MULTIPLIERS = {
    "support": 1.0,
    "resistance": 1.0,
    "pivot": 0.75,
    "reclaim": 0.85,
    "ma": 0.75,
    "ma20": 0.75,
    "event_low": 1.0,
    "event_high": 1.0,
}
_NUMERIC_KEYS = {
    "atr": ("atr14", "atr_14", "atr", "daily_atr"),
    "spread": ("spread", "bid_ask_spread", "spread_usd", "quote_spread"),
    "intraday_vol": ("intradayvol", "intraday_vol", "intraday_volatility", "realized_vol", "atr_intraday"),
    "source_dispersion": ("source_dispersion", "source_dispersion_usd", "dispersion"),
}


def build_execution_zones(
    snapshot: Mapping[str, Any] | None,
    levels: Sequence[Mapping[str, Any]] | None = None,
    session_quality: Mapping[str, Any] | None = None,
    *,
    role_multipliers: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build bounded zones while preserving the raw level projection.

    ``levels`` is optional for callers that have not yet projected levels; in
    that case the existing pure ``build_key_levels`` function is used.  A
    zone is displayable when at least one positive observed width input exists
    and the level is a current spot level.  The confidence values are rule
    scores and are never probabilities.
    """

    source = snapshot if isinstance(snapshot, Mapping) else {}
    if levels is None:
        from apps.features.research.levels import build_key_levels

        levels = build_key_levels(dict(source), session_quality=session_quality)
    raw_levels = [dict(item) for item in (levels or ()) if isinstance(item, Mapping)]
    session = session_quality if isinstance(session_quality, Mapping) else _session_from_snapshot(source)
    inputs = _extract_inputs(source)
    multipliers = {**_DEFAULT_ROLE_MULTIPLIERS, **_safe_multipliers(role_multipliers)}
    positive_inputs = {name: value for name, value in inputs["values"].items() if _positive(value)}
    method = _zone_method(positive_inputs)
    missing = [name for name in inputs["values"] if name not in positive_inputs]
    holiday_multiplier = _holiday_multiplier(session)
    zone_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for level in raw_levels:
        if str(level.get("instrument") or "").lower() not in {"xauusd spot", "xauusd_spot", "spot"}:
            excluded.append({"price": level.get("price"), "reason": "futures_or_non_spot_level"})
            continue
        price = _number(level.get("price"))
        if price is None:
            excluded.append({"price": level.get("price"), "reason": "invalid_level_price"})
            continue
        role = str(level.get("role") or "pivot").lower()
        level_status = _canonical_level_status(level.get("status"))
        role_kind = _role_kind(role, level.get("source_type"))
        role_factor = (
            multipliers.get(role_kind, multipliers.get(role, 1.0))
            if role == "pivot" and role_kind != "pivot"
            else multipliers.get(role, multipliers.get(role_kind, 1.0))
        )
        if not positive_inputs:
            zone_rows.append(_unavailable_zone(level, method, missing))
            continue
        component_widths = {
            name: round(value * _WIDTH_COEFFICIENTS.get(name, 1.0) * role_factor, 6)
            for name, value in positive_inputs.items()
        }
        width = max(component_widths.values())
        lower = round(price - width, 6)
        upper = round(price + width, 6)
        display_lower, display_upper, display_tick = _display_bounds(lower, upper, width)
        zone_status = "unavailable" if level_status in {"Stale", "Invalidated"} else "available"
        zone_confidence = _zone_confidence(inputs, level, holiday_multiplier)
        eligible = (
            bool(level.get("eligible_for_target", level_status == "Active"))
            and level_status == "Active"
            and zone_status == "available"
        )
        zone_rows.append(
            {
                "price": price,
                "instrument": "XAUUSD spot",
                "role": role,
                "level_status": level_status,
                "source_type": level.get("source_type"),
                "source_date": level.get("source_date"),
                "source_refs": deepcopy(level.get("source_refs") or []),
                "confidence": zone_confidence,
                "zone_status": zone_status,
                "zone_method": method,
                "width_policy_version": ZONE_WIDTH_POLICY_VERSION,
                "inputs": deepcopy(inputs["values"]),
                "component_widths": component_widths,
                "width": width,
                "lower": lower,
                "upper": upper,
                "bounds": {"lower": lower, "upper": upper},
                "raw_lower": lower,
                "raw_upper": upper,
                "raw_bounds": {"lower": lower, "upper": upper},
                "display_lower": display_lower,
                "display_upper": display_upper,
                "display_tick": display_tick,
                "display_label": f"{display_lower:g}-{display_upper:g}",
                "display_bounds": {"lower": display_lower, "upper": display_upper},
                "activation": _activation(role_kind, display_lower, display_upper),
                "invalidation": _invalidation(role_kind, display_lower, display_upper),
                "eligible_for_target": eligible,
                "is_target": eligible,
                "holiday_confidence_multiplier": holiday_multiplier,
                "raw_level": deepcopy(level),
            }
        )

    available_zones = [row for row in zone_rows if row.get("zone_status") == "available"]
    status = "available" if available_zones else "unavailable" if not positive_inputs else "partial"
    source_refs = _dedupe_refs(
        [
            *_refs(inputs.get("source_refs")),
            *[ref for row in raw_levels for ref in _refs(row.get("source_refs"))],
            *_refs(session.get("source_refs")),
        ]
    )
    return {
        "schema_version": ZONE_SCHEMA_VERSION,
        "status": status,
        "zone_method": method,
        "width_policy_version": ZONE_WIDTH_POLICY_VERSION,
        "width_coefficients": deepcopy(_WIDTH_COEFFICIENTS),
        "inputs": inputs["values"],
        "input_methods": inputs["methods"],
        "missing_inputs": missing,
        "confidence": _aggregate_confidence(zone_rows, holiday_multiplier),
        "confidence_note": "zone confidence is a deterministic input-coverage score, not a calibrated probability",
        "holiday_confidence_multiplier": holiday_multiplier,
        "session_class": session.get("session_class") if isinstance(session, Mapping) else None,
        "zones": zone_rows,
        "levels": zone_rows,
        "raw_levels": deepcopy(raw_levels),
        "excluded_levels": excluded,
        "source_refs": source_refs,
    }


def _extract_inputs(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    technical_section = snapshot.get("technical")
    technical = _section_data(technical_section)
    execution = technical.get("execution") if isinstance(technical.get("execution"), Mapping) else {}
    quote = technical.get("quote") if isinstance(technical.get("quote"), Mapping) else {}
    anchor = technical.get("spot_anchor") if isinstance(technical.get("spot_anchor"), Mapping) else {}
    top_anchor = snapshot.get("spot_anchor") if isinstance(snapshot.get("spot_anchor"), Mapping) else {}
    research = snapshot.get("daily_research") if isinstance(snapshot.get("daily_research"), Mapping) else {}
    research_anchor = research.get("spot_anchor") if isinstance(research.get("spot_anchor"), Mapping) else {}
    objects = [technical, execution, quote, anchor, top_anchor, research_anchor, snapshot]
    values: dict[str, float | None] = {}
    methods: dict[str, str] = {}
    for name, keys in _NUMERIC_KEYS.items():
        value, method = _first_numeric(objects, keys)
        if value is None and name == "intraday_vol":
            value = _derive_intraday_vol(technical, research)
            method = "completed_ohlc_range_mean" if value is not None else None
        values[name] = value
        if method:
            methods[name] = method
    outer_refs = _refs(technical_section.get("source_refs")) if isinstance(technical_section, Mapping) else []
    refs = [*outer_refs, *_refs(technical.get("source_refs")), *_refs(snapshot.get("source_refs"))]
    return {"values": values, "methods": methods, "source_refs": _dedupe_refs(refs)}


def _derive_intraday_vol(technical: Mapping[str, Any], research: Mapping[str, Any] | None = None) -> float | None:
    execution = technical.get("execution_timeframes")
    if not isinstance(execution, Mapping) and isinstance(research, Mapping):
        execution_section = research.get("execution_timeframes")
        execution = execution_section.get("timeframes") if isinstance(execution_section, Mapping) else execution_section
    if isinstance(execution, Mapping) and isinstance(execution.get("timeframes"), Mapping):
        execution = execution["timeframes"]
    if not isinstance(execution, Mapping):
        return None
    candidates: list[Mapping[str, Any]] = []
    for key in ("15m", "15min", "5m", "5min"):
        item = execution.get(key)
        if isinstance(item, Mapping):
            candidates.append(item)
    for item in candidates:
        bars = item.get("bars")
        if not isinstance(bars, Sequence) or isinstance(bars, (str, bytes, bytearray)):
            continue
        ranges = []
        for bar in list(bars)[-20:]:
            if not isinstance(bar, Mapping):
                continue
            high, low = _number(bar.get("high")), _number(bar.get("low"))
            if high is not None and low is not None and high >= low:
                ranges.append(high - low)
        if ranges:
            return round(sum(ranges) / len(ranges), 6)
    return None


def _first_numeric(objects: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> tuple[float | None, str | None]:
    for obj in objects:
        for key in keys:
            if key not in obj:
                continue
            value = _number_allow_zero(obj.get(key))
            if value is not None:
                return value, f"observed:{key}"
    return None, None


def _unavailable_zone(level: Mapping[str, Any], method: str, missing: Sequence[str]) -> dict[str, Any]:
    level_status = _canonical_level_status(level.get("status"))
    return {
        "price": _number(level.get("price")),
        "instrument": "XAUUSD spot",
        "role": level.get("role"),
        "level_status": level_status,
        "source_type": level.get("source_type"),
        "source_date": level.get("source_date"),
        "source_refs": deepcopy(level.get("source_refs") or []),
        "confidence": 0.0,
        "zone_status": "unavailable",
        "zone_method": method,
        "width_policy_version": ZONE_WIDTH_POLICY_VERSION,
        "inputs": {},
        "component_widths": {},
        "width": None,
        "lower": None,
        "upper": None,
        "bounds": None,
        "raw_lower": None,
        "raw_upper": None,
        "raw_bounds": None,
        "display_lower": None,
        "display_upper": None,
        "display_tick": None,
        "display_label": None,
        "display_bounds": None,
        "activation": "缺少正的观测波动输入，暂不生成执行区间。",
        "invalidation": "获得有效 ATR、spread、intradayvol 或 source dispersion 后重新计算。",
        "eligible_for_target": False,
        "is_target": False,
        "raw_level": deepcopy(dict(level)),
        "missing_inputs": list(missing),
    }


def _activation(role: str, lower: float, upper: float) -> str:
    if role == "support":
        return f"价格进入 {lower:.2f}-{upper:.2f} 支撑观察区，等待收盘防守确认。"
    if role == "resistance":
        return f"价格进入 {lower:.2f}-{upper:.2f} 阻力观察区，等待突破或拒绝确认。"
    if role == "reclaim":
        return f"价格回到 {lower:.2f}-{upper:.2f} 收复观察区，等待收盘站稳确认。"
    if role in {"ma", "ma20"}:
        return f"价格接近 {lower:.2f}-{upper:.2f} 均线观察区，等待趋势过滤确认。"
    return f"价格进入 {lower:.2f}-{upper:.2f} 枢轴观察区，等待方向确认。"


def _invalidation(role: str, lower: float, upper: float) -> str:
    if role == "support":
        return f"收盘有效跌破 {lower:.2f}，支撑区失效。"
    if role == "resistance":
        return f"收盘有效站上 {upper:.2f}，阻力区失效并重新评估角色。"
    if role == "reclaim":
        return f"收盘重新跌回 {lower:.2f} 下方，收复区失效。"
    if role in {"ma", "ma20"}:
        return f"收盘有效脱离 {lower:.2f}-{upper:.2f}，均线观察区失效。"
    return f"收盘脱离 {lower:.2f}-{upper:.2f} 枢轴区，当前区间失效。"


def _role_kind(role: str, source_type: Any = None) -> str:
    source = str(source_type or "").lower()
    if "ma20" in source or "moving_average" in source:
        return "ma20"
    if role in {"reclaim", "recovery", "reclaim_level"}:
        return "reclaim"
    if role in {"ma", "ma20", "moving_average"}:
        return "ma20"
    if role in {"event_low", "support", "primary_support"}:
        return "support"
    if role in {"event_high", "resistance", "primary_resistance"}:
        return "resistance"
    return "pivot"


def _canonical_level_status(value: Any) -> str:
    normalized = str(value or "Active").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"stale", "outdated", "out_of_date"}:
        return "Stale"
    if normalized in {"invalidated", "invalid", "void", "revoked", "expired", "expiry"}:
        return "Invalidated"
    if normalized in {"conditional", "partial", "unavailable", "blocked", "failed", "error", "degraded"}:
        return "Conditional"
    if normalized in {"active", "available", "current"}:
        return "Active"
    return str(value or "Active")


def _zone_method(inputs: Mapping[str, float | None]) -> str:
    names = [name for name, value in inputs.items() if _positive(value)]
    if not names:
        return "unavailable_no_positive_observed_width"
    terms = "_".join(f"{name}{_WIDTH_COEFFICIENTS.get(name, 1.0):g}" for name in names)
    return f"{ZONE_WIDTH_POLICY_VERSION}:max_scaled_observed_{terms}"


def _display_bounds(lower: float, upper: float, width: float) -> tuple[int | float, int | float, float]:
    """Round outward for a compact report label while retaining raw bounds."""

    from math import ceil, floor

    tick = 1.0 if width < 5.0 else 5.0
    display_lower = floor((lower + 1e-9) / tick) * tick
    display_upper = ceil((upper - 1e-9) / tick) * tick
    return _compact_number(display_lower), _compact_number(display_upper), tick


def _compact_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 6)


def _zone_confidence(inputs: Mapping[str, Any], level: Mapping[str, Any], holiday_multiplier: float) -> float:
    values = inputs.get("values", {}) if isinstance(inputs, Mapping) else {}
    count = sum(1 for value in values.values() if _positive(value))
    score = 0.25 + 0.15 * count
    if _refs(inputs.get("source_refs")):
        score += 0.05
    level_confidence = _number_allow_zero(level.get("confidence"))
    if level_confidence is not None:
        score = min(score, level_confidence)
    # ``apply_session_confidence`` may already have adjusted an explicitly
    # holiday-observed level before it reaches the zone projection.  Apply the
    # session factor here only for raw callers so one observation is never
    # discounted twice along level -> zone.
    multiplier = 1.0 if level.get("session_confidence_applied") is True else holiday_multiplier
    return round(max(0.0, min(1.0, score * multiplier)), 6)


def _aggregate_confidence(rows: Sequence[Mapping[str, Any]], multiplier: float) -> float:
    values = [_number_allow_zero(row.get("confidence")) for row in rows if row.get("zone_status") == "available"]
    if not values:
        return 0.0
    return round(max(0.0, min(1.0, sum(value for value in values if value is not None) / len(values))), 6)


def _holiday_multiplier(session: Mapping[str, Any] | None) -> float:
    if not isinstance(session, Mapping):
        return 1.0
    value = _number_allow_zero(session.get("confidence_multiplier"))
    return (
        value
        if value is not None and 0.0 <= value <= 1.0
        else 0.7
        if session.get("session_class") == "HOLIDAY"
        else 1.0
    )


def _session_from_snapshot(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    value = snapshot.get("session_quality") or snapshot.get("session")
    return value if isinstance(value, Mapping) else {}


def _safe_multipliers(value: Mapping[str, float] | None) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        parsed = _number_allow_zero(raw)
        if parsed is not None and parsed > 0:
            result[str(key).lower()] = parsed
    return result


def _section_data(section: Any) -> dict[str, Any]:
    if not isinstance(section, Mapping):
        return {}
    data = section.get("data")
    return dict(data) if isinstance(data, Mapping) else dict(section)


def _refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _dedupe_refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        marker = repr(sorted(item.items()))
        if marker not in seen:
            seen.add(marker)
            result.append(dict(item))
    return result


def _number(value: Any) -> float | None:
    parsed = _number_allow_zero(value)
    return parsed if parsed is not None and parsed > 0 else None


def _number_allow_zero(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) and parsed >= 0 else None


def _positive(value: Any) -> bool:
    return _number_allow_zero(value) is not None and float(value) > 0


__all__ = ["ZONE_SCHEMA_VERSION", "ZONE_WIDTH_POLICY_VERSION", "build_execution_zones"]
