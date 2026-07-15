"""Pure, read-only live strategy state builder for Issue 63-A."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from apps.analysis.strategy.event_overlay import build_event_overlay
from apps.analysis.strategy.live_schemas import LiveStrategyOutput
from apps.analysis.strategy.price_events import detect_latest_price_event, event_thresholds
from apps.analysis.strategy.risk_plan import build_risk_plan


SCHEMA_VERSION = "live_strategy.v1"
CANONICAL_FRESHNESS_SECONDS = 600
QUOTE_FRESHNESS_SECONDS = 120
CLOCK_SKEW_TOLERANCE_SECONDS = 30
ATR_PERIOD = 14


def build_live_strategy(
    *,
    asset: str,
    baseline: Mapping[str, Any] | None,
    canonical_market: Mapping[str, Any] | None,
    options_decision: Mapping[str, Any] | None,
    canonical_market_15m: Mapping[str, Any] | None = None,
    quote_cache: Mapping[str, Any] | None = None,
    event_observation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the deterministic live-strategy read model without I/O.

    ``canonical_market`` must be the response from ``get_market_candles``.  A
    quote cache is deliberately accepted only for supplemental bid/ask/change
    fields; it never participates in price, ATR, or state selection.
    """
    current_time = _as_utc(now) or datetime.now(timezone.utc)
    normalized_asset = str(asset or "XAUUSD").upper()
    market = dict(canonical_market or {})
    market_15m = dict(canonical_market_15m or {})
    baseline_summary = _baseline_summary(baseline)
    latest_candle = _latest_candle(market)
    candle_time = _as_utc(latest_candle.get("time")) if latest_candle else None
    price = _number_or_none(latest_candle.get("close")) if latest_candle else None
    freshness_seconds = _freshness_seconds(current_time, candle_time)
    canonical_ready = (
        price is not None
        and freshness_seconds is not None
        and -CLOCK_SKEW_TOLERANCE_SECONDS <= freshness_seconds <= CANONICAL_FRESHNESS_SECONDS
    )

    warnings: list[str] = []
    if price is None or candle_time is None:
        warnings.append("canonical_candle_unavailable")
    elif freshness_seconds is not None and freshness_seconds < -CLOCK_SKEW_TOLERANCE_SECONDS:
        warnings.append("canonical_candle_future")
    elif freshness_seconds is not None and freshness_seconds > CANONICAL_FRESHNESS_SECONDS:
        warnings.append("canonical_candle_stale")

    quote = _fresh_quote(quote_cache, normalized_asset, current_time, warnings)
    atr14 = _atr14(market.get("candles"), warnings)
    levels = _key_levels(options_decision)
    nearest_level = _nearest_level(price, levels)
    gamma_regime = _nested(options_decision, "gamma_summary", "regime") or "unavailable"

    has_baseline = baseline_summary["strategy_card_id"] is not None
    level_ready = nearest_level is not None
    if not has_baseline:
        warnings.append("baseline_unavailable")
    if not level_ready:
        warnings.append("option_key_levels_unavailable")

    base_strategy_status, base_update_reason = _state(
        canonical_ready=canonical_ready,
        canonical_reason_code=_canonical_reason_code(
            price=price,
            candle_time=candle_time,
            freshness_seconds=freshness_seconds,
        ),
        has_baseline=has_baseline,
        level_ready=level_ready,
        atr14=atr14,
        nearest_level=nearest_level,
    )
    if atr14 is None:
        warnings.append("atr14_unavailable")

    thresholds = event_thresholds(atr14)
    touch_threshold = thresholds["touch_threshold"]
    approach_threshold = thresholds["approach_threshold"]
    market_status = "available" if canonical_ready else ("stale" if price is not None else "unavailable")
    data_ready = canonical_ready
    source_refs = _source_refs(baseline, market, market_15m, options_decision, quote)
    latest_price_event = (
        detect_latest_price_event(
            candles_5m=[item for item in market.get("candles") or [] if isinstance(item, Mapping)],
            candles_15m=[item for item in market_15m.get("candles") or [] if isinstance(item, Mapping)],
            key_levels=levels,
            atr14=atr14,
            source_refs=source_refs,
        )
        if canonical_ready
        else None
    )
    risk_plan = build_risk_plan(
        price=price,
        key_levels=levels,
        atr14=atr14,
        latest_price_event=latest_price_event,
        bid=quote.get("bid"),
        ask=quote.get("ask"),
        data_ready=canonical_ready,
        prerequisites_ready=has_baseline and level_ready and atr14 is not None,
    )
    event_overlay = build_event_overlay(event_observation)
    strategy_status, update_reason = _event_state(
        base_status=base_strategy_status,
        base_reason=base_update_reason,
        canonical_ready=canonical_ready,
        has_baseline=has_baseline,
        level_ready=level_ready,
        atr14=atr14,
        event=latest_price_event,
        setups=risk_plan["setups"],
    )
    feasibility_reasons = _feasibility_reasons(
        data_ready=data_ready,
        has_baseline=has_baseline,
        level_ready=level_ready,
        atr14=atr14,
        setups=risk_plan["setups"],
    )
    input_fingerprint = {
        "ruleset": "live_strategy.rules.v2",
        "asset": normalized_asset,
        "baseline_strategy_id": baseline_summary["strategy_card_id"],
        "baseline_version": baseline_summary["version"],
        "canonical_candle": {
            "time": latest_candle.get("time") if latest_candle else None,
            "close": price,
            "source": latest_candle.get("source") if latest_candle else None,
        },
        "canonical_15m_candle": {
            "time": _latest_candle(market_15m).get("time") if _latest_candle(market_15m) else None,
            "close": _number_or_none(_latest_candle(market_15m).get("close")) if _latest_candle(market_15m) else None,
        },
        "options": {
            "trade_date": _nested(options_decision, "meta", "current_trade_date"),
            "gamma_regime": gamma_regime,
            "key_levels": levels,
        },
        "latest_price_event": latest_price_event,
        "risk_plan": risk_plan,
    }
    strategy_id = f"live-strategy-{_stable_digest(input_fingerprint)[:16]}"

    artifact_refs = _artifact_refs(baseline, market, options_decision, quote)
    baseline_date = baseline_summary.get("trade_date")
    options_date = _nested(options_decision, "meta", "current_trade_date")
    if baseline_date and options_date and baseline_date != options_date:
        warnings.append("baseline_options_trade_date_mismatch")

    response = LiveStrategyOutput(
        schema_version=SCHEMA_VERSION,
        status=_response_status(canonical_present=price is not None, canonical_ready=canonical_ready, has_baseline=has_baseline, level_ready=level_ready, atr14=atr14),
        strategy_id=strategy_id,
        baseline_strategy_id=baseline_summary["strategy_card_id"],
        strategy_version="live_strategy.rules.v2",
        asset=normalized_asset,
        strategy_status=strategy_status,
        updated_at=current_time.isoformat(),
        update_reason=update_reason,
        baseline=baseline_summary,
        live_market={
            "price": price,
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "change_pct": quote.get("change_pct"),
            "provider": market.get("provider") or "unavailable",
            "timestamps": {
                "canonical": latest_candle.get("time") if latest_candle else None,
                "quote_cache": quote.get("timestamp"),
            },
            "freshness_seconds": freshness_seconds,
            "freshness": "fresh" if canonical_ready else ("stale" if price is not None else "unavailable"),
            "status": market_status,
            "session": "unknown",
        },
        market_state={
            "gamma_regime": gamma_regime,
            "nearest_level": nearest_level,
            "distance": nearest_level.get("distance") if nearest_level else None,
            "atr14": atr14,
            "level_event": update_reason["reason_code"] if update_reason["reason_code"] in {"touch", "approach"} else None,
            "key_levels": levels,
            "touch_threshold": touch_threshold,
            "approach_threshold": approach_threshold,
            "break_buffer": thresholds["break_buffer"],
            "retest_threshold": thresholds["retest_threshold"],
            "latest_price_event": latest_price_event,
            "confirmation_15m": _confirmation_15m(market_15m, latest_price_event),
        },
        feasibility={
            "data_ready": data_ready,
            "level_ready": level_ready,
            "trigger_ready": latest_price_event is not None and latest_price_event.get("confirmed") is True,
            "risk_ready": any(setup.get("reference_level") is not None for setup in risk_plan["setups"]),
            "rr_ready": any(setup.get("gate", {}).get("passed") is True for setup in risk_plan["setups"]),
            "execution_ready": False,
            "reasons": feasibility_reasons,
        },
        active_scenario=risk_plan["active_scenario"],
        setups=risk_plan["setups"],
        no_trade=risk_plan["no_trade"],
        event_overlay=event_overlay,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        data_quality={
            "canonical_candle": {
                "status": market_status,
                "timestamp": latest_candle.get("time") if latest_candle else None,
                "freshness_seconds": freshness_seconds,
                "provider": market.get("provider") or "unavailable",
            },
            "quote_cache": {
                "status": quote["status"],
                "timestamp": quote["timestamp"],
                "freshness_seconds": quote["freshness_seconds"],
            },
            "canonical_15m": {
                "status": "available" if _latest_candle(market_15m) else "unavailable",
                "timestamp": _latest_candle(market_15m).get("time") if _latest_candle(market_15m) else None,
            },
            "baseline_trade_date": baseline_date,
            "options_trade_date": options_date,
            "baseline_options_same_trade_date": baseline_date == options_date if baseline_date and options_date else None,
            "warnings": _unique(warnings),
        },
    )
    return response.model_dump(mode="json")


