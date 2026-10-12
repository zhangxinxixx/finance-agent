"""Causal confirmed pivots and zone interactions on completed bars only."""

from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from copy import deepcopy

from apps.features.research.timeframes import build_execution_timeframe_features
from apps.features.research.sessions import build_session_quality


def _time(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else None
    except ValueError:
        return None


def analyze_bars(bars, *, zones=(), known_at=None):
    pivots, events, last, labels = [], [], {}, {}
    trend = "unconfirmed"
    broken = set()
    zone_states = [
        {
            "price": z.get("price"),
            "low": z["display_lower"],
            "high": z["display_upper"],
            "role": "support" if z["role"] in {"support", "event_low"} else "resistance",
            "state": "WATCH",
            "events": [],
        }
        for z in zones
        if z.get("zone_status") == "available"
        and z.get("eligible_for_target")
        and z.get("role") in {"support", "resistance", "event_low", "event_high"}
    ]
    available = _time(known_at)
    for i, bar in enumerate(bars):
        stamp = bar["close_time"]
        # Only pivots already confirmed on earlier bars may be broken.
        for side, direction in [("high", "bullish"), ("low", "bearish")]:
            pivot = last.get(side)
            if not pivot or (side, pivot["index"]) in broken or i == 0:
                continue
            value = pivot["price"]
            crossed = (
                bars[i - 1]["close"] <= value < bar["close"]
                if side == "high"
                else bars[i - 1]["close"] >= value > bar["close"]
            )
            if crossed:
                kind = "STRUCTURE_BREAK" if trend == "unconfirmed" else "BOS" if trend == direction else "CHoCH"
                events.append(
                    {
                        "type": kind,
                        "direction": direction,
                        "price": value,
                        "time": stamp,
                        "pivot_time": pivot["pivot_time"],
                        "pivot_confirmed_at": pivot["confirmed_at"],
                    }
                )
                broken.add((side, pivot["index"]))
        j = i - 2
        if j >= 2:
            for side in ("high", "low"):
                value = bars[j][side]
                neighbours = [bars[n][side] for n in range(j - 2, j + 3) if n != j]
                hit = all(value > v for v in neighbours) if side == "high" else all(value < v for v in neighbours)
                if hit:
                    old = last.get(side)
                    label = (
                        ("HH" if value > old["price"] else "LH" if value < old["price"] else "EQH")
                        if side == "high" and old
                        else (
                            ("HL" if value > old["price"] else "LL" if value < old["price"] else "EQL")
                            if old
                            else "FIRST"
                        )
                    )
                    p = {
                        "index": j,
                        "side": side,
                        "price": value,
                        "label": label,
                        "pivot_time": bars[j]["close_time"],
                        "confirmed_at": stamp,
                    }
                    pivots.append(p)
                    last[side] = p
                    labels[side] = label
                    trend = (
                        "bullish"
                        if labels == {"high": "HH", "low": "HL"}
                        else "bearish"
                        if labels == {"high": "LH", "low": "LL"}
                        else "unconfirmed"
                    )
        span, body = bar["high"] - bar["low"], abs(bar["close"] - bar["open"])
        if span > 0:
            lower = min(bar["open"], bar["close"]) - bar["low"]
            upper = bar["high"] - max(bar["open"], bar["close"])
            for side, wick in [("lower", lower), ("upper", upper)]:
                if wick >= 2 * body and wick / span >= 0.5:
                    events.append(
                        {"type": "CANDLE_REJECTION", "side": side, "time": stamp, "wick_fraction": wick / span}
                    )
        if available is None or _time(stamp) <= available:
            continue
        for z in zone_states:
            close = bar["close"]
            lo, hi = z["low"], z["high"]
            support = z["role"] == "support"
            outside = close < lo if support else close > hi
            inside = close >= lo if support else close <= hi
            touched = bar["high"] >= lo and bar["low"] <= hi
            prior = z["state"]
            event = None
            if prior == "BROKEN_PENDING":
                if inside:
                    z["state"] = "RECLAIMED"
                    event = "RECLAIM"
                elif touched:
                    z["state"] = "FLIPPED"
                    event = "RETEST_FAILED"
                    z["role"] = "resistance" if support else "support"
            elif outside:
                z["state"] = "BROKEN_PENDING"
                event = "ZONE_BREAK"
            elif touched:
                z["state"] = "DEFENDED"
                event = "ZONE_TEST"
            if event:
                z["events"].append({"type": event, "time": stamp, "close": close})
    return {
        "status": "available" if len(bars) >= 5 else "partial",
        "swing_rule": "strict_left2_right2",
        "structure_trend": trend,
        "pivots": pivots,
        "events": events,
        "latest_bar_time": bars[-1]["close_time"] if bars else None,
        "zone_states": zone_states,
        "zone_known_at": known_at,
        "trade_permission": False,
    }


def cme_weight(options, *, as_of):
    data = options.get("data", {})
    source = data.get("data_source", {})
    day = source.get("report_date")
    result = {
        "report_date": day,
        "weight_multiplier": 0.0,
        "role": "unavailable",
        "rule": "0-1 sessions=1;2=0.5;>=3=0.2/background;PRELIM usable without FINAL;unknown version x0.5",
        "calendar_days": None,
        "trading_days": None,
        "is_probability": False,
    }
    now = _time(as_of)
    try:
        observed = date.fromisoformat(str(day))
    except ValueError:
        return result
    if now is None:
        return result
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    age = (today - observed).days
    if age < 0 or age > 366:
        return result
    sessions = 0
    for n in range(1, age + 1):
        current = observed + timedelta(days=n)
        quality = build_session_quality({"trade_date": current.isoformat()})
        if not quality.get("calendar_known"):
            return result
        if current.weekday() < 5 and quality["session_class"] != "HOLIDAY":
            sessions += 1
    version = str(
        source.get("report_status") or source.get("version") or source.get("status") or data.get("report_status") or ""
    ).upper()
    multiplier = 1.0 if sessions <= 1 else 0.5 if sessions == 2 else 0.2
    if version not in {"FINAL", "PRELIM", "PRELIMINARY"}:
        multiplier *= 0.5
    refs = data.get("source_refs") or source.get("source_refs") or []
    valid = options.get("status") == "available" and bool(refs)
    result.update(
        calendar_days=age,
        trading_days=sessions,
        source_version=version or "unknown",
        weight_multiplier=multiplier if valid else 0.0,
        role=("confirmation_context" if sessions <= 2 else "background_only") if valid else "unavailable",
        source_refs=deepcopy(refs),
    )
    return result


def build_price_action(snapshot, *, previous_zones=None, previous_time=None):
    raw = snapshot.get("daily_research", {}).get("execution_timeframes", {}).get("timeframes", {})
    checked = build_execution_timeframe_features(
        {k: v for k, v in raw.items() if k in {"4h", "1h", "15m"}}, analysis_date=snapshot["trade_date"]
    )
    frames = {}
    cutoff = _time(snapshot.get("snapshot_time"))
    from apps.features.research.market_session import resolve_market_session
    session = resolve_market_session(snapshot.get("snapshot_time"))
    for key in ("4h", "1h", "15m"):
        if not session["new_intraday_confirmation_allowed"]:
            frames[key] = {"status": "unavailable", "reason": "market_session_"+session["state"], "events": []}
            continue
        item = checked.get(key, {})
        bars = item.get("bars", [])
        latest = _time(item.get("latest_closed_time"))
        timely = (
            cutoff
            and latest
            and _time(item.get("retrieved_at"))
            and _time(item["retrieved_at"]) <= cutoff
            and 0 <= (cutoff - latest).total_seconds() <= {"4h": 14700, "1h": 3900, "15m": 1200}[key]
        )
        if (
            item.get("status") != "available"
            or not timely
            or not item.get("raw_path")
            or item.get("continuity_status") == "gapped"
        ):
            frames[key] = {"status": "unavailable", "reason": "missing_stale_or_gapped_bars"}
            continue
        frames[key] = {
            **analyze_bars(bars, zones=previous_zones or [], known_at=previous_time),
            "raw_path": item["raw_path"],
            "source_refs": item.get("source_refs", []),
            "ticker": item.get("ticker"),
            "continuity_status": item.get("continuity_status"),
            "continuity_source_refs": item.get("continuity_source_refs", []),
        }
    return {
        "schema_version": "price_action.v1",
        "timeframes": frames,
        "cme_context": cme_weight(snapshot.get("options", {}), as_of=snapshot["snapshot_time"]),
        "execution_timeframe": "15m",
        "five_minute_enabled": False,
        "limitations": [
            "PA描述结构，不直接授予交易权限",
            "CME为期货坐标Proxy，不能直接当现货位或已知dealer方向",
            "首次运行没有前序已知zone时，不回填历史break/retest",
            "未实现FVG/OB/VP、成交量确认与仓位管理",
        ],
    }


def gate_execution_frames(execution, price_action):
    """Legacy range proxies cannot bypass the canonical PA quality gate."""
    from copy import deepcopy

    result = deepcopy(execution)
    checks = price_action.get('timeframes', {})
    frames = []
    for frame in result.get('timeframe_features', []):
        quality = checks.get(str(frame.get('timeframe', '')).lower())
        if quality and quality.get('status') == 'unavailable':
            frames.append({'timeframe': frame.get('timeframe'), 'status': 'unavailable',
                           'reason': quality.get('reason'), 'events': [], 'trend': None, 'close_time': None,
                           'context_scope': 'legacy_proxy_excluded_by_PA_quality_gate'})
        else:
            frames.append(frame)
    result['timeframe_features'] = frames
    if frames and all(f.get('status') == 'unavailable' for f in frames):
        result.update(status='unavailable', trigger=None, trigger_permission='observation_only')
    return result
