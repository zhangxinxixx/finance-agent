"""Adapt verified provider-native gold bars into the existing PA input."""

from copy import deepcopy
from datetime import timedelta

from apps.features.research.timeframes import build_execution_timeframe_features, _parse_utc

PERIODS = {900: ("15m", "15min"), 3600: ("1h", "1h"), 14400: ("4h", "4h")}


def stale_execution_timeframes(existing, *, as_of, analysis_date):
    """Return only frames that cannot pass the final PA freshness gate."""
    now = _parse_utc(as_of)
    frames = (existing or {}).get("timeframes", {})
    checked = build_execution_timeframe_features(frames, analysis_date=analysis_date)
    return [key for seconds, (key, _) in PERIODS.items()
            if not _usable(checked.get(key, {}), now, seconds)]


def merge_tradingview_execution(existing, series, *, as_of, analysis_date):
    """Prefer usable primary bars; fill missing frames with lineaged TV spot bars.

    No quotes, futures proxies, delayed/unknown clocks, resampling, or synthetic
    candles enter this adapter. Source errors remain visible in diagnostics.
    """
    now = _parse_utc(as_of)
    frames = deepcopy((existing or {}).get("timeframes", {}))
    diagnostics = {}
    for item in series:
        seconds = item.get("resolution_seconds")
        if item.get("ticker") != "OANDA:XAUUSD" or seconds not in PERIODS:
            continue
        key, interval = PERIODS[seconds]
        retrieved = _parse_utc(item.get("retrieved_at"))
        refs = item.get("source_refs") or []
        refs = [r for r in refs if r.get("source") == "tradingview_chart"
                and r.get("ticker") == "OANDA:XAUUSD" and r.get("raw_path")
                and _parse_utc(r.get("retrieved_at")) == retrieved]
        if (item.get("status") != "available" or item.get("delay_seconds") != 0
                or not now or not retrieved or retrieved > now or not refs):
            diagnostics[key] = item.get("error") or "unverified_chart_source_or_clock"
            continue
        closed_before = retrieved - timedelta(seconds=75)
        bars = []
        for bar in item.get("bars", []):
            opened = _parse_utc(bar.get("time"))
            if opened is None:
                continue
            closed = opened + timedelta(seconds=seconds)
            if closed <= closed_before:
                bars.append({**bar, "open_time": opened.isoformat(), "close_time": closed.isoformat()})
        raw = {"status": "available", "timeframe": key, "interval": interval,
               "ticker": "OANDA:XAUUSD", "timezone": "UTC", "instrument_type": "spot",
               "retrieved_at": retrieved.isoformat(), "closed_before": closed_before.isoformat(),
               "raw_path": refs[0]["raw_path"], "source_refs": deepcopy(refs), "bars": bars}
        candidate = build_execution_timeframe_features({key: raw}, analysis_date=analysis_date)[key]
        old = build_execution_timeframe_features({key: frames.get(key, {})}, analysis_date=analysis_date)[key]
        if _usable(old, now, seconds):
            continue
        if _usable(candidate, now, seconds):
            frames[key] = candidate
        else:
            diagnostics[key] = candidate.get("reason") or "missing_stale_or_gapped_bars"
    return {"status": "available" if any(v.get("status") == "available" for v in frames.values()) else "unavailable",
            "timeframes": frames, "fallback_diagnostics": diagnostics}


def _usable(item, now, seconds):
    latest = _parse_utc(item.get("latest_closed_time"))
    retrieved = _parse_utc(item.get("retrieved_at"))
    return bool(now and retrieved and latest and retrieved <= now and item.get("raw_path")
                and item.get("status") == "available" and item.get("bar_count", 0) >= 5
                and item.get("continuity_status") != "gapped"
                and 0 <= (now - latest).total_seconds() <= seconds + 300)
