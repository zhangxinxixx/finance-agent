"""Canonical XAUUSD candle selection and strict deterministic aggregation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from database.market_identity import is_xauusd_spot_identity


TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}

XAUUSD_SOURCE_PRIORITY = {
    "jin10_mcp_derived_5m": 0,
    "twelvedata_xauusd_5m": 1,
    "canonical_xauusd_5m_aggregate_15m": 0,
    "canonical_xauusd_5m_aggregate_30m": 0,
    "canonical_xauusd_5m_aggregate_1h": 0,
    "canonical_xauusd_5m_aggregate_4h": 0,
    "twelvedata_xauusd_15m": 1,
    "twelvedata_xauusd_1h": 1,
    "twelvedata_xauusd_4h": 1,
    "jin10_mcp_kline_1m": 0,
}

_REJECTED_QUALITY = {"invalid", "rejected", "quarantined"}
_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class AggregatedCandle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str
    source_ref: dict[str, Any]
    raw_path: str | None = None


def select_canonical_xauusd_rows(rows: Iterable[Any]) -> list[Any]:
    """Choose one whole compatible provider bar for each timestamp."""
    selected: dict[datetime, Any] = {}
    selected_rank: dict[datetime, tuple[int, str]] = {}
    for row in rows:
        if not is_xauusd_compatible_row(row):
            continue
        open_time = _open_time(row)
        if open_time is None:
            continue
        source = str(_value(row, "source") or "")
        source_ref = _source_ref(row)
        quality = str(source_ref.get("quality_status") or "accepted")
        if quality in _REJECTED_QUALITY:
            continue
        rank = (XAUUSD_SOURCE_PRIORITY.get(source, 100), source)
        if open_time not in selected or rank < selected_rank[open_time]:
            selected[open_time] = row
            selected_rank[open_time] = rank
    return [selected[key] for key in sorted(selected)]


def is_xauusd_compatible_row(row: Any) -> bool:
    """Reject known futures-continuous rows from the XAUUSD spot proxy chain."""
    return is_xauusd_spot_identity(
        asset=str(_value(row, "asset") or "XAUUSD"),
        source=str(_value(row, "source") or ""),
        source_ref=_source_ref(row),
    )


def aggregate_complete_candles(
    rows: Iterable[Any],
    *,
    source_timeframe: str,
    target_timeframe: str,
    source: str,
    closed_before: datetime | None = None,
) -> list[AggregatedCandle]:
    """Aggregate only buckets containing every expected unique component bar."""
    source_seconds = TIMEFRAME_SECONDS[source_timeframe]
    target_seconds = TIMEFRAME_SECONDS[target_timeframe]
    if target_seconds % source_seconds:
        raise ValueError(f"{target_timeframe} is not divisible by {source_timeframe}")
    expected_count = target_seconds // source_seconds
    normalized_closed_before = _as_utc(closed_before) if closed_before is not None else None

    buckets: dict[datetime, dict[datetime, Any]] = {}
    for row in rows:
        open_time = _open_time(row)
        if open_time is None:
            continue
        bucket_time = _bucket_time(open_time, target_timeframe)
        buckets.setdefault(bucket_time, {})[open_time] = row

    result: list[AggregatedCandle] = []
    for bucket_time in sorted(buckets):
        bucket_end = bucket_time + timedelta(seconds=target_seconds)
        if normalized_closed_before is not None and bucket_end > normalized_closed_before:
            continue
        component_map = buckets[bucket_time]
        expected_times = [bucket_time + timedelta(seconds=source_seconds * index) for index in range(expected_count)]
        if any(expected_time not in component_map for expected_time in expected_times):
            continue
        components = [component_map[expected_time] for expected_time in expected_times]
        component_refs = [
            {
                "open_time": expected_time.isoformat(),
                "source": str(_value(component, "source") or ""),
                "raw_path": _value(component, "raw_path"),
            }
            for expected_time, component in zip(expected_times, components, strict=True)
        ]
        result.append(
            AggregatedCandle(
                open_time=bucket_time,
                open=float(_value(components[0], "open")),
                high=max(float(_value(component, "high")) for component in components),
                low=min(float(_value(component, "low")) for component in components),
                close=float(_value(components[-1], "close")),
                volume=None,
                source=source,
                source_ref={
                    "provider": "canonical_xauusd",
                    "provider_symbol": "XAUUSD",
                    "instrument_type": "otc_spot_quote_proxy",
                    "source_key": "canonical_xauusd_5m",
                    "source_role": "market_primary",
                    "quality_status": "accepted",
                    "provider_timeframe": source_timeframe,
                    "target_timeframe": target_timeframe,
                    "volume_semantics": "unavailable_or_quote_activity",
                    "component_count": expected_count,
                    "component_source_refs": component_refs,
                },
                raw_path=_value(components[-1], "raw_path"),
            )
        )
    return result


def aggregate_provider_complete_candles(
    rows: Iterable[Any],
    *,
    source_timeframe: str,
    target_timeframe: str,
    source: str,
    closed_before: datetime | None = None,
) -> list[AggregatedCandle]:
    """Choose one complete provider bucket; never mix provider bars in OHLC."""

    provider_rows: dict[str, list[Any]] = {}
    for row in rows:
        if not is_xauusd_compatible_row(row):
            continue
        provider = str(_value(row, "source") or "")
        quality = str(_source_ref(row).get("quality_status") or "accepted")
        if not provider or quality in _REJECTED_QUALITY:
            continue
        provider_rows.setdefault(provider, []).append(row)

    selected: dict[datetime, tuple[tuple[int, str], AggregatedCandle]] = {}
    for provider, candidates in provider_rows.items():
        rank = (XAUUSD_SOURCE_PRIORITY.get(provider, 100), provider)
        aggregates = aggregate_complete_candles(
            candidates,
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
            source=source,
            closed_before=closed_before,
        )
        for candle in aggregates:
            current = selected.get(candle.open_time)
            if current is not None and current[0] <= rank:
                continue
            source_ref = dict(candle.source_ref)
            source_ref["selected_provider"] = provider
            source_ref["provider"] = provider
            selected[candle.open_time] = (rank, replace(candle, source_ref=source_ref))
    return [selected[key][1] for key in sorted(selected)]


def merge_candle_series(primary: Iterable[Any], fallback: Iterable[Any]) -> list[Any]:
    """Fill missing timestamps with whole fallback bars without field mixing."""
    merged: dict[datetime, Any] = {}
    for row in fallback:
        if (open_time := _open_time(row)) is not None:
            merged[open_time] = row
    for row in primary:
        if (open_time := _open_time(row)) is not None:
            merged[open_time] = row
    return [merged[key] for key in sorted(merged)]


def _bucket_time(open_time: datetime, timeframe: str) -> datetime:
    aware = _as_utc(open_time)
    if timeframe == "4h":
        return _session_bucket_time(aware, interval_hours=4)
    seconds = TIMEFRAME_SECONDS[timeframe]
    bucket_ts = int(aware.timestamp() // seconds) * seconds
    return datetime.fromtimestamp(bucket_ts, tz=UTC)


def _session_bucket_time(open_time: datetime, *, interval_hours: int) -> datetime:
    local = open_time.astimezone(_NEW_YORK)
    anchor_date = local.date() if local.time() >= time(17, 0) else local.date() - timedelta(days=1)
    anchor = datetime.combine(anchor_date, time(17, 0), tzinfo=_NEW_YORK)
    elapsed_seconds = max(0, int((local - anchor).total_seconds()))
    bucket_index = elapsed_seconds // (interval_hours * 3600)
    bucket_local = anchor + timedelta(hours=bucket_index * interval_hours)
    return bucket_local.astimezone(UTC)


def _source_ref(row: Any) -> dict[str, Any]:
    value = _value(row, "source_ref")
    return value if isinstance(value, dict) else {}


def _open_time(row: Any) -> datetime | None:
    value = _value(row, "open_time")
    if isinstance(value, datetime):
        return _as_utc(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _value(row: Any, field: str) -> Any:
    return row.get(field) if isinstance(row, dict) else getattr(row, field, None)
