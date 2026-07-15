"""Pure deterministic directional risk-plan construction for Issue 63-B."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def build_risk_plan(
    *,
    price: float | None,
    key_levels: list[Mapping[str, Any]] | None,
    atr14: float | None,
    latest_price_event: Mapping[str, Any] | None,
    bid: float | None = None,
    ask: float | None = None,
    data_ready: bool = True,
    prerequisites_ready: bool = True,
) -> dict[str, Any]:
    """Build two deterministic setups plus a no-trade explanation without I/O."""
    levels = [dict(item) for item in key_levels or [] if _number(item.get("reference_price")) is not None]
    normalized_price = _number(price)
    event = dict(latest_price_event or {})
    spread = _fresh_spread(bid, ask)
    spread_buffer = 2 * spread if spread is not None else 0.0
    if not data_ready or not prerequisites_ready or atr14 is None or normalized_price is None:
        status = "blocked_data" if not data_ready else "unavailable"
        reason = "blocked_data" if not data_ready else "strategy_prerequisites_unavailable"
        setups = [_blocked_setup(direction, status, reason=reason) for direction in ("long", "short")]
        return {
            "setups": setups,
            "active_scenario": None,
            "no_trade": _no_trade(setups, price=normalized_price, levels=levels),
        }

    entry_buffer = max(0.10 * atr14, 0.5)
    volatility_buffer = max(0.15 * atr14, 0.5)
    stop_buffer = max(volatility_buffer, spread_buffer)
    setups = [
        _setup(
            direction=direction,
            price=normalized_price,
            levels=levels,
            event=event,
            entry_buffer=entry_buffer,
            volatility_buffer=volatility_buffer,
            stop_buffer=stop_buffer,
            spread_buffer=spread_buffer,
            data_ready=data_ready,
        )
        for direction in ("long", "short")
    ]
    triggered = next((setup for setup in setups if setup["status"] == "triggered"), None)
    active_scenario = triggered["direction"] if triggered else ("no_trade" if event.get("confirmed") is True else None)
    return {
        "setups": setups,
        "active_scenario": active_scenario,
        "no_trade": _no_trade(
            setups,
            price=normalized_price,
            levels=levels,
            directional_active=active_scenario in {"long", "short"},
        ),
    }


def _setup(
    *,
    direction: str,
    price: float,
    levels: list[dict[str, Any]],
    event: dict[str, Any],
    entry_buffer: float,
    volatility_buffer: float,
    stop_buffer: float,
    spread_buffer: float,
    data_ready: bool,
) -> dict[str, Any]:
    reference = _reference_level(direction, price, levels, event)
    if not data_ready:
        return _blocked_setup(direction, "blocked_data")
    if reference is None:
        return _blocked_setup(direction, "unavailable")
    reference_price = float(reference["reference_price"])
    entry_zone = [reference_price - entry_buffer, reference_price + entry_buffer]
    midpoint = sum(entry_zone) / 2
    stop = reference_price - stop_buffer if direction == "long" else reference_price + stop_buffer
    targets = _targets(direction, midpoint, levels)
    risk_reward = _risk_reward(direction, midpoint, stop, targets)
    gate_passed = (risk_reward["tp1"] or 0.0) >= 1.0 or (risk_reward["tp2"] or 0.0) >= 1.5
    matching_event = _event_matches_direction(event, direction)
    event_type = event.get("event_type")
    confirmed = event.get("confirmed") is True
    if matching_event and confirmed and gate_passed:
        status = "triggered"
    elif matching_event and confirmed and not gate_passed:
        status = "blocked_rr"
    elif matching_event and event_type in {"intrabar_breach", "touch"}:
        status = "armed"
    else:
        status = "watching"
    reasons: list[str] = []
    if not gate_passed:
        reasons.append("risk_reward_insufficient")
    if not targets:
        reasons.append("targets_unavailable")
    return {
        "setup_id": _setup_id(direction, reference_price, event),
        "direction": direction,
        "status": status,
        "reference_level": _level_summary(reference),
        "entry_zone": entry_zone,
        "trigger_conditions": ["canonical_5m_price_event_matches_direction"],
        "confirmation_conditions": ["two_canonical_5m_closes_and_completed_15m_close_for_accepted_break"],
        "invalidation_level": stop,
        "stop_reference": stop,
        "volatility_buffer": volatility_buffer,
        "spread_buffer": spread_buffer,
        "targets": targets,
        "risk_reward": risk_reward,
        "gate": {"passed": gate_passed, "reasons": reasons},
        "calculation": {
            "ruleset": "live_strategy.rules.v2",
            "inputs": {
                "reference_price": reference_price,
                "entry_buffer": entry_buffer,
                "stop_buffer": stop_buffer,
                "fresh_spread_buffer": spread_buffer,
            },
        },
    }


def _reference_level(direction: str, price: float, levels: list[dict[str, Any]], event: Mapping[str, Any]) -> dict[str, Any] | None:
    if _event_matches_direction(event, direction):
        event_level = event.get("related_level")
        value = _number(event_level.get("value")) if isinstance(event_level, Mapping) else None
        if value is not None:
            return {"reference_price": value, **dict(event_level)}
    if direction == "long":
        candidates = [item for item in levels if _is_support(item) and float(item["reference_price"]) <= price]
        return max(candidates, key=lambda item: float(item["reference_price"]), default=None)
    candidates = [item for item in levels if _is_resistance(item) and float(item["reference_price"]) >= price]
    return min(candidates, key=lambda item: float(item["reference_price"]), default=None)


def _event_matches_direction(event: Mapping[str, Any], direction: str) -> bool:
    event_type, event_direction = event.get("event_type"), event.get("direction")
    if event_type == "failed_break":
        return (event_direction == "below") if direction == "long" else (event_direction == "above")
    return (event_direction == "above") if direction == "long" else (event_direction == "below")


def _targets(direction: str, midpoint: float, levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [float(item["reference_price"]) for item in levels]
    prices = sorted({item for item in candidates if item > midpoint}) if direction == "long" else sorted({item for item in candidates if item < midpoint}, reverse=True)
    targets: list[dict[str, Any]] = []
    for target_price in prices[:3]:
        source = next(item for item in levels if float(item["reference_price"]) == target_price)
        targets.append({"label": f"TP{len(targets) + 1}", "price": target_price, "source_role": source.get("role")})
    return targets


def _risk_reward(direction: str, midpoint: float, stop: float, targets: list[dict[str, Any]]) -> dict[str, float | None]:
    risk = abs(midpoint - stop)
    values: list[float | None] = []
    for target in targets:
        reward = float(target["price"]) - midpoint if direction == "long" else midpoint - float(target["price"])
        values.append(reward / risk if risk > 0 and reward > 0 else None)
    return {f"tp{index}": values[index - 1] if len(values) >= index else None for index in range(1, 4)}


def _blocked_setup(direction: str, status: str, *, reason: str | None = None) -> dict[str, Any]:
    return {
        "setup_id": f"live-setup-{direction}-unavailable",
        "direction": direction,
        "status": status,
        "reference_level": None,
        "entry_zone": None,
        "trigger_conditions": [],
        "confirmation_conditions": [],
        "invalidation_level": None,
        "stop_reference": None,
        "volatility_buffer": None,
        "spread_buffer": 0.0,
        "targets": [],
        "risk_reward": {"tp1": None, "tp2": None, "tp3": None},
        "gate": {"passed": False, "reasons": [reason or ("blocked_data" if status == "blocked_data" else "reference_level_unavailable")]},
        "calculation": {"ruleset": "live_strategy.rules.v2", "inputs": {}},
    }


def _no_trade(
    setups: list[Mapping[str, Any]],
    *,
    price: float | None,
    levels: list[Mapping[str, Any]],
    directional_active: bool = False,
) -> dict[str, Any]:
    if directional_active:
        return {"range": _no_trade_range(price, levels), "reasons": [], "waiting_conditions": []}
    reasons = sorted({reason for setup in setups for reason in setup.get("gate", {}).get("reasons", [])})
    waiting_conditions: list[str] = []
    if "blocked_data" in reasons:
        waiting_conditions.append("fresh_canonical_5m_required")
    if "reference_level_unavailable" in reasons:
        waiting_conditions.append("directional_reference_level_required")
    if "strategy_prerequisites_unavailable" in reasons:
        waiting_conditions.append("strategy_prerequisites_required")
    if "targets_unavailable" in reasons:
        waiting_conditions.append("structural_targets_required")
    if "risk_reward_insufficient" in reasons:
        waiting_conditions.append("risk_reward_gate_required")
    if not any(setup.get("status") == "triggered" for setup in setups):
        waiting_conditions.append("confirmed_price_event_required")
    return {
        "range": _no_trade_range(price, levels),
        "reasons": reasons or ["no_confirmed_directional_setup"],
        "waiting_conditions": list(dict.fromkeys(waiting_conditions)),
    }


def _no_trade_range(price: float | None, levels: list[Mapping[str, Any]]) -> list[float] | None:
    if price is None:
        return None
    supports = [float(item["reference_price"]) for item in levels if _is_support(item) and float(item["reference_price"]) <= price]
    resistances = [float(item["reference_price"]) for item in levels if _is_resistance(item) and float(item["reference_price"]) >= price]
    if not supports or not resistances:
        return None
    lower, upper = max(supports), min(resistances)
    return [lower, upper] if lower < upper else None


def _is_support(level: Mapping[str, Any]) -> bool:
    role = str(level.get("role") or "").lower()
    return "support" in role or "tail" in role


def _is_resistance(level: Mapping[str, Any]) -> bool:
    return "resistance" in str(level.get("role") or "").lower()


def _fresh_spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or ask < bid:
        return None
    return ask - bid


def _level_summary(level: Mapping[str, Any]) -> dict[str, Any]:
    return {"role": level.get("role"), "value": level.get("reference_price"), "strength": level.get("strength")}


def _setup_id(direction: str, reference_price: float, event: Mapping[str, Any]) -> str:
    encoded = json.dumps({"direction": direction, "reference_price": reference_price, "event": event}, sort_keys=True, default=str).encode()
    return f"live-setup-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
