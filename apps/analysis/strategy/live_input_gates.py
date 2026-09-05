"""Fail-closed input gates for the deterministic live strategy read model.

The market candle service exposes candle ``time`` as the bar open.  This
module keeps the close-time, completeness, and UTC scope rules in one place so
the live strategy cannot accidentally treat an open bar or a stale daily
context as a new trigger.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any


CANONICAL_CANDLE_DURATION_SECONDS = 5 * 60
CANONICAL_15M_CANDLE_DURATION_SECONDS = 15 * 60
CANONICAL_FRESHNESS_SECONDS = 10 * 60
CLOCK_SKEW_TOLERANCE_SECONDS = 30

_CANDLE_INTERVALS = {
    "5m": timedelta(seconds=CANONICAL_CANDLE_DURATION_SECONDS),
    "15m": timedelta(seconds=CANONICAL_15M_CANDLE_DURATION_SECONDS),
}
_CANDLE_REASON_PREFIXES = {
    "5m": "canonical_candle",
    "15m": "canonical_15m",
}


def evaluate_live_input_gates(
    *,
    canonical_market: Mapping[str, Any] | None,
    canonical_market_15m: Mapping[str, Any] | None,
    options_decision: Mapping[str, Any] | None,
    effective_trade_date: Any,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Evaluate all live input gates without changing any input payload."""

    current_time = _as_utc(now)
    canonical_5m = evaluate_candle_gate(
        canonical_market,
        timeframe="5m",
        now=current_time,
    )
    canonical_15m = evaluate_candle_gate(
        canonical_market_15m,
        timeframe="15m",
        now=current_time,
        reference_close_at=_parse_datetime(canonical_5m.get("closed_at")),
    )
    cme = evaluate_cme_gate(
        options_decision,
        expected_trade_date=effective_trade_date,
    )
    scope = evaluate_utc_scope_gate(
        effective_trade_date=effective_trade_date,
        cme_trade_date=cme.get("trade_date"),
        canonical_5m_close_at=_parse_datetime(canonical_5m.get("closed_at")),
    )
    return {
        "canonical_5m": canonical_5m,
        "canonical_15m": canonical_15m,
        "cme": cme,
        "utc_scope": scope,
    }


def evaluate_candle_gate(
    market: Mapping[str, Any] | None,
    *,
    timeframe: str,
    now: datetime,
    reference_close_at: datetime | None = None,
) -> dict[str, Any]:
    """Check one latest OHLC bar for complete, aligned, closed input.

    A bar is never considered closed because it is within the clock-skew
    tolerance.  Its calculated close must be at or before ``now``; the
    tolerance remains useful for supplemental quote timestamps elsewhere.
    """

    if timeframe not in _CANDLE_INTERVALS:
        raise ValueError(f"unsupported live candle timeframe: {timeframe}")
    prefix = _CANDLE_REASON_PREFIXES[timeframe]
    rows = [item for item in (market or {}).get("candles") or [] if isinstance(item, Mapping)]
    latest = dict(rows[-1]) if rows else None
    if latest is None:
        return _candle_result(
            status="missing" if timeframe == "15m" else "unavailable",
            reason_code=(f"{prefix}_missing" if timeframe == "15m" else f"{prefix}_unavailable"),
        )

    open_at = _parse_datetime(latest.get("time"))
    if open_at is None:
        return _candle_result(
            status="invalid",
            reason_code=f"{prefix}_misaligned" if timeframe == "15m" else f"{prefix}_unavailable",
            timestamp=latest.get("time"),
        )
    close_at = open_at + _CANDLE_INTERVALS[timeframe]
    freshness_seconds = int((now - close_at).total_seconds())
    common = {
        "timestamp": latest.get("time"),
        "closed_at": close_at.isoformat(),
        "freshness_seconds": freshness_seconds,
    }

    if _explicitly_incomplete(latest):
        return _candle_result(status="partial", reason_code=f"{prefix}_partial", **common)
    if not _valid_ohlc(latest):
        return _candle_result(status="invalid", reason_code=f"{prefix}_invalid", **common)
    # This check intentionally has no clock-skew allowance.  A still-open bar
    # cannot be used to confirm a live strategy event.
    if close_at > now:
        return _candle_result(status="future", reason_code=f"{prefix}_future", **common)
    if not _utc_open_is_aligned(open_at, timeframe):
        return _candle_result(status="misaligned", reason_code=f"{prefix}_misaligned", **common)
    window_reason = _window_reason(rows, timeframe=timeframe, now=now)
    if window_reason is not None:
        status, reason_code = window_reason
        return _candle_result(status=status, reason_code=reason_code, **common)
    if timeframe == "15m" and reference_close_at is not None:
        expected_close_at = _floor_to_interval(reference_close_at, _CANDLE_INTERVALS[timeframe])
        common["expected_closed_at"] = expected_close_at.isoformat()
        if close_at < expected_close_at:
            return _candle_result(status="stale", reason_code=f"{prefix}_stale", **common)
        if close_at > expected_close_at:
            return _candle_result(status="misaligned", reason_code=f"{prefix}_scope_mismatch", **common)
    if timeframe == "5m" and freshness_seconds > CANONICAL_FRESHNESS_SECONDS:
        return _candle_result(status="stale", reason_code=f"{prefix}_stale", **common)
    return _candle_result(status="available", reason_code=None, ready=True, **common)


