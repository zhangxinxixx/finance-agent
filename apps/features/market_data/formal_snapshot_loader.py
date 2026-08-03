"""Read-only point-in-time loader for formal market snapshot builders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.features.market_data.formal_snapshots import (
    MarketContextSnapshot,
    MarketPriceSnapshot,
    OilSnapshot,
    build_market_context_snapshot,
    build_market_price_snapshot,
    build_oil_snapshot,
)
from database.queries.market import list_completed_market_candles


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DAILY_DURATION = timedelta(days=1)
_SPOT_DURATION = timedelta(minutes=5)


@dataclass(frozen=True)
class FormalSnapshotBundle:
    market_prices: MarketPriceSnapshot
    oil: OilSnapshot
    as_of: datetime
    market_context: MarketContextSnapshot | None = None


def resolve_formal_snapshot_as_of(*, trade_date: str, run_time: datetime) -> datetime:
    """Resolve the point-in-time cutoff at 21:00 Asia/Shanghai.

    The current trade date cannot see data after the worker's actual run time;
    historical dates use their fixed daily-close cutoff.  Output is canonical
    UTC and is always timezone-aware.
    """

    if run_time.tzinfo is None or run_time.utcoffset() is None:
        raise ValueError("run_time must be timezone-aware")
    try:
        requested_date = date.fromisoformat(trade_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date must be ISO YYYY-MM-DD") from exc

    normalized_run_time = run_time.astimezone(UTC)
    run_local_date = normalized_run_time.astimezone(_SHANGHAI).date()
    if requested_date > run_local_date:
        raise ValueError("trade_date cannot be in the future")
    cutoff = datetime.combine(requested_date, time(21, 0), tzinfo=_SHANGHAI).astimezone(UTC)
    return min(cutoff, normalized_run_time) if requested_date == run_local_date else cutoff


def load_formal_market_snapshots(session: Any, *, as_of: datetime) -> FormalSnapshotBundle:
    """Load completed canonical bars and build immutable formal snapshots.

    This loader is read-only: it neither creates tables nor writes candles.
    Query failures are deliberately propagated to the caller.
    """

    point_in_time = _aware_utc(as_of, field="as_of")
    xauusd = list_completed_market_candles(
        session,
        asset="XAUUSD",
        timeframe="5m",
        as_of=point_in_time,
        bar_duration=_SPOT_DURATION,
    )
    gc = list_completed_market_candles(
        session,
        asset="GC",
        timeframe="1d",
        as_of=point_in_time,
        bar_duration=_DAILY_DURATION,
    )
    wti = list_completed_market_candles(
        session,
        asset="WTI",
        timeframe="1d",
        as_of=point_in_time,
        bar_duration=_DAILY_DURATION,
    )
    brent = list_completed_market_candles(
        session,
        asset="BRENT",
        timeframe="1d",
        as_of=point_in_time,
        bar_duration=_DAILY_DURATION,
    )
    xagusd = list_completed_market_candles(
        session, asset="XAGUSD", timeframe="1d", as_of=point_in_time, bar_duration=_DAILY_DURATION
    )
    dxy = list_completed_market_candles(
        session, asset="DXY", timeframe="1d", as_of=point_in_time, bar_duration=_DAILY_DURATION
    )
    vix = list_completed_market_candles(
        session, asset="VIX", timeframe="1d", as_of=point_in_time, bar_duration=_DAILY_DURATION
    )
    market_candidates = [
        *(_candle_mapping(row, duration=_SPOT_DURATION) for row in xauusd),
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in gc),
    ]
    oil_candidates = [
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in wti),
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in brent),
    ]
    market_context_candidates = [
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in xagusd),
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in dxy),
        *(_candle_mapping(row, duration=_DAILY_DURATION) for row in vix),
    ]
    return FormalSnapshotBundle(
        market_prices=build_market_price_snapshot(candidates=market_candidates, as_of=point_in_time),
        oil=build_oil_snapshot(candidates=oil_candidates, as_of=point_in_time),
        as_of=point_in_time,
        market_context=build_market_context_snapshot(candidates=market_context_candidates, as_of=point_in_time),
    )


def _candle_mapping(row: Any, *, duration: timedelta) -> dict[str, Any]:
    source_ref = _mapping_value(row, "source_ref")
    open_time = _aware_utc(_value(row, "open_time"), field="open_time")
    return {
        "asset": str(_value(row, "asset") or ""),
        "timeframe": str(_value(row, "timeframe") or ""),
        "open_time": open_time,
        "close_time": open_time + duration,
        "open": _value(row, "open"),
        "high": _value(row, "high"),
        "low": _value(row, "low"),
        "close": _value(row, "close"),
        "source": str(_value(row, "source") or ""),
        "source_ref": source_ref,
        "raw_path": _value(row, "raw_path"),
        "created_at": _optional_aware_utc(_value(row, "created_at")),
        "updated_at": _optional_aware_utc(_value(row, "updated_at")),
    }


def _mapping_value(row: Any, field: str) -> dict[str, Any]:
    value = _value(row, field)
    return dict(value) if isinstance(value, Mapping) else {}


def _value(row: Any, field: str) -> Any:
    return row.get(field) if isinstance(row, Mapping) else getattr(row, field, None)


def _optional_aware_utc(value: object) -> datetime | None:
    return _aware_utc(value, field="ORM datetime") if isinstance(value, datetime) else None


def _aware_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    # SQLite returns naive values for timezone columns; this boundary treats
    # persisted naive ORM datetimes as canonical UTC before pure validation.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
