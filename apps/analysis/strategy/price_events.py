"""Pure canonical-candle price-event detection for live_strategy.v1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


_EVENT_PRIORITY = {
    "failed_break": 7,
    "reclaim": 6,
    "retest": 5,
    "accepted_break": 4,
    "intrabar_breach": 3,
    "touch": 2,
    "approach": 1,
}


def event_thresholds(atr14: float | None) -> dict[str, float | None]:
    """Return the frozen Issue 63-B proximity and confirmation thresholds."""
    if atr14 is None:
        return {
            "touch_threshold": None,
            "approach_threshold": None,
            "break_buffer": None,
            "retest_threshold": None,
        }
    return {
        "touch_threshold": max(min(0.05 * atr14, 0.5), 0.1),
        "approach_threshold": max(0.2 * atr14, 1.0),
        "break_buffer": max(0.05 * atr14, 0.25),
        "retest_threshold": max(0.10 * atr14, 0.5),
    }


def detect_latest_price_event(
    *,
    candles_5m: list[Mapping[str, Any]] | None,
    candles_15m: list[Mapping[str, Any]] | None,
    key_levels: list[Mapping[str, Any]] | None,
    atr14: float | None,
    source_refs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Determine one highest-priority event from immutable candle windows.

    The function deliberately has no clock, storage, or provider dependency.
    A 15m candle is accepted only when it is explicitly complete (or carries no
    partial marker, as is the case for the canonical read model).
    """
    rows = [dict(item) for item in candles_5m or [] if isinstance(item, Mapping)]
    levels = [dict(item) for item in key_levels or [] if isinstance(item, Mapping)]
    if not rows or not levels or atr14 is None:
        return None
    latest = rows[-1]
    price = _number(latest.get("close"))
    detected_at = _iso(latest.get("time"))
    if price is None or detected_at is None:
        return None

    thresholds = event_thresholds(atr14)
    candidates: list[dict[str, Any]] = []
    for level in levels:
        value = _number(level.get("reference_price"))
        if value is None:
            continue
        event = _detect_for_level(
            rows=rows,
            candles_15m=candles_15m or [],
            level=level,
            value=value,
            price=price,
            detected_at=detected_at,
            thresholds=thresholds,
            source_refs=source_refs or [],
        )
        if event is not None:
            candidates.append(event)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _EVENT_PRIORITY[item["event_type"]],
            -abs(float(item["price"]) - float(item["related_level"]["value"])),
        ),
    )


