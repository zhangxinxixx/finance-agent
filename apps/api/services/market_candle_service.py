from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.features.market_data import (
    aggregate_complete_candles,
    merge_candle_series,
    select_canonical_xauusd_rows,
)
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
_SUPPORTED_ASSETS = {"XAUUSD", "DXY", "GC"}
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
    degraded_reason: str | None = None


def get_market_candles(
    asset: str = "XAUUSD",
    timeframe: str = "5m",
    limit: int = 500,
    *,
    session: Any | None = None,
) -> dict[str, Any]:
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

    if session is None:
        session_factory = _market_session_factory()
        with session_factory() as db_session:
            ensure_analysis_tables(db_session)
            plan = choose_best_source(
                db_session,
                asset=normalized_asset,
                timeframe=normalized_timeframe,
                limit=requested_limit,
            )
    else:
        ensure_analysis_tables(session)
        plan = choose_best_source(
            session,
            asset=normalized_asset,
            timeframe=normalized_timeframe,
            limit=requested_limit,
        )

    candles = [_row_to_candle(row) for row in plan.rows[-requested_limit:]]
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
            "fallback_source": "twelvedata_xauusd" if plan.provider == "canonical_xauusd_mixed" else None,
            "latest_raw_path": _row_attr(latest_row, "raw_path") if latest_row is not None else None,
            "latest_update_time": _iso_datetime(_row_attr(latest_row, "updated_at")) if latest_row is not None else None,
        },
    }


def normalize_timeframe(timeframe: str) -> str:
    raw = str(timeframe or "5m").strip()
    normalized = _TIMEFRAME_ALIASES.get(raw.upper(), raw)
    return normalized if normalized in _VALID_TIMEFRAMES else "5m"


def choose_best_source(session: Any, *, asset: str, timeframe: str, limit: int) -> SourcePlan:
    db_timeframe = _db_timeframe(timeframe)
    if asset != "XAUUSD":
        native_rows = list_market_candles(session, asset=asset, timeframe=db_timeframe, limit=limit)
        if native_rows:
            return SourcePlan(
                source_timeframe=timeframe,
                provider=_provider_from_rows(native_rows),
                rows=native_rows,
            )

    if asset == "XAUUSD" and timeframe == "1m":
        staging_rows = list_market_candles(
            session,
            asset=asset,
            timeframe="1m",
            limit=limit,
            source="jin10_mcp_kline_1m",
        )
        if staging_rows:
            return SourcePlan(
                source_timeframe="1m",
                provider="jin10_mcp_staging",
                rows=staging_rows,
                degraded_reason="1m is internal staging; the formal minimum XAUUSD timeframe is 5m.",
            )

    if asset == "XAUUSD" and timeframe == "5m":
        candidate_rows = list_market_candles(
            session,
            asset=asset,
            timeframe="5m",
            limit=max(limit * 3, limit + 10),
        )
        canonical_rows = select_canonical_xauusd_rows(candidate_rows)[-limit:]
        if canonical_rows:
            return SourcePlan(
                source_timeframe="5m",
                provider=_canonical_provider(canonical_rows),
                rows=canonical_rows,
            )

    if asset == "XAUUSD" and timeframe in {"15m", "30m", "1h", "4h"}:
        fetch_limit = _aggregation_fetch_limit_from_five_minutes(timeframe, limit)
        five_minute_candidates = list_market_candles(
            session,
            asset=asset,
            timeframe="5m",
            limit=fetch_limit * 3,
        )
        canonical_five_minute = select_canonical_xauusd_rows(five_minute_candidates)
        local_rows = aggregate_complete_candles(
            canonical_five_minute,
            source_timeframe="5m",
            target_timeframe=timeframe,
            source=f"canonical_xauusd_5m_aggregate_{timeframe}",
        )
        fallback_rows: list[Any] = []
        if timeframe in {"15m", "1h", "4h"}:
            fallback_rows = list_market_candles(
                session,
                asset=asset,
                timeframe=timeframe,
                limit=max(limit * 2, limit + 5),
                source=f"twelvedata_xauusd_{timeframe}",
            )
        merged = merge_candle_series(local_rows, fallback_rows)[-limit:]
        if merged:
            return SourcePlan(
                source_timeframe="5m",
                provider=_canonical_provider(merged),
                rows=merged,
            )

    if asset == "XAUUSD" and timeframe == "1D":
        native_rows = list_market_candles(session, asset=asset, timeframe="1d", limit=max(limit * 3, limit))
        compatible_rows = select_canonical_xauusd_rows(native_rows)[-limit:]
        if compatible_rows:
            return SourcePlan(
                source_timeframe="1D",
                provider=_provider_from_rows(compatible_rows),
                rows=compatible_rows,
            )

    return SourcePlan(
        source_timeframe=timeframe,
        provider="unavailable",
        rows=[],
        degraded_reason=f"No canonical market_candles rows available for {asset} {timeframe}.",
    )


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


def _aggregation_fetch_limit_from_five_minutes(timeframe: str, target_limit: int) -> int:
    multipliers = {"15m": 3, "30m": 6, "1h": 12, "4h": 48}
    return (target_limit + 2) * multipliers[timeframe]


def _provider_from_rows(rows: list[Any]) -> str:
    source = str(_row_attr(rows[-1], "source") or "") if rows else ""
    if source.startswith("canonical_xauusd_5m_aggregate_"):
        source_ref = _row_attr(rows[-1], "source_ref") or {}
        components = source_ref.get("component_source_refs", []) if isinstance(source_ref, dict) else []
        component_sources = {str(item.get("source") or "") for item in components if isinstance(item, dict)}
        if component_sources and all("jin10" in item for item in component_sources):
            return "jin10_mcp"
        if component_sources and all("twelvedata" in item for item in component_sources):
            return "twelve_data"
        return "canonical_xauusd_mixed"
    if "jin10" in source:
        return "jin10_mcp"
    if "twelvedata" in source:
        return "twelve_data"
    if "yahoo" in source or "openbb" in source:
        return "openbb_yfinance" if "openbb" in source else "yahoo_finance"
    return source or "market_candles"


def _canonical_provider(rows: list[Any]) -> str:
    providers = {_provider_from_rows([row]) for row in rows}
    if providers == {"jin10_mcp"}:
        return "jin10_mcp"
    if providers == {"twelve_data"}:
        return "twelve_data"
    if len(providers) > 1:
        return "canonical_xauusd_mixed"
    return next(iter(providers), "canonical_xauusd")


def _db_timeframe(timeframe: str) -> str:
    return "1d" if timeframe == "1D" else timeframe


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
