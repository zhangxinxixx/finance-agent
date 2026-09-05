"""Pure, read-only live strategy state builder for Issue 63-A."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from apps.analysis.strategy.event_overlay import build_event_overlay
from apps.analysis.strategy.live_schemas import LiveStrategyOutput
from apps.analysis.strategy.live_input_gates import (
    CANONICAL_CANDLE_DURATION_SECONDS,
    CANONICAL_FRESHNESS_SECONDS,
    evaluate_live_input_gates,
)
from apps.analysis.strategy.price_events import detect_latest_price_event, event_thresholds
from apps.analysis.strategy.risk_plan import build_risk_plan


SCHEMA_VERSION = "live_strategy.v1"
QUOTE_FRESHNESS_SECONDS = 120
CLOCK_SKEW_TOLERANCE_SECONDS = 30
ATR_PERIOD = 14
_CONFIRMED_PRICE_EVENTS = frozenset({"accepted_break", "failed_break", "retest", "reclaim"})

__all__ = [
    "CANONICAL_CANDLE_DURATION_SECONDS",
    "CANONICAL_FRESHNESS_SECONDS",
    "build_live_strategy",
]

_GOLD_ID_PATTERNS = {
    "receipt_id": r"gold_daily_close_canonical_receipt\.v1:[0-9a-f]{64}",
    "result_id": r"gold_daily_close_loop_result\.v1:[0-9a-f]{64}",
    "feature_snapshot_id": r"feature_snapshot\.v[12]:[0-9a-f]{64}",
    "state_id": r"analysis_state\.v[12]:[0-9a-f]{64}",
    "transition_decision_hash": r"[0-9a-f]{64}",
    "strategy_id": r"strategy_decision\.v[12]:[0-9a-f]{64}",
    "consistency_decision_id": r"analysis_strategy_consistency_decision\.v1:[0-9a-f]{64}",
}


def build_live_strategy(
    *,
    asset: str,
    baseline: Mapping[str, Any] | None,
    gold_baseline: Mapping[str, Any] | None = None,
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
    if normalized_asset != "XAUUSD":
        raise ValueError("live_strategy.v1 supports only XAUUSD")
    market = dict(canonical_market or {})
    market_15m = dict(canonical_market_15m or {})
    premarket_context = _premarket_context_summary(baseline)
    baseline_summary = _gold_baseline_summary(gold_baseline, premarket_context, current_time=current_time)
    gold_authority = baseline_summary["authority"]
    effective_strategy_as_of = _timestamp_utc(gold_authority.get("strategy_decision_as_of"))
    effective_trade_date = _trade_date(effective_strategy_as_of)
    input_gates = evaluate_live_input_gates(
        canonical_market=market,
        canonical_market_15m=market_15m,
        options_decision=options_decision,
        effective_trade_date=effective_trade_date,
        now=current_time,
    )
    canonical_5m_gate = input_gates["canonical_5m"]
    canonical_15m_gate = input_gates["canonical_15m"]
    cme_gate = input_gates["cme"]
    utc_scope_gate = input_gates["utc_scope"]
    latest_candle = _latest_candle(market)
    canonical_5m_rows = [item for item in market.get("candles") or [] if isinstance(item, Mapping)]
    candle_closed_at = _timestamp_utc(canonical_5m_gate.get("closed_at"))
    price = _number_or_none(latest_candle.get("close")) if latest_candle else None
    freshness_seconds = canonical_5m_gate.get("freshness_seconds")
    canonical_reason_code = canonical_5m_gate.get("reason_code")
    canonical_ready = canonical_5m_gate.get("ready") is True

    warnings: list[str] = []
    warnings.extend(
        reason
        for gate in input_gates.values()
        for reason in gate.get("reasons", [])
        if isinstance(reason, str)
    )
    if canonical_reason_code and canonical_reason_code not in warnings:
        warnings.append(canonical_reason_code)

    quote = _fresh_quote(quote_cache, normalized_asset, current_time, warnings)
    atr14 = _atr14(market.get("candles"), warnings)
    levels = _key_levels(options_decision)
    nearest_level = _nearest_level(price, levels)
    gamma_regime = _nested(options_decision, "gamma_summary", "regime") or "unavailable"
    cme_positioning = _cme_positioning(options_decision, baseline_trade_date=baseline_summary.get("trade_date"))

    has_baseline = gold_authority["authority_ready"] is True
    authorized_direction = gold_authority["direction"] if has_baseline else None
    baseline_reason_code = gold_authority["reason_code"]
    level_gate_reasons = _level_gate_reasons(
        cme_gate=cme_gate,
        utc_scope_gate=utc_scope_gate,
    )
    level_ready = nearest_level is not None and not level_gate_reasons
    level_reason_code = (
        "option_key_levels_unavailable"
        if nearest_level is None
        else level_gate_reasons[0] if level_gate_reasons else None
    )
    if not has_baseline:
        warnings.append("gold_direction_authority_unavailable")
    if not level_ready:
        warnings.append(level_reason_code or "option_key_levels_unavailable")

    base_strategy_status, base_update_reason = _state(
        canonical_ready=canonical_ready,
        canonical_reason_code=canonical_reason_code,
        has_baseline=has_baseline,
        baseline_reason_code=baseline_reason_code,
        level_ready=level_ready,
        level_reason_code=level_reason_code,
        atr14=atr14,
        nearest_level=nearest_level,
    )
    if atr14 is None:
        warnings.append("atr14_unavailable")

    thresholds = event_thresholds(atr14)
    touch_threshold = thresholds["touch_threshold"]
    approach_threshold = thresholds["approach_threshold"]
    market_status = "available" if canonical_ready else (
        "stale" if price is not None and canonical_5m_gate.get("status") == "stale" else "unavailable"
    )
    data_ready = canonical_ready
    source_refs = _source_refs(baseline_summary, market, market_15m, options_decision, quote)
    has_directional_inputs = canonical_ready and has_baseline and cme_gate.get("ready") is True and utc_scope_gate.get("ready") is True
    candidate_price_event = (
        detect_latest_price_event(
            candles_5m=canonical_5m_rows[-15:],
            candles_15m=[item for item in market_15m.get("candles") or [] if isinstance(item, Mapping)],
            key_levels=levels,
            atr14=atr14,
            source_refs=source_refs,
        )
        if has_directional_inputs
        else None
    )
    price_event_gate_reason = None
    latest_price_event = candidate_price_event
    if (
        candidate_price_event
        and candidate_price_event.get("event_type") in _CONFIRMED_PRICE_EVENTS
        and canonical_15m_gate.get("ready") is not True
    ):
        price_event_gate_reason = canonical_15m_gate.get("reason_code") or "canonical_15m_unavailable"
        latest_price_event = None
        warnings.append(price_event_gate_reason)
    directional_gate_reasons = _directional_gate_reasons(
        cme_gate=cme_gate,
        utc_scope_gate=utc_scope_gate,
        price_event_gate_reason=price_event_gate_reason,
    )
    risk_plan = build_risk_plan(
        price=price,
        key_levels=levels,
        atr14=atr14,
        latest_price_event=latest_price_event,
        bid=quote.get("bid"),
        ask=quote.get("ask"),
        data_ready=canonical_ready,
        prerequisites_ready=level_ready and atr14 is not None,
        allowed_directions=(authorized_direction,) if authorized_direction else (),
        restricted_direction_reason=("gold_direction_mismatch" if authorized_direction else "gold_direction_authority_unavailable"),
    )
    if not level_ready and nearest_level is not None:
        risk_plan = _apply_level_gate_to_risk_plan(
            risk_plan,
            reason_code=level_reason_code or "live_input_gate_blocked",
        )
    event_overlay = build_event_overlay(event_observation)
    strategy_status, update_reason = _event_state(
        base_status=base_strategy_status,
        base_reason=base_update_reason,
        canonical_ready=canonical_ready,
        has_baseline=has_baseline,
        authorized_direction=authorized_direction,
        input_gate_reasons=directional_gate_reasons,
        level_ready=level_ready,
        atr14=atr14,
        event=latest_price_event,
        setups=risk_plan["setups"],
    )
    feasibility_reasons = _feasibility_reasons(
        data_ready=data_ready,
        has_baseline=has_baseline,
        baseline_reason_code=baseline_reason_code,
        input_gate_reasons=directional_gate_reasons,
        canonical_5m_gate=canonical_5m_gate,
        canonical_15m_gate=canonical_15m_gate,
        level_ready=level_ready,
        level_reason_code=level_reason_code,
        atr14=atr14,
        setups=risk_plan["setups"],
    )
    input_fingerprint = {
        "ruleset": "live_strategy.rules.v2",
        "asset": normalized_asset,
        "effective_strategy_as_of": _iso(effective_strategy_as_of),
        "input_gates": _semantic_input_gates(input_gates),
        "price_event_gate_reason": price_event_gate_reason,
        "gold_baseline": {
            key: gold_authority.get(key)
            for key in (
                "status",
                "reason_code",
                "direction",
                "receipt_id",
                "result_id",
                "feature_snapshot_id",
                "state_id",
                "transition_decision_hash",
                "strategy_id",
                "consistency_decision_id",
                "gold_head_held",
                "lineage_verified",
            )
        },
        "premarket_context_strategy_card_id": premarket_context["strategy_card_id"],
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
            "cme_positioning": cme_positioning,
        },
        "latest_price_event": latest_price_event,
        "risk_plan": risk_plan,
    }
    strategy_id = f"live-strategy-{_stable_digest(input_fingerprint)[:16]}"

    artifact_refs = _artifact_refs(baseline_summary, market, options_decision, quote)
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
                "canonical_closed_at": _iso(candle_closed_at),
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
            "confirmation_15m": _confirmation_15m(market_15m, latest_price_event, gate=canonical_15m_gate),
        },
        cme_positioning=cme_positioning,
        feasibility={
            "data_ready": data_ready,
            "level_ready": level_ready,
            "trigger_ready": any(setup.get("status") == "triggered" for setup in risk_plan["setups"]),
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
            "gold_baseline": {
                key: gold_authority.get(key)
                for key in (
                    "status",
                    "reason_code",
                    "direction",
                    "quality_status",
                    "strategy_decision_as_of",
                    "gold_head_held",
                    "authority_ready",
                    "lineage_verified",
                    "receipt_id",
                    "strategy_id",
                )
            },
            "canonical_candle": {
                **canonical_5m_gate,
                "status": market_status,
                "timestamp": latest_candle.get("time") if latest_candle else None,
                "closed_at": _iso(candle_closed_at),
                "freshness_seconds": freshness_seconds,
                "provider": market.get("provider") or "unavailable",
            },
            "quote_cache": {
                "status": quote["status"],
                "timestamp": quote["timestamp"],
                "freshness_seconds": quote["freshness_seconds"],
            },
            "canonical_15m": {
                **canonical_15m_gate,
                "timestamp": _latest_candle(market_15m).get("time") if _latest_candle(market_15m) else None,
            },
            "input_gates": input_gates,
            "effective_strategy_as_of": _iso(effective_strategy_as_of),
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
    baseline_reason_code: str | None,
    level_ready: bool,
    level_reason_code: str | None,
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
            "reason_code": baseline_reason_code or "gold_direction_authority_unavailable",
            "message": "A verified directional Gold daily-close baseline is required before live monitoring can proceed.",
            "related_level": None,
        }
    if not level_ready:
        return "WAITING", {
            "reason_code": level_reason_code or "option_key_levels_unavailable",
            "message": "Live key-level input is blocked by a deterministic input gate.",
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
    authorized_direction: str | None,
    input_gate_reasons: list[str],
    level_ready: bool,
    atr14: float | None,
    event: Mapping[str, Any] | None,
    setups: list[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Apply 63-B event/risk transitions without bypassing data prerequisites."""
    if not canonical_ready or not has_baseline or not level_ready or atr14 is None:
        return base_status, base_reason
    if input_gate_reasons:
        return "WAITING", {
            "reason_code": input_gate_reasons[0],
            "message": "Live directional inputs are blocked by a deterministic input gate.",
            "related_level": None,
        }
    if not event:
        return base_status, base_reason
    if not _event_matches_direction(event, authorized_direction):
        return "WAITING", {
            "reason_code": "gold_direction_mismatch",
            "message": "Canonical price event conflicts with the verified Gold daily-close direction.",
            "related_level": event.get("related_level"),
        }
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