def _detect_for_level(
    *,
    rows: list[dict[str, Any]],
    candles_15m: list[Mapping[str, Any]],
    level: dict[str, Any],
    value: float,
    price: float,
    detected_at: str,
    thresholds: Mapping[str, float | None],
    source_refs: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    break_buffer = float(thresholds["break_buffer"] or 0.0)
    retest_threshold = float(thresholds["retest_threshold"] or 0.0)
    closes = [_number(item.get("close")) for item in rows]
    if closes[-1] is None:
        return None
    allowed_directions = _allowed_break_directions(level)

    def above_break(number: float | None) -> bool:
        return number is not None and number > value + break_buffer

    def below_break(number: float | None) -> bool:
        return number is not None and number < value - break_buffer

    def above_structure(number: float | None) -> bool:
        return number is not None and number > value

    def below_structure(number: float | None) -> bool:
        return number is not None and number < value

    event_type: str | None = None
    direction: str | None = None
    evidence: list[dict[str, Any]] = []
    # A recent wick outside followed by a close back inside is a confirmed
    # failure. It outranks every other pattern by the frozen contract.
    if "above" in allowed_directions and not above_structure(closes[-1]) and _recent_breach_crosses(rows, value, break_buffer, "above"):
        event_type, direction = "failed_break", "above"
        evidence.append({"rule": "recent_high_outside_then_close_inside", "window": "1-3x5m"})
    elif "below" in allowed_directions and not below_structure(closes[-1]) and _recent_breach_crosses(rows, value, break_buffer, "below"):
        event_type, direction = "failed_break", "below"
        evidence.append({"rule": "recent_low_outside_then_close_inside", "window": "1-3x5m"})
    elif "above" in allowed_directions and len(closes) >= 12 and all(above_structure(close) for close in closes[-2:]) and any(
        below_break(close) for close in closes[-12:-3]
    ):
        event_type, direction = "reclaim", "above"
        evidence.append({"rule": "outside_close_4_to_12_bars_ago_then_two_reclaimed_closes"})
    elif "below" in allowed_directions and len(closes) >= 12 and all(below_structure(close) for close in closes[-2:]) and any(
        above_break(close) for close in closes[-12:-3]
    ):
        event_type, direction = "reclaim", "below"
        evidence.append({"rule": "outside_close_4_to_12_bars_ago_then_two_reclaimed_closes"})
    elif "above" in allowed_directions and _has_prior_break(closes, above_break) and abs(price - value) <= retest_threshold and above_structure(price):
        event_type, direction = "retest", "above"
        evidence.append({"rule": "two_prior_outside_closes_then_retest_holds_above"})
    elif "below" in allowed_directions and _has_prior_break(closes, below_break) and abs(price - value) <= retest_threshold and below_structure(price):
        event_type, direction = "retest", "below"
        evidence.append({"rule": "two_prior_outside_closes_then_retest_holds_below"})
    elif _new_break(closes, above_break) and "above" in allowed_directions and _confirmed_15m(candles_15m, value, break_buffer, "above"):
        event_type, direction = "accepted_break", "above"
        evidence.append({"rule": "two_5m_closes_and_completed_15m_close_above_break_buffer"})
    elif _new_break(closes, below_break) and "below" in allowed_directions and _confirmed_15m(candles_15m, value, break_buffer, "below"):
        event_type, direction = "accepted_break", "below"
        evidence.append({"rule": "two_5m_closes_and_completed_15m_close_below_break_buffer"})
    elif _new_break(closes, above_break) and "above" in allowed_directions and _recent_breach_crosses(rows, value, break_buffer, "above"):
        event_type, direction = "intrabar_breach", "above"
        evidence.append({"rule": "break_closes_lack_completed_15m_confirmation"})
    elif _new_break(closes, below_break) and "below" in allowed_directions and _recent_breach_crosses(rows, value, break_buffer, "below"):
        event_type, direction = "intrabar_breach", "below"
        evidence.append({"rule": "break_closes_lack_completed_15m_confirmation"})
    elif (
        "above" in allowed_directions and _intrabar_crosses(rows[-1], value, break_buffer, "above")
    ) or (
        "below" in allowed_directions and _intrabar_crosses(rows[-1], value, break_buffer, "below")
    ):
        direction = "above" if "above" in allowed_directions and _intrabar_crosses(rows[-1], value, break_buffer, "above") else "below"
        event_type = "intrabar_breach"
        evidence.append({"rule": "latest_5m_high_or_low_crossed_break_buffer_without_accepted_confirmation"})
    elif abs(price - value) <= float(thresholds["touch_threshold"] or 0.0):
        event_type = "touch"
        direction = "above" if price >= value else "below"
        evidence.append({"rule": "latest_5m_close_within_touch_threshold"})
    elif abs(price - value) <= float(thresholds["approach_threshold"] or 0.0):
        event_type = "approach"
        direction = "above" if price >= value else "below"
        evidence.append({"rule": "latest_5m_close_within_approach_threshold"})

    if event_type is None or direction is None:
        return None
    confirmed = event_type in {"accepted_break", "failed_break", "retest", "reclaim"}
    return {
        "event_type": event_type,
        "direction": direction,
        "confirmed": confirmed,
        "detected_at": detected_at,
        "price": price,
        "related_level": {
            "role": level.get("role"),
            "value": value,
            "strength": level.get("strength"),
        },
        "break_buffer": break_buffer,
        "confirmation": {
            "five_minute_closes": [close for close in closes[-2:] if close is not None],
            "fifteen_minute_close": _latest_complete_close(candles_15m),
        },
        "evidence": evidence,
        "source_refs": [dict(item) for item in source_refs if isinstance(item, Mapping)],
    }


def _has_prior_break(closes: list[float | None], predicate: Any) -> bool:
    return len(closes) >= 3 and predicate(closes[-2]) and predicate(closes[-3])


def _new_break(closes: list[float | None], predicate: Any) -> bool:
    """Require the two confirmed closes to follow a candle outside the break state."""
    return len(closes) >= 3 and predicate(closes[-1]) and predicate(closes[-2]) and not predicate(closes[-3])


def _allowed_break_directions(level: Mapping[str, Any]) -> set[str]:
    """Map directional options roles to the only structurally valid break side."""
    role = str(level.get("role") or "").lower()
    if "support" in role or "tail" in role:
        return {"below"}
    if "resistance" in role:
        return {"above"}
    return {"above", "below"}


def _recent_breach_crosses(rows: list[Mapping[str, Any]], value: float, buffer: float, direction: str) -> bool:
    """Require a real level crossing, not a candle merely living on that side."""
    for index in range(max(1, len(rows) - 4), len(rows) - 1):
        previous_close = _number(rows[index - 1].get("close"))
        high = _number(rows[index].get("high"))
        low = _number(rows[index].get("low"))
        if direction == "above" and high is not None and high > value + buffer and previous_close is not None and previous_close <= value + buffer:
            return True
        if direction == "below" and low is not None and low < value - buffer and previous_close is not None and previous_close >= value - buffer:
            return True
    return False


def _intrabar_crosses(candle: Mapping[str, Any], value: float, buffer: float, direction: str) -> bool:
    open_price = _number(candle.get("open"))
    close = _number(candle.get("close"))
    if direction == "above":
        high = _number(candle.get("high"))
        return high is not None and high > value + buffer and (open_price is None or open_price <= value + buffer or close <= value + buffer)
    low = _number(candle.get("low"))
    return low is not None and low < value - buffer and (open_price is None or open_price >= value - buffer or close >= value - buffer)


def _confirmed_15m(candles: list[Mapping[str, Any]], value: float, buffer: float, direction: str) -> bool:
    if not candles:
        return False
    latest = candles[-1]
    if latest.get("partial") is True:
        return False
    close = _number(latest.get("close"))
    return close is not None and (close > value + buffer if direction == "above" else close < value - buffer)


def _latest_complete_close(candles: list[Mapping[str, Any]]) -> float | None:
    if not candles or candles[-1].get("partial") is True:
        return None
    return _number(candles[-1].get("close"))


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat()
