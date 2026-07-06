from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models.analysis import ensure_analysis_tables
from database.models.engine import DATABASE_URL
from database.queries.market import list_market_candles


EXPECTED_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1D": 86400,
}

_VALID_TIMEFRAMES = set(EXPECTED_INTERVAL_SECONDS)
_AGGREGATABLE_TIMEFRAMES = {"5m", "15m", "30m", "1h", "4h"}
_SUPPORTED_ASSETS = {"XAUUSD", "DXY"}
_TIMEFRAME_ALIASES = {
    "1M": "1m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1D",
    "1DAY": "1D",
    "D": "1D",
}


@dataclass(frozen=True)
class SourcePlan:
    source_timeframe: str
    provider: str
    rows: list[Any]
    aggregated: bool = False
    degraded_reason: str | None = None


def get_market_candles(asset: str = "XAUUSD", timeframe: str = "1m", limit: int = 500) -> dict[str, Any]:
    normalized_asset = str(asset or "XAUUSD").upper()
    normalized_timeframe = normalize_timeframe(timeframe)
    requested_limit = _clamp_limit(limit)

    if normalized_asset not in _SUPPORTED_ASSETS:
        return _empty_response(
            asset=normalized_asset,
            timeframe=normalized_timeframe,
            requested_limit=requested_limit,
            source_timeframe=normalized_timeframe,
            provider="unsupported",
            reason=f"unsupported asset: {normalized_asset}",
            primary_source="market_candles",
        )

    if normalized_asset == "DXY" and normalized_timeframe != "1D":
        return _empty_response(
            asset=normalized_asset,
            timeframe=normalized_timeframe,
            requested_limit=requested_limit,
            source_timeframe="1D",
            provider="unavailable",
            reason="DXY intraday candles are not available; do not fabricate minute-level DXY data.",
            primary_source="market_candles:DXY:1d",
        )

    session_factory = _market_session_factory()
    with session_factory() as session:
        ensure_analysis_tables(session)
        plan = choose_best_source(
            session,
            asset=normalized_asset,
            timeframe=normalized_timeframe,
            limit=requested_limit,
        )

    candles = aggregate_candles(plan.rows, normalized_timeframe)[-requested_limit:] if plan.aggregated else [
        _row_to_candle(row) for row in plan.rows[-requested_limit:]
    ]
    coverage = detect_candle_gaps(candles, normalized_timeframe, requested_limit=requested_limit)
    if plan.degraded_reason:
        coverage["degraded"] = True
        coverage["reason"] = plan.degraded_reason

    latest_row = plan.rows[-1] if plan.rows else None
    return {
        "asset": normalized_asset,
        "timeframe": normalized_timeframe,
        "requested_limit": requested_limit,
        "source_timeframe": plan.source_timeframe,
        "provider": plan.provider,
        "candles": candles,
        "coverage": coverage,
        "source_trace": {
            "primary_source": f"market_candles:{normalized_asset}:{plan.source_timeframe}",
            "fallback_source": "market_candles:XAUUSD:1m" if plan.aggregated else None,
            "latest_raw_path": _row_attr(latest_row, "raw_path") if latest_row is not None else None,
            "latest_update_time": _iso_datetime(_row_attr(latest_row, "updated_at")) if latest_row is not None else None,
        },
    }


def normalize_timeframe(timeframe: str) -> str:
    raw = str(timeframe or "1m").strip()
    normalized = _TIMEFRAME_ALIASES.get(raw.upper(), raw)
    return normalized if normalized in _VALID_TIMEFRAMES else "1m"


def choose_best_source(session: Any, *, asset: str, timeframe: str, limit: int) -> SourcePlan:
    db_timeframe = _db_timeframe(timeframe)
    native_rows = list_market_candles(session, asset=asset, timeframe=db_timeframe, limit=limit)
    if native_rows:
        return SourcePlan(
            source_timeframe=timeframe,
            provider=_provider_from_rows(native_rows),
            rows=native_rows,
        )

    if asset == "XAUUSD" and timeframe in _AGGREGATABLE_TIMEFRAMES:
        fetch_limit = _aggregation_fetch_limit(timeframe, limit)
        minute_rows = list_market_candles(session, asset=asset, timeframe="1m", limit=fetch_limit)
        if minute_rows:
            return SourcePlan(
                source_timeframe="1m",
                provider=_provider_from_rows(minute_rows),
                rows=minute_rows,
                aggregated=True,
            )

    if asset == "XAUUSD" and timeframe == "4h":
        hourly_rows = list_market_candles(session, asset=asset, timeframe="1h", limit=max(limit * 4, limit))
        if hourly_rows:
            return SourcePlan(
                source_timeframe="1h",
                provider=_provider_from_rows(hourly_rows),
                rows=hourly_rows,
                aggregated=True,
                degraded_reason="4h requested but XAUUSD 1m candles are unavailable; aggregated from 1h rows.",
            )

    return SourcePlan(
        source_timeframe=timeframe,
        provider="unavailable",
        rows=[],
        degraded_reason=f"No market_candles rows available for {asset} {timeframe}.",
    )


