"""Capability-specific freshness, with separate TV intraday and official views."""

from copy import deepcopy
from datetime import UTC, datetime


def _time(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(UTC) if d.tzinfo is not None else None
    except ValueError:
        return None


def build_cross_asset_features(observations, *, as_of):
    from apps.features.research.market_session import resolve_market_session
    session = resolve_market_session(as_of)
    now = _time(as_of)
    rows = deepcopy(observations.get("observations", []))
    for row in rows:
        fetched, bar = _time(row.get("retrieved_at")), _time(row.get("minute_bar_time"))
        daily = _time(row.get("provider_bar_time"))
        age = (now - bar).total_seconds() if now and bar else None
        capture_age = (now - fetched).total_seconds() if now and fetched else None
        row.update(bar_age_seconds=age, capture_age_seconds=capture_age, intraday_confirmation_allowed=False)
        if row["status"] != "available":
            status = "MISSING" if row["status"] == "missing" else "INVALID"
        elif now is None or fetched is None or capture_age < 0 or (bar and bar > now) or (daily and daily > now):
            status = "INVALID_TIME"
        elif capture_age > 900:
            status = "STALE_CAPTURE"
        elif session["state"] in {"CLOSED", "HOLIDAY", "EARLY_CLOSE", "MAINTENANCE"}:
            status = "MARKET_CLOSED" if session["state"] == "CLOSED" else "EXPECTED_STALE"
        elif session["state"] == "UNKNOWN":
            status = "SESSION_UNKNOWN"
        elif bar is None:
            status = "DELAYED_CLOCK_UNVERIFIED" if row.get("delay_seconds") else "CLOCK_UNVERIFIED"
        elif age > 900:
            status = "STALE_BAR"
        elif row.get("delay_seconds") is None:
            status = "DELAY_UNVERIFIED"
        elif row["delay_seconds"] > 0:
            status = "DELAYED_BAR"
        else:
            status = "FRESH_MINUTE_BAR"
            row["intraday_confirmation_allowed"] = True
        row["freshness"] = status
        row["display_value"] = row.get("value") if status not in {"INVALID", "INVALID_TIME", "MISSING"} else None
    by_symbol = {r["symbol"]: r for r in rows}
    curves = []
    for left, right in (("US02Y", "US03M"), ("US10Y", "US02Y"), ("US30Y", "US10Y")):
        a, b = by_symbol.get(left, {}), by_symbol.get(right, {})
        aligned = bool(a.get("intraday_confirmation_allowed") and b.get("intraday_confirmation_allowed")
                       and abs((_time(a["minute_bar_time"]) - _time(b["minute_bar_time"])).total_seconds()) <= 120)
        curves.append({"label": left + "−" + right, "value_bp": round((a["value"]-b["value"])*100, 3) if aligned else None,
                       "status": "aligned_minute_bars" if aligned else "unavailable_asynchronous_or_stale",
                       "left_time": a.get("minute_bar_time"), "right_time": b.get("minute_bar_time"),
                       "source_refs": a.get("source_refs", []) + b.get("source_refs", [])})
    def capability(symbols):
        selected = [by_symbol.get(s, {}) for s in symbols]
        if all(r.get("freshness") in {"MARKET_CLOSED", "EXPECTED_STALE"} for r in selected):
            return "MARKET_CLOSED"
        return "ENABLED" if all(r.get("intraday_confirmation_allowed") for r in selected) else "DEGRADED" if any(r.get("display_value") is not None for r in selected) else "UNAVAILABLE"
    capabilities = {"energy_regime_analysis": capability(("BRENT", "WTI")),
                    "tv_price_analysis": capability(("XAUUSD",)), "tv_dollar_analysis": capability(("DXY",)),
                    "tv_nominal_rate_analysis": capability(("US02Y", "US10Y", "US30Y"))}
    failures = ["ENERGY_INTRADAY"] if capabilities["energy_regime_analysis"] not in {"ENABLED", "MARKET_CLOSED"} else []
    result = {"schema_version": "cross_asset_freshness.v1", "as_of": as_of, "market_session": session, "observations": rows,
            "curves": curves, "analysis_capability": capabilities, "critical_freshness_failures": failures,
            "overall_quality": "Partial" if failures or any(v != "ENABLED" for v in capabilities.values()) else "Complete",
            "synchronous_event_attribution_allowed": False,
            "alignment_note": "单次分钟bar快照不构成事件前后收益率；日线time、抓取时间均不是最新成交时间。官方实际利率独立保留。",
            "source_refs": observations.get("source_refs", [])}
    if "chart_series" in observations or "chart_windows" in observations:
        from apps.features.research.chart_windows import build_chart_windows, refresh_chart_windows
        windows = (build_chart_windows(observations["chart_series"], as_of=as_of, anchors=observations.get('window_anchors')) if "chart_series" in observations
                   else refresh_chart_windows(observations["chart_windows"], as_of=as_of))
        result["chart_windows"] = windows
        usable = [w for w in windows["windows"] if w.get("aligned_comparison_allowed")]
        capabilities["aligned_chart_comparison"] = "ENABLED" if usable else "UNAVAILABLE"
        energy = [w for w in usable if w["group"] == "energy"]
        capabilities["energy_window_comparison"] = (
            "HISTORICAL" if energy and energy[0]["comparison_scope"] == "LAST_AVAILABLE_SESSION"
            else "DELAYED" if energy and energy[0]["max_delay_seconds"] else "ENABLED" if energy else "UNAVAILABLE")
        result["alignment_note"] = (
            "chart_windows按共同已完成K线比较；延迟行情可用于标明起止时刻的历史窗口。"
            "实时能力与窗口能力分开，ENERGY_INTRADAY不否定已验证的延迟窗口。"
            "窗口共振不证明新闻因果，官方实际利率独立保留。")
    return result