def _state(
    *,
    canonical_ready: bool,
    canonical_reason_code: str | None,
    has_baseline: bool,
    level_ready: bool,
    atr14: float | None,
    nearest_level: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    if not canonical_ready:
        return "SUSPENDED_DATA", {
            "reason_code": canonical_reason_code or "canonical_candle_unavailable",
            "message": "Canonical XAUUSD 5m candle is missing, stale, or has an invalid timestamp.",
            "related_level": None,
        }
    if not has_baseline:
        return "WAITING", {
            "reason_code": "baseline_unavailable",
            "message": "A baseline StrategyCard is required before live monitoring can proceed.",
            "related_level": None,
        }
    if not level_ready:
        return "WAITING", {
            "reason_code": "option_key_levels_unavailable",
            "message": "Options decision key levels are unavailable.",
            "related_level": None,
        }
    if atr14 is None:
        return "WAITING", {
            "reason_code": "atr14_unavailable",
            "message": "ATR14 cannot be calculated from canonical candles; proximity thresholds are unavailable.",
            "related_level": nearest_level,
        }
    distance = nearest_level["distance"]
    if distance <= _touch_threshold(atr14):
        return "ARMED", {
            "reason_code": "touch",
            "message": "Canonical price is within the deterministic touch threshold of the nearest key level.",
            "related_level": nearest_level,
        }
    if distance <= _approach_threshold(atr14):
        return "WATCHING", {
            "reason_code": "approach",
            "message": "Canonical price is approaching the nearest key level.",
            "related_level": nearest_level,
        }
    return "WAITING", {
        "reason_code": "outside_approach_range",
        "message": "Canonical price is outside the deterministic approach range of key levels.",
        "related_level": nearest_level,
    }


def _event_state(
    *,
    base_status: str,
    base_reason: dict[str, Any],
    canonical_ready: bool,
    has_baseline: bool,
    level_ready: bool,
    atr14: float | None,
    event: Mapping[str, Any] | None,
    setups: list[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Apply 63-B event/risk transitions without bypassing data prerequisites."""
    if not canonical_ready or not has_baseline or not level_ready or atr14 is None:
        return base_status, base_reason
    if not event:
        return base_status, base_reason
    event_type = str(event.get("event_type"))
    matching = [item for item in setups if item.get("status") in {"triggered", "blocked_rr"}]
    if event.get("confirmed") is True and any(item.get("status") == "triggered" for item in matching):
        return "TRIGGERED", _event_reason(event, "confirmed_price_event")
    if event.get("confirmed") is True and any(item.get("status") == "blocked_rr" for item in matching):
        return "ARMED", _event_reason(event, "risk_reward_insufficient")
    if event_type in {"intrabar_breach", "touch"}:
        return "ARMED", _event_reason(event, event_type)
    if event_type == "approach":
        return "WATCHING", _event_reason(event, "approach")
    return base_status, base_reason


def _event_reason(event: Mapping[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "message": f"Deterministic canonical price event: {event.get('event_type')}.",
        "related_level": event.get("related_level"),
    }


def _confirmation_15m(market: Mapping[str, Any], event: Mapping[str, Any] | None) -> dict[str, Any]:
    latest = _latest_candle(market)
    return {
        "confirmed": event is not None and event.get("event_type") == "accepted_break" and event.get("confirmed") is True,
        "close": _number_or_none(latest.get("close")) if latest and latest.get("partial") is not True else None,
        "timestamp": latest.get("time") if latest else None,
    }


def _baseline_summary(baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(baseline or {})
    card = raw.get("json") if isinstance(raw.get("json"), Mapping) else {}
    strategy_card_id = raw.get("strategy_card_id") or raw.get("run_id")
    return {
        "strategy_card_id": str(strategy_card_id) if strategy_card_id else None,
        "asset": raw.get("asset"),
        "trade_date": raw.get("trade_date"),
        "run_id": raw.get("run_id"),
        "snapshot_id": raw.get("snapshot_id"),
        "version": card.get("version") or raw.get("version"),
        "bias": raw.get("bias") if raw.get("bias") is not None else card.get("bias"),
        "confidence": raw.get("confidence") if raw.get("confidence") is not None else card.get("confidence"),
        "market_regime": raw.get("market_regime") if raw.get("market_regime") is not None else card.get("market_regime"),
        "updated_at": raw.get("updated_at") if raw.get("updated_at") is not None else card.get("created_at"),
        "source_refs": list(raw.get("source_refs") or []),
        "artifact_refs": list(raw.get("artifact_refs") or raw.get("paths", {}).values()),
    }


def _latest_candle(market: Mapping[str, Any]) -> dict[str, Any] | None:
    candles = [item for item in market.get("candles") or [] if isinstance(item, Mapping)]
    return dict(candles[-1]) if candles else None


def _atr14(candles: Any, warnings: list[str]) -> float | None:
    rows = [dict(item) for item in candles or [] if isinstance(item, Mapping)]
    if len(rows) < ATR_PERIOD + 1:
        return None
    true_ranges: list[float] = []
    for previous, current in zip(rows[-(ATR_PERIOD + 1) :], rows[-ATR_PERIOD:]):
        previous_close = _number_or_none(previous.get("close"))
        high = _number_or_none(current.get("high"))
        low = _number_or_none(current.get("low"))
        if previous_close is None or high is None or low is None:
            warnings.append("atr14_invalid_candle")
            return None
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(true_ranges) / ATR_PERIOD


def _key_levels(options_decision: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in (options_decision or {}).get("key_levels") or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        reference = _number_or_none(item.get("strike"))
        band = item.get("band")
        if reference is None and isinstance(band, Mapping):
            lower = _number_or_none(band.get("lower"))
            upper = _number_or_none(band.get("upper"))
            if lower is not None and upper is not None:
                reference = (lower + upper) / 2
        if reference is None:
            continue
        item["reference_price"] = reference
        result.append(item)
    return result


def _nearest_level(price: float | None, levels: list[dict[str, Any]]) -> dict[str, Any] | None:
    if price is None or not levels:
        return None
    nearest = min(levels, key=lambda item: abs(item["reference_price"] - price))
    return {
        "role": nearest.get("role"),
        "value": nearest["reference_price"],
        "distance": abs(nearest["reference_price"] - price),
        "distance_pct": abs(nearest["reference_price"] - price) / price * 100 if price else None,
        "strength": nearest.get("strength"),
        "source_level": nearest,
    }


def _fresh_quote(
    quote_cache: Mapping[str, Any] | None,
    asset: str,
    now: datetime,
    warnings: list[str],
) -> dict[str, Any]:
    cache = dict(quote_cache or {})
    timestamp = _as_utc(cache.get("generated_at") or cache.get("updated_at"))
    freshness_seconds = _freshness_seconds(now, timestamp)
    quote = (cache.get("quotes") or {}).get(asset) if isinstance(cache.get("quotes"), Mapping) else None
    if not isinstance(quote, Mapping):
        return {"status": "unavailable", "timestamp": _iso(timestamp), "freshness_seconds": freshness_seconds, "bid": None, "ask": None, "change_pct": None}
    if freshness_seconds is None or not -CLOCK_SKEW_TOLERANCE_SECONDS <= freshness_seconds <= QUOTE_FRESHNESS_SECONDS:
        warnings.append(
            "quote_cache_future"
            if freshness_seconds is not None and freshness_seconds < -CLOCK_SKEW_TOLERANCE_SECONDS
            else "quote_cache_stale"
        )
        return {"status": "stale", "timestamp": _iso(timestamp), "freshness_seconds": freshness_seconds, "bid": None, "ask": None, "change_pct": None}
    return {
        "status": "fresh",
        "timestamp": _iso(timestamp),
        "freshness_seconds": freshness_seconds,
        "bid": _number_or_none(quote.get("bid")),
        "ask": _number_or_none(quote.get("ask")),
        "change_pct": _number_or_none(quote.get("change_pct")),
        "artifact_ref": "storage/outputs/jin10/quotes_cache.json",
    }


def _source_refs(
    baseline: Mapping[str, Any] | None,
    market: Mapping[str, Any],
    market_15m: Mapping[str, Any],
    options_decision: Mapping[str, Any] | None,
    quote: Mapping[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    trace = market.get("source_trace") if isinstance(market.get("source_trace"), Mapping) else {}
    refs.append({"name": "canonical_xauusd_5m", "source_ref": trace.get("primary_source"), "status": "ok" if market.get("candles") else "unavailable"})
    trace_15m = market_15m.get("source_trace") if isinstance(market_15m.get("source_trace"), Mapping) else {}
    refs.append({"name": "canonical_xauusd_15m", "source_ref": trace_15m.get("primary_source"), "status": "ok" if market_15m.get("candles") else "unavailable"})
    refs.extend(item for item in (baseline or {}).get("source_refs") or [] if isinstance(item, Mapping))
    refs.extend(item for item in (options_decision or {}).get("source_refs") or [] if isinstance(item, Mapping))
    if quote.get("status") == "fresh":
        refs.append({"name": "jin10_quote_cache", "source_ref": quote.get("artifact_ref"), "status": "supplemental"})
    return [dict(item) for item in refs]


def _artifact_refs(
    baseline: Mapping[str, Any] | None,
    market: Mapping[str, Any],
    options_decision: Mapping[str, Any] | None,
    quote: Mapping[str, Any],
) -> list[Any]:
    refs: list[Any] = []
    refs.extend((baseline or {}).get("artifact_refs") or (baseline or {}).get("paths", {}).values())
    refs.extend((options_decision or {}).get("artifact_refs") or [])
    trace = market.get("source_trace") if isinstance(market.get("source_trace"), Mapping) else {}
    if trace.get("latest_raw_path"):
        refs.append(trace["latest_raw_path"])
    if quote.get("status") == "fresh" and quote.get("artifact_ref"):
        refs.append(quote["artifact_ref"])
    return _unique(refs)


def _feasibility_reasons(
    *,
    data_ready: bool,
    has_baseline: bool,
    level_ready: bool,
    atr14: float | None,
    setups: list[Mapping[str, Any]],
) -> dict[str, list[str]]:
    data_reasons: list[str] = [] if data_ready else ["canonical_xauusd_5m_unavailable_or_stale"]
    level_reasons: list[str] = []
    if not level_ready:
        level_reasons.append("options_key_levels_unavailable")
    trigger_reasons: list[str] = []
    if atr14 is None:
        trigger_reasons.append("atr14_unavailable")
    if not any(item.get("status") in {"armed", "triggered", "blocked_rr"} for item in setups):
        trigger_reasons.append("no_directional_price_event")
    risk_reasons = ["reference_level_unavailable"] if not any(item.get("reference_level") is not None for item in setups) else []
    rr_reasons = ["risk_reward_insufficient"] if not any(item.get("gate", {}).get("passed") is True for item in setups) else []
    return {
        "data_ready": data_reasons,
        "level_ready": level_reasons,
        "baseline": [] if has_baseline else ["baseline_strategy_card_unavailable"],
        "trigger_ready": trigger_reasons,
        "risk_ready": risk_reasons,
        "rr_ready": rr_reasons,
        "execution_ready": ["execution_intentionally_not_supported"],
    }


def _response_status(*, canonical_present: bool, canonical_ready: bool, has_baseline: bool, level_ready: bool, atr14: float | None) -> str:
    if not canonical_present:
        return "unavailable"
    if canonical_ready and has_baseline and level_ready and atr14 is not None:
        return "available"
    return "partial"


def _canonical_reason_code(
    *,
    price: float | None,
    candle_time: datetime | None,
    freshness_seconds: int | None,
) -> str | None:
    if price is None or candle_time is None or freshness_seconds is None:
        return "canonical_candle_unavailable"
    if freshness_seconds < -CLOCK_SKEW_TOLERANCE_SECONDS:
        return "canonical_candle_future"
    if freshness_seconds > CANONICAL_FRESHNESS_SECONDS:
        return "canonical_candle_stale"
    return None


def _touch_threshold(atr14: float | None) -> float | None:
    return max(min(0.05 * atr14, 0.5), 0.1) if atr14 is not None else None


def _approach_threshold(atr14: float | None) -> float | None:
    return max(0.2 * atr14, 1.0) if atr14 is not None else None


def _freshness_seconds(now: datetime, timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return int((now - timestamp).total_seconds())


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _number_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested(payload: Mapping[str, Any] | None, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