def aggregate_candles(rows: list[Any], timeframe: str) -> list[dict[str, Any]]:
    interval = EXPECTED_INTERVAL_SECONDS.get(timeframe)
    if not rows or not interval:
        return []

    buckets: dict[datetime, list[Any]] = {}
    for row in sorted(rows, key=lambda item: _row_open_time(item)):
        open_time = _row_open_time(row)
        bucket_time = _bucket_time(open_time, interval)
        buckets.setdefault(bucket_time, []).append(row)

    candles: list[dict[str, Any]] = []
    for bucket_time in sorted(buckets):
        bucket_rows = sorted(buckets[bucket_time], key=lambda item: _row_open_time(item))
        first = bucket_rows[0]
        last = bucket_rows[-1]
        volumes = [_row_attr(item, "volume") for item in bucket_rows if _row_attr(item, "volume") is not None]
        candles.append(
            {
                "time": _iso_datetime(bucket_time),
                "open": float(_row_attr(first, "open")),
                "high": max(float(_row_attr(item, "high")) for item in bucket_rows),
                "low": min(float(_row_attr(item, "low")) for item in bucket_rows),
                "close": float(_row_attr(last, "close")),
                "volume": sum(float(volume) for volume in volumes) if volumes else None,
                "source": str(_row_attr(last, "source") or ""),
                "partial": False,
            }
        )
    return candles


def detect_candle_gaps(
    candles: list[dict[str, Any]],
    timeframe: str,
    *,
    requested_limit: int,
) -> dict[str, Any]:
    interval = EXPECTED_INTERVAL_SECONDS.get(timeframe, 60)
    gap_threshold = interval * (3.5 if timeframe == "1D" else 1.5)
    gap_ranges: list[dict[str, Any]] = []
    max_gap_seconds: int | None = None

    for current, nxt in zip(candles, candles[1:]):
        current_time = _parse_time(current.get("time"))
        next_time = _parse_time(nxt.get("time"))
        if current_time is None or next_time is None:
            continue
        gap_seconds = int((next_time - current_time).total_seconds())
        if gap_seconds > gap_threshold:
            gap_ranges.append(
                {
                    "from": current_time.isoformat(),
                    "to": next_time.isoformat(),
                    "gap_seconds": gap_seconds,
                }
            )
            max_gap_seconds = max(max_gap_seconds or gap_seconds, gap_seconds)

    returned = len(candles)
    low_coverage = requested_limit > 0 and returned < requested_limit * 0.8
    degraded = bool(gap_ranges) or low_coverage
    reason = None
    if gap_ranges:
        reason = "candle gaps detected"
    elif low_coverage:
        reason = "insufficient candle coverage"

    return {
        "returned": returned,
        "first_time": candles[0].get("time") if candles else None,
        "last_time": candles[-1].get("time") if candles else None,
        "expected_interval_seconds": interval,
        "gap_count": len(gap_ranges),
        "max_gap_seconds": max_gap_seconds,
        "gap_ranges": gap_ranges[:10],
        "degraded": degraded,
        "reason": reason,
    }


def _row_to_candle(row: Any) -> dict[str, Any]:
    return {
        "time": _iso_datetime(_row_attr(row, "open_time")),
        "open": float(_row_attr(row, "open")),
        "high": float(_row_attr(row, "high")),
        "low": float(_row_attr(row, "low")),
        "close": float(_row_attr(row, "close")),
        "volume": _row_attr(row, "volume"),
        "source": str(_row_attr(row, "source") or ""),
        "partial": False,
    }


def _empty_response(
    *,
    asset: str,
    timeframe: str,
    requested_limit: int,
    source_timeframe: str,
    provider: str,
    reason: str,
    primary_source: str,
) -> dict[str, Any]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "requested_limit": requested_limit,
        "source_timeframe": source_timeframe,
        "provider": provider,
        "candles": [],
        "coverage": {
            "returned": 0,
            "first_time": None,
            "last_time": None,
            "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS.get(timeframe, 60),
            "gap_count": 0,
            "max_gap_seconds": None,
            "gap_ranges": [],
            "degraded": True,
            "reason": reason,
        },
        "source_trace": {
            "primary_source": primary_source,
            "fallback_source": None,
            "latest_raw_path": None,
            "latest_update_time": None,
        },
    }


def _aggregation_fetch_limit(timeframe: str, target_limit: int) -> int:
    multipliers = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
    return (target_limit + 2) * multipliers.get(timeframe, 1)


def _bucket_time(open_time: datetime, interval_seconds: int) -> datetime:
    aware = open_time if open_time.tzinfo else open_time.replace(tzinfo=timezone.utc)
    bucket_ts = int(aware.timestamp() // interval_seconds) * interval_seconds
    return datetime.fromtimestamp(bucket_ts, tz=timezone.utc)


def _provider_from_rows(rows: list[Any]) -> str:
    source = str(_row_attr(rows[-1], "source") or "") if rows else ""
    if "jin10" in source:
        return "jin10_mcp"
    if "yahoo" in source or "openbb" in source:
        return "openbb_yfinance" if "openbb" in source else "yahoo_finance"
    return source or "market_candles"


def _db_timeframe(timeframe: str) -> str:
    return "1d" if timeframe == "1D" else timeframe


def _row_open_time(row: Any) -> datetime:
    value = _row_attr(row, "open_time")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = _parse_time(value)
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_datetime(value: Any) -> str | None:
    parsed = _parse_time(value)
    return parsed.isoformat() if parsed else None


def _row_attr(row: Any, field: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _clamp_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 500
    return max(1, min(value, 2000))


def _market_session_factory():
    engine = create_engine(DATABASE_URL, echo=False)
    return sessionmaker(bind=engine)
