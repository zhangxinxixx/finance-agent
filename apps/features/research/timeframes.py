"""Pure execution-timeframe structure features for XAU/USD spot bars."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any, Mapping
from zoneinfo import ZoneInfo

OANDA_GOLD_SESSION_REF = {
    "source": "oanda_trading_hours",
    "source_url": "https://www.oanda.com/uk-en/trading/hours-of-operation/",
    "rule_version": "oanda_xauusd_hours.2026-09-28",
    "timezone": "America/New_York",
    "regular_hours": "Sun-Fri 18:05-16:59",
}

_TIMEFRAME_SECONDS = {"5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400}
_INTERVAL_SECONDS = {"5min": 300, "15min": 900, "1h": 3_600, "4h": 14_400}
_MAX_LATEST_AGE_SECONDS = {"5m": 15 * 60, "15m": 45 * 60, "1h": 3 * 3_600, "4h": 12 * 3_600}


def build_execution_timeframe_features(
    raw: dict[str, Any],
    *,
    session_quality: Mapping[str, Any] | None = None,
    analysis_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build conservative trend/range-break facts from completed bars.

    The collector filters provider responses, but this pure layer verifies the
    archived payload again. A structure event is a prior-five-bar range-break
    proxy; it is never promoted to a swing-pivot BOS confirmation.
    """

    result: dict[str, dict[str, Any]] = {}
    for timeframe, item in raw.items():
        key = str(timeframe)
        session = _session_context(session_quality or (item.get("session_quality") if isinstance(item, dict) else None))
        if not isinstance(item, dict):
            result[key] = {
                "status": "unavailable",
                "reason": "invalid_timeframe_payload",
                **session,
                "execution_eligible": False,
            }
            continue
        normalized_timeframe = str(item.get("timeframe") or key)
        expected_seconds = _TIMEFRAME_SECONDS.get(normalized_timeframe) or _INTERVAL_SECONDS.get(
            str(item.get("interval") or "")
        )
        retrieved_at = _parse_utc(item.get("retrieved_at"))
        closed_before = _parse_utc(item.get("closed_before"))
        bars, rejected = _valid_bars(
            item.get("bars"),
            expected_seconds=expected_seconds,
            retrieved_at=retrieved_at,
            closed_before=closed_before,
            analysis_date=analysis_date or item.get("analysis_date"),
        )
        continuity = _continuity_status(bars, expected_seconds, item=item)
        base = {
            "timeframe": normalized_timeframe,
            "interval": item.get("interval"),
            "instrument_type": "spot",
            "timezone": item.get("timezone", "UTC"),
            "retrieved_at": item.get("retrieved_at"),
            "closed_before": item.get("closed_before"),
            "raw_path": item.get("raw_path"),
            "ticker": item.get("ticker"),
            "source_refs": item.get("source_refs", []),
            "latest_closed_time": bars[-1]["close_time"] if bars else None,
            "bar_count": len(bars),
            "basis": "completed_bars_only",
            "trend_method": "last_3_closed_closes_monotonic",
            "structure_method": "prior_5_bar_range_break_proxy",
            "continuity_status": continuity,
            "continuity_source_refs": [dict(OANDA_GOLD_SESSION_REF)] if continuity == "continuous_over_scheduled_breaks" else [],
            "rejected_bar_count": rejected,
            "bars": bars,
            **session,
        }
        if not bars:
            base.update(
                {
                    "status": item.get("status", "unavailable"),
                    "reason": item.get("reason")
                    or item.get("error")
                    or ("no_completed_bars" if item.get("status") == "partial" else "no_valid_completed_bars"),
                    "trend": "unavailable",
                    "structure_status": "unavailable",
                    "events": [],
                }
            )
            _apply_session_quality(base, session)
            result[key] = base
            continue

        latest_stale = _latest_is_stale(
            bars=bars[-1],
            retrieved_at=retrieved_at,
            timeframe=normalized_timeframe,
        )
        if latest_stale:
            base.update(
                {
                    "status": "stale",
                    "reason": "latest_completed_bar_expired_for_execution",
                    "trend": "stale",
                    "structure_status": "stale_latest_bar",
                    "events": [],
                }
            )
            _apply_session_quality(base, session)
            result[key] = base
            continue

        events = _structure_events(bars)
        base.update(
            {
                "status": "available" if len(bars) >= 3 else "partial",
                "trend": _trend(bars),
                "structure_status": (
                    "observed_proxy_gapped"
                    if events and continuity == "gapped"
                    else "observed_proxy"
                    if events
                    else "no_confirmed_event"
                ),
                "events": events,
            }
        )
        _apply_session_quality(base, session)
        result[key] = base
    return result


