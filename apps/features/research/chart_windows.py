"""Comparable completed chart-bar windows; price co-movement is not causal proof."""

from datetime import timedelta

from apps.features.research.cross_asset import _time
from apps.features.research.market_session import resolve_market_session
from apps.parsers.market.tradingview import ALL_INSTRUMENTS, number

GOLD = "OANDA:XAUUSD"
GROUPS = {
    "energy": (GOLD, "NYMEX:CL1!", "ICEEUR:BRN1!"),
    "policy": (GOLD, "TVC:DXY", "TVC:US02Y", "TVC:US10Y"),
}


def build_chart_windows(series, *, as_of, anchors=None):
    now = _time(as_of)
    session = resolve_market_session(as_of)
    healthy, health, seen = {}, [], set()
    for row in series:
        ticker = row.get("ticker")
        delay, interval = row.get("delay_seconds"), row.get("resolution_seconds")
        fetched = _time(row.get("retrieved_at"))
        reason = None
        bars = {}
        if ticker in seen:
            healthy.pop(ticker, None)
            reason = "DUPLICATE_SERIES"
        elif ticker not in ALL_INSTRUMENTS or row.get("status") != "available":
            reason = "SERIES_UNAVAILABLE"
        elif now is None or fetched is None or not 0 <= (now - fetched).total_seconds() <= 900:
            reason = "INVALID_OR_STALE_CAPTURE"
        elif number(delay) is None or delay < 0 or delay > 86400:
            reason = "DELAY_UNVERIFIED"
        elif interval not in (60, 900, 3600):
            reason = "INVALID_RESOLUTION"
        else:
            for bar in row.get("bars", []):
                start, close = _time(bar.get("time")), number(bar.get("close"))
                if start is None or close is None or close <= 0:
                    reason = "INVALID_BAR"
                    break
                end = start + timedelta(seconds=interval)
                # A delayed feed's unfinished bar must not enter the return calculation.
                if end > min(now, fetched) - timedelta(seconds=delay):
                    continue
                if end in bars and bars[end] != close:
                    reason = "CONFLICTING_BAR"
                    break
                bars[end] = close
            if not bars and reason is None:
                reason = "NO_COMPLETED_BARS"
        seen.add(ticker)
        item = {"ticker": ticker, "status": reason or "AVAILABLE", "delay_seconds": delay,
                "resolution_seconds": interval, "completed_bar_count": len(bars),
                "retrieved_at": row.get("retrieved_at"),
                "last_completed_bar_end": max(bars).isoformat() if bars else None,
                "front_contract": row.get("front_contract"), "source_refs": row.get("source_refs", [])}
        health.append(item)
        if reason is None:
            healthy[ticker] = (row, bars)
    groups = dict(GROUPS)
    present = {r.get("ticker") for r in series}
    core = set(GROUPS['energy']) | set(GROUPS['policy'])
    anchor, alignment_delay = None, 0
    if core <= set(healthy) and len({healthy[t][0]['resolution_seconds'] for t in core}) == 1:
        core_ends = set.intersection(*(set(healthy[t][1]) for t in core))
        if core_ends:
            candidate = max(core_ends)
            candidate_delay = max(healthy[t][0]['delay_seconds'] for t in core)
            interval = healthy[GOLD][0]['resolution_seconds']
            if (now - candidate).total_seconds() <= candidate_delay + 2 * interval:
                anchor, alignment_delay = candidate, candidate_delay
    covered = {ticker for tickers in GROUPS.values() if set(tickers) <= set(healthy) for ticker in tickers}
    for ticker in sorted(present - {GOLD, None}):
        if ticker not in covered:
            groups["gold_vs_" + ticker] = (GOLD, ticker)
    windows = []
    for group, tickers in groups.items():
        if not (set(tickers) - {GOLD}) & present:
            continue
        missing = [t for t in tickers if t not in healthy]
        if missing:
            windows.append({"group": group, "status": "UNAVAILABLE", "aligned_comparison_allowed": False,
                            "reason": "MISSING_SERIES", "missing_tickers": missing})
            continue
        selected = [healthy[t] for t in tickers]
        intervals = {row["resolution_seconds"] for row, _ in selected}
        common = set.intersection(*(set(bars) for _, bars in selected))
        if len(intervals) != 1 or not common:
            windows.append({"group": group, "status": "UNAVAILABLE", "aligned_comparison_allowed": False,
                            "reason": "NO_COMMON_RESOLUTION_OR_ENDPOINT"})
            continue
        interval = intervals.pop()
        aligned_ends = {end for end in common if end <= anchor} if anchor else common
        if not aligned_ends:
            windows.append({'group': group, 'status': 'UNAVAILABLE', 'aligned_comparison_allowed': False,
                            'reason': 'NO_ENDPOINT_BEFORE_COMMON_ANCHOR'})
            continue
        end = max(aligned_ends)
        max_delay = max(row["delay_seconds"] for row, _ in selected)
        lag = (now - end).total_seconds()
        closed = session["state"] in {"CLOSED", "HOLIDAY", "EARLY_CLOSE", "MAINTENANCE"}
        effective_delay = max(max_delay, alignment_delay)
        stale = lag > effective_delay + 2 * interval
        for minutes in ((1, 30, 120) if interval == 60 else (15, 60, 120) if interval == 900 else (60, 120)):
            start = end - timedelta(minutes=minutes)
            item = {"group": group, "window_start": start.isoformat(), "window_end": end.isoformat(),
                    "horizon_minutes": minutes, "bar_resolution_seconds": interval,
                    "window_lag_seconds": lag, "max_delay_seconds": max_delay,
                    "alignment_delay_seconds": effective_delay,
                    "common_anchor_end": anchor.isoformat() if anchor else None,
                    "comparison_scope": "LAST_AVAILABLE_SESSION" if closed else "RECENT_COMPLETED_WINDOW",
                    "aligned_comparison_allowed": False, "status": "UNAVAILABLE", "changes": []}
            # Do not interpolate missing bars or combine sessions/continuous-contract roll dates.
            required = {start + timedelta(seconds=i * interval) for i in range(minutes * 60 // interval + 1)}
            if start.date() != end.date():
                item["reason"] = "CROSS_DATE_WINDOW_EXCLUDED"
            elif any(not required <= set(bars) for _, bars in selected):
                item["reason"] = "MISSING_ENDPOINT_OR_INTERIOR_BAR"
            elif (stale and not closed) or lag > 96 * 3600:
                item.update(status="STALE", reason="COMMON_WINDOW_TOO_OLD")
            elif session["state"] == "UNKNOWN":
                item["reason"] = "SESSION_UNKNOWN"
            else:
                item.update(status="AVAILABLE_DELAYED" if effective_delay else "AVAILABLE",
                            aligned_comparison_allowed=True)
                for row, bars in selected:
                    ticker = row["ticker"]
                    symbol, instrument, unit, _ = ALL_INSTRUMENTS[ticker]
                    change = {"ticker": ticker, "symbol": symbol, "unit": unit,
                              "start_close": bars[start], "end_close": bars[end],
                              "delay_seconds": row["delay_seconds"], "front_contract": row.get("front_contract"),
                              "source_refs": row.get("source_refs", [])}
                    if instrument == "bond":
                        change["change_bp"] = round((bars[end] - bars[start]) * 100, 4)
                    else:
                        change["change_pct"] = round((bars[end] / bars[start] - 1) * 100, 5)
                    item["changes"].append(change)
            windows.append(item)
    from apps.features.research.multi_horizon import build_multi_horizon
    multi = build_multi_horizon(healthy, groups=groups, now=now, session=session, anchors=anchors)
    return {"schema_version": "cross_asset_chart_windows.v1", "as_of": as_of,
            'multi_horizon': multi,
            "alignment_reference_tickers": sorted(core) if anchor else [],
            "series_health": health, "windows": windows, "causal_attribution_allowed": False,
            "limitations": ["共同已完成K线收盘到收盘变化，不是实时成交或已证实新闻因果。",
                            "期货保留连续合约坐标；跨日期窗口排除，日内换月影响仍需核验。",
                            "国债为名义收益率代理，不生成分钟级官方实际利率。"]}


def refresh_chart_windows(windows, *, as_of):
    """Recheck compact frozen evidence without reopening or rewriting upstream bars."""
    from copy import deepcopy
    result = deepcopy(windows)
    now = _time(as_of)
    closed = resolve_market_session(as_of)["state"] in {"CLOSED", "HOLIDAY", "EARLY_CLOSE", "MAINTENANCE"}
    result["as_of"] = as_of
    health = {r["ticker"]: r for r in result.get("series_health", [])}
    for item in result.get("windows", []):
        if not item.get("aligned_comparison_allowed"):
            continue
        end = _time(item.get("window_end"))
        lag = (now - end).total_seconds() if now and end else -1
        limit = 96 * 3600 if closed else max(item["max_delay_seconds"], item.get('alignment_delay_seconds', 0)) + 2 * item["bar_resolution_seconds"]
        item["window_lag_seconds"] = lag
        captured = [_time(health.get(r["ticker"], {}).get("retrieved_at")) for r in item.get("changes", [])]
        if not now or not captured or any(not t or not 0 <= (now - t).total_seconds() <= 900 for t in captured):
            item.update(status="STALE", aligned_comparison_allowed=False, reason="INVALID_OR_STALE_CAPTURE")
        elif not 0 <= lag <= limit:
            item.update(status="STALE", aligned_comparison_allowed=False, reason="COMMON_WINDOW_TOO_OLD")
        item["comparison_scope"] = "LAST_AVAILABLE_SESSION" if closed else "RECENT_COMPLETED_WINDOW"
    for item in result.get('multi_horizon', {}).get('rows', []):
        if not item.get('aligned_comparison_allowed'):
            continue
        selected = [health.get(r['ticker'], {}) for r in item['changes']]
        captures = [_time(r.get('retrieved_at')) for r in selected]
        ends = [_time(r.get('last_completed_bar_end')) for r in selected]
        endpoint = _time(item.get('alignment_endpoint') or item.get('window_end'))
        limit = 96 * 3600 if closed else item['alignment_delay_seconds'] + 2 * item['bar_resolution_seconds']
        if (not now or not captures or any(not t or not 0 <= (now - t).total_seconds() <= 900 for t in captures)
                or not endpoint or not 0 <= (now - endpoint).total_seconds() <= limit
                or any(not t or not 0 <= (now - t).total_seconds() <= limit for t in ends)):
            item.update(status='STALE', aligned_comparison_allowed=False, reason='STALE_CAPTURE_OR_SERIES')
    return result
