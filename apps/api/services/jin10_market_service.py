"""Read-side cache and candle helpers for Jin10 market routes."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JIN10_FLASH_CACHE_PATH = Path("./storage/outputs/jin10/flash_cache.json")
JIN10_FLASH_CACHE_MAX_AGE_SECONDS = 60
JIN10_CALENDAR_CACHE_PATH = Path("./storage/outputs/jin10/calendar_cache.json")
JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS = 18 * 60 * 60
JIN10_CALENDAR_PAST_WINDOW_DAYS = 7
JIN10_CALENDAR_FUTURE_WINDOW_DAYS = 14


def jin10_unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "quotes": {},
        "counts": {},
        "kline_codes": [],
    }


def is_file_stale(path: Path, *, max_age_seconds: int) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return True
    return age_seconds > max_age_seconds


def refresh_jin10_calendar_cache() -> None:
    try:
        from apps.scheduler.jin10_refresh import refresh_jin10_calendar_cache as refresh

        refresh()
    except Exception:
        pass


def _parse_calendar_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip().replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)

    candidates = [normalized]
    if len(normalized) == 16:
        candidates.append(f"{normalized}:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _calendar_window(now: datetime | None = None) -> tuple[str, str]:
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return (
        (anchor - timedelta(days=JIN10_CALENDAR_PAST_WINDOW_DAYS)).isoformat(),
        (anchor + timedelta(days=JIN10_CALENDAR_FUTURE_WINDOW_DAYS)).isoformat(),
    )


def build_jin10_calendar_payload(data: dict[str, Any], cache_path: Path) -> dict[str, Any]:
    raw_events = data.get("events")
    events = [_normalize_calendar_event(item) for item in raw_events if isinstance(item, dict)] if isinstance(raw_events, list) else []
    window_start_date, window_end_date = _calendar_window()
    events = [
        event
        for event in events
        if _is_calendar_event_in_window(event, window_start=window_start_date, window_end=window_end_date)
    ]
    events.sort(key=_calendar_event_sort_key)

    upcoming_count = sum(1 for event in events if event.get("release_state") == "upcoming")
    released_count = len(events) - upcoming_count
    high_impact_count = sum(1 for event in events if event.get("is_high_impact"))
    event_dates = [event.get("event_date") for event in events if isinstance(event.get("event_date"), str)]
    earliest_event_date = min(event_dates) if event_dates else None
    latest_event_date = max(event_dates) if event_dates else None
    cache_age_seconds = _calendar_cache_age_seconds(cache_path)

    stale_by_age = is_file_stale(cache_path, max_age_seconds=JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS)
    today_key = datetime.now(timezone.utc).date().isoformat()
    stale_by_window = upcoming_count == 0 and latest_event_date is not None and latest_event_date < today_key
    is_stale = stale_by_age or stale_by_window

    freshness_reason = "no_upcoming_events" if stale_by_window else "cache_too_old" if stale_by_age else "fresh"
    for event in events:
        event.pop("_sort_ts", None)

    return {
        "status": "stale" if is_stale else "ok",
        "generated_at": data.get("generated_at"),
        "events": events,
        "stats": {
            "total": len(events),
            "upcoming": upcoming_count,
            "released": released_count,
            "high_impact": high_impact_count,
            "earliest_event_date": earliest_event_date,
            "latest_event_date": latest_event_date,
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
        },
        "freshness": {"is_stale": is_stale, "reason": freshness_reason, "cache_age_seconds": cache_age_seconds},
    }


def candle_to_dict(row: Any) -> dict[str, Any]:
    return {
        "time": row.open_time.isoformat() if row.open_time else "",
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume if row.volume else 0,
    }


def aggregation_fetch_limit(timeframe: str, target_limit: int) -> int:
    multipliers = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
    return (target_limit + 4) * multipliers.get(timeframe, 1)


def aggregate_candles(rows: list[Any], timeframe: str) -> list[dict[str, Any]]:
    if not rows:
        return []

    minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440}
    delta = timedelta(minutes=minutes.get(timeframe, 1))
    sorted_rows = sorted(rows, key=lambda row: row.open_time if row.open_time else datetime.min.replace(tzinfo=timezone.utc))
    buckets: dict[datetime, list[Any]] = {}
    for row in sorted_rows:
        if not row.open_time:
            continue
        bucket_seconds = int(delta.total_seconds())
        bucket_key = datetime.fromtimestamp(int(row.open_time.timestamp() // bucket_seconds) * bucket_seconds, tz=timezone.utc)
        buckets.setdefault(bucket_key, []).append(row)

    result = []
    for bucket_key in sorted(buckets):
        group = buckets[bucket_key]
        opens = [row.open for row in group if row.open is not None]
        highs = [row.high for row in group if row.high is not None]
        lows = [row.low for row in group if row.low is not None]
        closes = [row.close for row in group if row.close is not None]
        volumes = [row.volume for row in group if row.volume is not None]
        if not opens:
            continue
        result.append({
            "time": bucket_key.isoformat(),
            "open": opens[0],
            "high": max(highs) if highs else opens[0],
            "low": min(lows) if lows else opens[0],
            "close": closes[-1],
            "volume": sum(volumes) if volumes else 0,
        })
    return result


def _normalize_calendar_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(event)
    parsed_time = _parse_calendar_time(event.get("pub_time"))
    if parsed_time is not None:
        normalized["pub_time"] = parsed_time.isoformat(timespec="minutes")
        normalized["event_date"] = parsed_time.date().isoformat()
        normalized["_sort_ts"] = parsed_time.timestamp()
    else:
        normalized["event_date"] = None
        normalized["_sort_ts"] = 0.0
    normalized["release_state"] = calendar_release_state(event)
    normalized["is_high_impact"] = int(event.get("star") or 0) >= 4
    return normalized


def calendar_release_state(event: dict[str, Any]) -> str:
    return "upcoming" if event.get("actual") in (None, "") else "released"


def _is_calendar_event_in_window(event: dict[str, Any], *, window_start: str, window_end: str) -> bool:
    event_date = event.get("event_date")
    return isinstance(event_date, str) and window_start <= event_date <= window_end


def _calendar_event_sort_key(event: dict[str, Any]) -> tuple[int, float, int]:
    sort_ts = float(event.get("_sort_ts") or 0.0)
    star = int(event.get("star") or 0)
    return (0, sort_ts, -star) if event.get("release_state") == "upcoming" else (1, -sort_ts, -star)


def _calendar_cache_age_seconds(path: Path) -> int | None:
    try:
        return max(0, int(time.time() - path.stat().st_mtime))
    except OSError:
        return None