def _valid_bars(
    value: Any,
    *,
    expected_seconds: int | None,
    retrieved_at: datetime | None,
    closed_before: datetime | None,
    analysis_date: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list) or expected_seconds is None or retrieved_at is None or closed_before is None:
        return [], len(value) if isinstance(value, list) else 0
    bars: list[dict[str, Any]] = []
    rejected = 0
    seen: set[tuple[datetime, datetime]] = set()
    for item in value:
        if not isinstance(item, dict):
            rejected += 1
            continue
        required = ("open_time", "close_time", "open", "high", "low", "close")
        if any(key not in item for key in required):
            rejected += 1
            continue
        open_time = _parse_utc(item.get("open_time"))
        close_time = _parse_utc(item.get("close_time"))
        if open_time is None or close_time is None:
            rejected += 1
            continue
        if (open_time, close_time) in seen or close_time - open_time != timedelta(seconds=expected_seconds):
            rejected += 1
            continue
        # Both gates matter: the bar must be closed before the provider's
        # declared cutoff and must not be in the future of retrieval.
        if close_time > closed_before or close_time > retrieved_at:
            rejected += 1
            continue
        if _future_bar(open_time, analysis_date):
            rejected += 1
            continue
        try:
            numbers = {key: float(item[key]) for key in ("open", "high", "low", "close")}
        except (TypeError, ValueError):
            rejected += 1
            continue
        if any(not isfinite(number) for number in numbers.values()):
            rejected += 1
            continue
        if (
            numbers["high"] < max(numbers["open"], numbers["close"])
            or numbers["low"] > min(numbers["open"], numbers["close"])
            or numbers["high"] < numbers["low"]
        ):
            rejected += 1
            continue
        seen.add((open_time, close_time))
        bars.append(
            {
                **item,
                "open_time": open_time.isoformat(),
                "close_time": close_time.isoformat(),
                **numbers,
            }
        )
    return sorted(bars, key=lambda item: str(item["close_time"])), rejected


def _latest_is_stale(*, bars: dict[str, Any], retrieved_at: datetime | None, timeframe: str) -> bool:
    if retrieved_at is None:
        return True
    close_time = _parse_utc(bars.get("close_time"))
    max_age = _MAX_LATEST_AGE_SECONDS.get(timeframe)
    if close_time is None or max_age is None:
        return True
    return (retrieved_at - close_time).total_seconds() > max_age


def _continuity_status(bars: list[dict[str, Any]], expected_seconds: int | None, *, item=None) -> str:
    if len(bars) < 2 or expected_seconds is None:
        return "unknown"
    scheduled = False
    for previous, current in zip(bars, bars[1:]):
        end, start = _parse_utc(previous["close_time"]), _parse_utc(current["open_time"])
        if end == start:
            continue
        if not _oanda_scheduled_break(end, start, item or {}):
            return "gapped"
        scheduled = True
    return "continuous_over_scheduled_breaks" if scheduled else "continuous"


def _oanda_scheduled_break(start, end, item):
    """Only recognize regular NY maintenance/weekends for lineaged OANDA gold.

    Holidays and unexplained missing trading bars remain gaps. Never fill a bar.
    """
    if (item.get("ticker") != "OANDA:XAUUSD" or not start or not end
            or not 0 < (end - start).total_seconds() <= 72 * 3600
            or not any(r.get("source") == "tradingview_chart" and r.get("ticker") == "OANDA:XAUUSD"
                       and r.get("raw_path") == item.get("raw_path") for r in item.get("source_refs", []))):
        return False
    cursor = start
    while cursor < end:
        local = cursor.astimezone(ZoneInfo("America/New_York"))
        minute = local.hour * 60 + local.minute
        closed = (local.weekday() == 5 or local.weekday() == 4 and minute >= 16 * 60 + 59
                  or local.weekday() == 6 and minute < 18 * 60 + 5
                  or 16 * 60 + 59 <= minute < 18 * 60 + 5)
        if not closed:
            return False
        cursor = min(end, cursor + timedelta(minutes=1))
    return True


def _trend(bars: list[dict[str, Any]]) -> str:
    if len(bars) < 3:
        return "unavailable"
    first, previous, latest = bars[-3], bars[-2], bars[-1]
    if latest["close"] > previous["close"] > first["close"]:
        return "bullish"
    if latest["close"] < previous["close"] < first["close"]:
        return "bearish"
    return "range_or_mixed"