def _event_matches_direction(event: Mapping[str, Any], direction: str | None) -> bool:
    if direction not in {"long", "short"}:
        return False
    event_type = event.get("event_type")
    event_direction = event.get("direction")
    if event_type == "failed_break":
        return (event_direction == "below") if direction == "long" else (event_direction == "above")
    return (event_direction == "above") if direction == "long" else (event_direction == "below")


def _directional_gate_reasons(
    *,
    cme_gate: Mapping[str, Any],
    utc_scope_gate: Mapping[str, Any],
    price_event_gate_reason: str | None,
) -> list[str]:
    reasons: list[str] = []
    for gate in (cme_gate, utc_scope_gate):
        for reason in gate.get("reasons", []):
            if isinstance(reason, str) and reason not in reasons:
                reasons.append(reason)
    if price_event_gate_reason and price_event_gate_reason not in reasons:
        reasons.append(price_event_gate_reason)
    return reasons


def _level_gate_reasons(
    *,
    cme_gate: Mapping[str, Any],
    utc_scope_gate: Mapping[str, Any],
) -> list[str]:
    return _directional_gate_reasons(
        cme_gate=cme_gate,
        utc_scope_gate=utc_scope_gate,
        price_event_gate_reason=None,
    )


def _semantic_input_gates(gates: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep qualification identity stable while ages remain display-only."""
    fields = {
        "canonical_5m": (
            "ready",
            "status",
            "reason_code",
            "timestamp",
            "closed_at",
            "expected_closed_at",
        ),
        "canonical_15m": (
            "ready",
            "status",
            "reason_code",
            "timestamp",
            "closed_at",
            "expected_closed_at",
        ),
        "cme": (
            "ready",
            "status",
            "reason_code",
            "reasons",
            "options_status",
            "source_status",
            "trade_date",
            "expected_trade_date",
        ),
        "utc_scope": (
            "ready",
            "status",
            "reason_code",
            "reasons",
            "effective_trade_date",
            "cme_trade_date",
            "canonical_5m_trade_date",
        ),
    }
    return {
        name: {key: dict(gates.get(name) or {}).get(key) for key in keys}
        for name, keys in fields.items()
    }


def _apply_level_gate_to_risk_plan(
    risk_plan: Mapping[str, Any],
    *,
    reason_code: str,
) -> dict[str, Any]:
    """Reflect the level gate in child setup fields without changing risk_plan."""
    setups: list[dict[str, Any]] = []
    for setup in risk_plan.get("setups", []):
        item = dict(setup)
        gate = dict(item.get("gate") or {})
        gate["passed"] = False
        gate["reasons"] = [reason_code]
        item["gate"] = gate
        setups.append(item)
    no_trade = dict(risk_plan.get("no_trade") or {})
    no_trade["reasons"] = [reason_code]
    waiting = list(no_trade.get("waiting_conditions") or [])
    if "live_input_gate_required" not in waiting:
        waiting.append("live_input_gate_required")
    no_trade["waiting_conditions"] = waiting
    return {
        "setups": setups,
        "active_scenario": None,
        "no_trade": no_trade,
    }


def _event_reason(event: Mapping[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "message": f"Deterministic canonical price event: {event.get('event_type')}.",
        "related_level": event.get("related_level"),
    }


def _confirmation_15m(
    market: Mapping[str, Any],
    event: Mapping[str, Any] | None,
    *,
    gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    latest = _latest_candle(market)
    gate_ready = gate is None or gate.get("ready") is True
    return {
        "confirmed": gate_ready and event is not None and event.get("event_type") == "accepted_break" and event.get("confirmed") is True,
        "close": _number_or_none(latest.get("close")) if gate_ready and latest and latest.get("partial") is not True else None,
        "timestamp": latest.get("time") if latest else None,
    }


def _premarket_context_summary(baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project the legacy StrategyCard as supplemental, never directional authority."""
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


def _gold_baseline_summary(
    gold_baseline: Mapping[str, Any] | None,
    premarket_context: Mapping[str, Any],
    *,
    current_time: datetime,
) -> dict[str, Any]:
    """Normalize the verified Gold adapter response into the stable baseline view."""
    authority = dict(gold_baseline or {})
    raw_direction = authority.get("direction")
    direction = raw_direction if isinstance(raw_direction, str) and raw_direction in {"long", "short"} else "none"
    authority_ready = _gold_authority_ready(authority, direction=direction, current_time=current_time)
    authority.setdefault("status", "unavailable")
    authority.setdefault("reason_code", "gold_direction_authority_unavailable")
    if not authority_ready:
        direction = "none"
        status = authority.get("status")
        if not isinstance(status, str) or status not in {"unavailable", "invalid"}:
            authority["status"] = "invalid"
            authority["reason_code"] = "gold_direction_authority_invalid"
    authority["direction"] = direction
    authority["authority_ready"] = authority_ready
    decision_as_of = authority.get("decision_as_of")
    effective_strategy_as_of = authority.get("strategy_decision_as_of")
    return {
        "strategy_card_id": authority.get("strategy_id"),
        "asset": authority.get("asset") or "XAUUSD",
        "trade_date": _trade_date(effective_strategy_as_of),
        "run_id": authority.get("result_id"),
        "snapshot_id": authority.get("feature_snapshot_id"),
        "version": authority.get("strategy_policy_version"),
        "bias": {"long": "bullish", "short": "bearish"}.get(direction, "unavailable"),
        "confidence": _number_or_none(authority.get("confidence")),
        "market_regime": authority.get("market_regime") or "unavailable",
        "updated_at": effective_strategy_as_of or decision_as_of,
        "effective_strategy_as_of": effective_strategy_as_of,
        "source_refs": [dict(item) for item in authority.get("source_refs") or [] if isinstance(item, Mapping)],
        "artifact_refs": list(authority.get("artifact_refs") or []),
        "authority": authority,
        "premarket_context": dict(premarket_context),
    }


def _trade_date(value: Any) -> str | None:
    timestamp = _timestamp_utc(value)
    return timestamp.date().isoformat() if timestamp else None


def _gold_authority_ready(
    authority: Mapping[str, Any],
    *,
    direction: str,
    current_time: datetime,
) -> bool:
    decision_as_of = _timestamp_utc(authority.get("decision_as_of"))
    strategy_decision_as_of = _timestamp_utc(authority.get("strategy_decision_as_of"))
    state_as_of = _timestamp_utc(authority.get("state_as_of"))
    status = authority.get("status")
    asset = authority.get("asset")
    scope = authority.get("scope")
    quality_status = authority.get("quality_status")
    strategy_status = authority.get("strategy_status")
    expected_statuses = {
        "long": {"LONG_WATCH", "LONG_RESEARCH_TRIGGERED"},
        "short": {"SHORT_WATCH", "SHORT_RESEARCH_TRIGGERED"},
    }
    return (
        isinstance(direction, str)
        and isinstance(status, str)
        and isinstance(asset, str)
        and isinstance(scope, str)
        and isinstance(quality_status, str)
        and isinstance(strategy_status, str)
        and authority.get("authority_ready") is True
        and authority.get("lineage_verified") is True
        and status in {"accepted", "held"}
        and asset == "XAUUSD"
        and scope == "daily_close"
        and quality_status == "accepted"
        and strategy_status in expected_statuses.get(direction, set())
        and decision_as_of is not None
        and strategy_decision_as_of is not None
        and state_as_of is not None
        and decision_as_of <= current_time
        and strategy_decision_as_of <= current_time
        and state_as_of <= current_time
        and authority.get("is_trade_instruction") is False
        and _gold_authority_identity_is_well_formed(authority)
    )


def _gold_authority_identity_is_well_formed(authority: Mapping[str, Any]) -> bool:
    for key, pattern in _GOLD_ID_PATTERNS.items():
        value = authority.get(key)
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            return False
    strategy_id = str(authority["strategy_id"])
    strategy_version = strategy_id.split(":", 1)[0].removeprefix("strategy_decision.")
    return authority.get("strategy_policy_version") == f"gold_strategy_policy.{strategy_version}"


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


def _cme_positioning(
    options_decision: Mapping[str, Any] | None,
    *,
    baseline_trade_date: Any,
) -> dict[str, Any]:
    decision = dict(options_decision or {})
    meta = decision.get("meta") if isinstance(decision.get("meta"), Mapping) else {}
    summary = decision.get("oi_summary") if isinstance(decision.get("oi_summary"), Mapping) else {}
    rankings = decision.get("oi_change_rankings") if isinstance(decision.get("oi_change_rankings"), Mapping) else {}
    quality = decision.get("data_quality") if isinstance(decision.get("data_quality"), Mapping) else {}
    trade_date = meta.get("current_trade_date")
    baseline_date = str(baseline_trade_date) if baseline_trade_date else None
    total = summary.get("total") if isinstance(summary.get("total"), Mapping) else {}
    all_large_oi_levels = [
        dict(item) for item in decision.get("large_oi_levels") or [] if isinstance(item, Mapping)
    ]
    nearby_large_oi_levels = [
        dict(item) for item in decision.get("nearby_large_oi_levels") or [] if isinstance(item, Mapping)
    ]
    if not nearby_large_oi_levels:
        nearby_large_oi_levels = [
            item
            for item in all_large_oi_levels
            if _number_or_none(item.get("distance_pct")) is not None
            and abs(_number_or_none(item.get("distance_pct")) or 0.0) <= 12.0
        ]
    return {
        "status": decision.get("status") if decision.get("status") in {"available", "partial"} else "unavailable",
        "trade_date": trade_date,
        "previous_trade_date": meta.get("previous_trade_date"),
        "baseline_trade_date": baseline_date,
        "aligned_with_baseline": baseline_date == trade_date if baseline_date and trade_date else None,
        "source_status": quality.get("cme_status"),
        "comparison_status": meta.get("comparison_status") or summary.get("comparison_status") or "unavailable",
        "total_oi": dict(total),
        "large_oi_levels": (nearby_large_oi_levels or all_large_oi_levels)[:8],
        "large_oi_scope": "nearby_6pct" if nearby_large_oi_levels else "full_chain",
        "largest_increases": [dict(item) for item in rankings.get("largest_increases") or [] if isinstance(item, Mapping)][:5],
        "largest_decreases": [dict(item) for item in rankings.get("largest_decreases") or [] if isinstance(item, Mapping)][:5],
        "pnt_summary": dict(decision.get("pnt_summary")) if isinstance(decision.get("pnt_summary"), Mapping) else {},
        "intent_summary": dict(decision.get("intent_summary")) if isinstance(decision.get("intent_summary"), Mapping) else {},
        "structure_summary": dict(decision.get("structure_summary")) if isinstance(decision.get("structure_summary"), Mapping) else {},
        "scenario_paths": [dict(item) for item in decision.get("scenario_paths") or [] if isinstance(item, Mapping)],
    }


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
    premarket_context = (baseline or {}).get("premarket_context")
    if isinstance(premarket_context, Mapping):
        refs.extend(item for item in premarket_context.get("source_refs") or [] if isinstance(item, Mapping))
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
    premarket_context = (baseline or {}).get("premarket_context")
    if isinstance(premarket_context, Mapping):
        refs.extend(premarket_context.get("artifact_refs") or premarket_context.get("paths", {}).values())
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
    baseline_reason_code: str | None,
    input_gate_reasons: list[str],
    canonical_5m_gate: Mapping[str, Any],
    canonical_15m_gate: Mapping[str, Any],
    level_ready: bool,
    level_reason_code: str | None,
    atr14: float | None,
    setups: list[Mapping[str, Any]],
) -> dict[str, list[str]]:
    data_reasons: list[str] = []
    if not data_ready:
        data_reasons.append(canonical_5m_gate.get("reason_code") or "canonical_xauusd_5m_unavailable_or_stale")
    for reason in input_gate_reasons:
        if reason not in data_reasons:
            data_reasons.append(reason)
    level_reasons: list[str] = []
    if not level_ready:
        level_reasons.append(level_reason_code or "options_key_levels_unavailable")
    trigger_reasons: list[str] = []
    if atr14 is None:
        trigger_reasons.append("atr14_unavailable")
    if not any(item.get("status") in {"armed", "triggered", "blocked_rr"} for item in setups):
        trigger_reasons.append("no_directional_price_event")
    if canonical_15m_gate.get("ready") is not True:
        confirmation_reason = canonical_15m_gate.get("reason_code") or "canonical_15m_unavailable"
        if confirmation_reason not in trigger_reasons:
            trigger_reasons.append(confirmation_reason)
    for reason in input_gate_reasons:
        if reason not in trigger_reasons:
            trigger_reasons.append(reason)
    risk_reasons = ["reference_level_unavailable"] if not any(item.get("reference_level") is not None for item in setups) else []
    rr_reasons = ["risk_reward_insufficient"] if not any(item.get("gate", {}).get("passed") is True for item in setups) else []
    return {
        "data_ready": data_reasons,
        "level_ready": level_reasons,
        "baseline": [] if has_baseline else [baseline_reason_code or "gold_direction_authority_unavailable"],
        "trigger_ready": trigger_reasons,
        "risk_ready": risk_reasons,
        "rr_ready": rr_reasons,
        "execution_ready": ["execution_intentionally_not_supported"],
        "input_gates": _unique(
            [
                *input_gate_reasons,
                *(
                    [canonical_5m_gate.get("reason_code")]
                    if not data_ready and canonical_5m_gate.get("reason_code")
                    else []
                ),
                *(
                    [canonical_15m_gate.get("reason_code")]
                    if canonical_15m_gate.get("ready") is not True and canonical_15m_gate.get("reason_code")
                    else []
                ),
            ]
        ),
    }


def _response_status(*, canonical_present: bool, canonical_ready: bool, has_baseline: bool, level_ready: bool, atr14: float | None) -> str:
    if not canonical_present:
        return "unavailable"
    if canonical_ready and has_baseline and level_ready and atr14 is not None:
        return "available"
    return "partial"


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


def _timestamp_utc(value: Any) -> datetime | None:
    """Parse a formal timestamp only when an explicit timezone is present."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _number_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