def evaluate_cme_gate(
    options_decision: Mapping[str, Any] | None,
    *,
    expected_trade_date: Any,
) -> dict[str, Any]:
    """Require the existing options decision to be available and FINAL."""

    decision = dict(options_decision or {})
    meta = decision.get("meta") if isinstance(decision.get("meta"), Mapping) else {}
    quality = decision.get("data_quality") if isinstance(decision.get("data_quality"), Mapping) else {}
    options_status = decision.get("status")
    source_status = quality.get("cme_status")
    trade_date = normalize_trade_date(meta.get("current_trade_date"))
    expected_date = normalize_trade_date(expected_trade_date)
    reasons: list[str] = []
    if options_status != "available":
        reasons.append("cme_unavailable")
    if source_status != "FINAL":
        reasons.append("cme_quality_not_final")
    if trade_date is None:
        reasons.append("cme_trade_date_unavailable")
    elif expected_date is not None and trade_date != expected_date:
        reasons.append("cme_gold_trade_date_mismatch")
    return {
        "ready": not reasons,
        "status": "available" if not reasons else "blocked",
        "reason_code": reasons[0] if reasons else None,
        "reasons": reasons,
        "options_status": options_status,
        "source_status": source_status,
        "trade_date": trade_date,
        "expected_trade_date": expected_date,
    }


def evaluate_utc_scope_gate(
    *,
    effective_trade_date: Any,
    cme_trade_date: Any,
    canonical_5m_close_at: datetime | None,
) -> dict[str, Any]:
    """Ensure the live 5m bar remains in the effective daily input scope."""

    effective_date = normalize_trade_date(effective_trade_date)
    cme_date = normalize_trade_date(cme_trade_date)
    candle_date = canonical_5m_close_at.date().isoformat() if canonical_5m_close_at else None
    reasons: list[str] = []
    if effective_date is not None and cme_date is not None and effective_date != cme_date:
        reasons.append("cme_gold_trade_date_mismatch")
    if effective_date is not None and candle_date is not None and effective_date != candle_date:
        reasons.append("live_candle_scope_mismatch")
    if cme_date is not None and candle_date is not None and cme_date != candle_date:
        reasons.append("live_candle_cme_scope_mismatch")
    return {
        "ready": not reasons,
        "status": "aligned" if not reasons else "misaligned",
        "reason_code": reasons[0] if reasons else None,
        "reasons": list(dict.fromkeys(reasons)),
        "effective_trade_date": effective_date,
        "cme_trade_date": cme_date,
        "canonical_5m_trade_date": candle_date,
    }


def normalize_trade_date(value: Any) -> str | None:
    """Return one UTC ``YYYY-MM-DD`` date for date or ISO timestamp input."""

    if isinstance(value, datetime):
        parsed = _parse_datetime(value)
        return parsed.date().isoformat() if parsed is not None else None
    if isinstance(value, date):
        return value.isoformat()
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        parsed = _parse_datetime(raw)
        return parsed.date().isoformat() if parsed is not None else None


def _candle_result(*, status: str, reason_code: str | None, ready: bool = False, **values: Any) -> dict[str, Any]:
    return {
        "ready": ready,
        "status": status,
        "reason_code": reason_code,
        "timestamp": values.get("timestamp"),
        "closed_at": values.get("closed_at"),
        "expected_closed_at": values.get("expected_closed_at"),
        "freshness_seconds": values.get("freshness_seconds"),
    }


def _explicitly_incomplete(candle: Mapping[str, Any]) -> bool:
    for key in ("partial", "is_partial"):
        if candle.get(key) is True:
            return True
    for key in ("closed", "is_closed", "complete", "completed"):
        if key in candle and candle.get(key) is False:
            return True
    return False


def _valid_ohlc(candle: Mapping[str, Any]) -> bool:
    values = tuple(_number(candle.get(key)) for key in ("open", "high", "low", "close"))
    if any(value is None or not math.isfinite(value) or value <= 0 for value in values):
        return False
    open_value, high, low, close = values
    return low <= open_value <= high and low <= close <= high and low <= high


def _floor_to_interval(value: datetime, interval: timedelta) -> datetime:
    """Return the UTC close bucket containing ``value``.

    Candle ``time`` is the bar open, while the reference passed by the 5m
    gate is its close.  Flooring the close to the 15m boundary therefore picks
    the latest complete 15m bucket available at that exact 5m close.
    """
    seconds = int(interval.total_seconds())
    epoch_seconds = int(value.timestamp())
    return datetime.fromtimestamp(epoch_seconds - (epoch_seconds % seconds), tz=timezone.utc)


def _utc_open_is_aligned(open_at: datetime, timeframe: str) -> bool:
    interval_minutes = 5 if timeframe == "5m" else 15
    return open_at.minute % interval_minutes == 0 and open_at.second == 0 and open_at.microsecond == 0


def _window_reason(
    rows: list[Mapping[str, Any]],
    *,
    timeframe: str,
    now: datetime,
) -> tuple[str, str] | None:
    """Validate the bars actually consumed by ATR and price-event rules."""
    if timeframe != "5m":
        return None
    window = rows[-15:]
    previous_open: datetime | None = None
    for row in window:
        open_at = _parse_datetime(row.get("time"))
        if open_at is None or not _utc_open_is_aligned(open_at, timeframe):
            return "misaligned", "canonical_candle_window_misaligned"
        if _explicitly_incomplete(row):
            return "partial", "canonical_candle_window_partial"
        if not _valid_ohlc(row):
            return "invalid", "canonical_candle_window_invalid"
        if open_at + _CANDLE_INTERVALS[timeframe] > now:
            return "future", "canonical_candle_window_future"
        if previous_open is not None and open_at - previous_open != _CANDLE_INTERVALS[timeframe]:
            return "misaligned", "canonical_candle_window_gap"
        previous_open = open_at
    return None


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value) if value.tzinfo is not None else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed) if parsed.tzinfo is not None else None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