def _structure_events(bars: list[dict[str, Any]], *, lookback: int = 5) -> list[dict[str, Any]]:
    if len(bars) <= lookback:
        return []
    latest = bars[-1]
    prior = bars[-(lookback + 1) : -1]
    prior_high = max(item["high"] for item in prior)
    prior_low = min(item["low"] for item in prior)
    events: list[dict[str, Any]] = []
    if latest["close"] > prior_high:
        events.append(
            {
                "type": "bos_up",
                "classification": "prior_5_bar_range_break_proxy",
                "confirmed": False,
                "bar_time": latest["close_time"],
                "level": prior_high,
                "evidence": "latest completed close exceeded prior 5-bar high; swing pivot confirmation unavailable",
            }
        )
    elif latest["close"] < prior_low:
        events.append(
            {
                "type": "bos_down",
                "classification": "prior_5_bar_range_break_proxy",
                "confirmed": False,
                "bar_time": latest["close_time"],
                "level": prior_low,
                "evidence": "latest completed close fell below prior 5-bar low; swing pivot confirmation unavailable",
            }
        )
    if latest["high"] > prior_high and latest["close"] <= prior_high:
        events.append(
            {
                "type": "failed_breakout_up",
                "classification": "prior_5_bar_range_break_proxy",
                "confirmed": False,
                "bar_time": latest["close_time"],
                "level": prior_high,
                "evidence": "latest completed high breached prior high but close reclaimed below it",
            }
        )
    if latest["low"] < prior_low and latest["close"] >= prior_low:
        events.append(
            {
                "type": "failed_breakout_down",
                "classification": "prior_5_bar_range_break_proxy",
                "confirmed": False,
                "bar_time": latest["close_time"],
                "level": prior_low,
                "evidence": "latest completed low breached prior low but close reclaimed above it",
            }
        )
    return events


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _session_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "session_class": None,
            "liquidity_class": None,
            "session_quality_status": None,
            "session_confidence_multiplier": 1.0,
            "session_source_refs": [],
            "otc_daily_close": {},
            "otc": {},
            "cme_settlement": {},
        }
    return {
        "session_class": value.get("session_class") or value.get("session_status"),
        "liquidity_class": value.get("liquidity_class"),
        "session_quality_status": value.get("status") or value.get("session_class"),
        "session_confidence_multiplier": value.get("confidence_multiplier", 1.0),
        "session_source_refs": [dict(item) for item in value.get("source_refs", []) if isinstance(item, Mapping)],
        "otc_daily_close": value.get("otc_daily_close") or value.get("otc") or {},
        "otc": value.get("otc") or value.get("otc_daily_close") or {},
        "cme_settlement": value.get("cme_settlement") or value.get("cme") or {},
    }


def _apply_session_quality(base: dict[str, Any], session: dict[str, Any]) -> None:
    session_class = str(session.get("session_class") or "").upper()
    liquidity_class = str(session.get("liquidity_class") or "").upper()
    status = str(base.get("status") or "unavailable")
    eligible = status == "available" and bool(base.get("bars"))
    reason = None
    if session_class == "PARTIAL":
        base["status"] = "partial" if status == "available" else status
        eligible = False
        reason = "session_quality_partial"
    elif liquidity_class == "LOW_LIQUIDITY" or session_class == "LOW_LIQUIDITY":
        eligible = False
        reason = "low_liquidity_session"
    elif session_class == "HOLIDAY":
        otc = session.get("otc_daily_close") or session.get("otc") or {}
        if status != "available" or not isinstance(otc, Mapping) or otc.get("status") != "available":
            eligible = False
            reason = "holiday_otc_observation_not_verified"
    elif session_class == "EARLY_CLOSE" and status != "available":
        eligible = False
        reason = "early_close_without_complete_intraday_bars"
    elif status != "available":
        eligible = False
    base["execution_eligible"] = eligible
    base["execution_reason"] = reason or ("session_and_completed_bar_checks_passed" if eligible else base.get("reason"))


def _future_bar(open_time: datetime, analysis_date: Any) -> bool:
    if not isinstance(analysis_date, str) or not analysis_date.strip():
        return False
    try:
        cutoff = date.fromisoformat(analysis_date.strip()[:10])
    except (AttributeError, TypeError, ValueError):
        return False
    return open_time.date() > cutoff


__all__ = ["build_execution_timeframe_features"]
