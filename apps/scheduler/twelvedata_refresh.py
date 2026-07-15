"""Scheduled Twelve Data validation and whole-bar fallback collection."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from threading import Lock
from typing import Any

from sqlalchemy import text

from apps.collectors.twelvedata import TwelveDataClient, TwelveDataQuotaError
from apps.features.market_data import aggregate_complete_candles, select_canonical_xauusd_rows
from database.models.analysis import ensure_analysis_tables
from database.models.engine import SessionLocal
from database.queries.data_source_status import get_data_source_status, upsert_data_source_status
from database.queries.market import list_market_candles, upsert_market_candle

logger = logging.getLogger(__name__)

TWELVE_DATA_SOURCE_KEY = "twelvedata_xauusd"
TWELVE_DATA_INTERVALS = {
    "5min": ("5m", 300),
    "15min": ("15m", 900),
    "1h": ("1h", 3600),
    "4h": ("4h", 14400),
}
TWELVE_DATA_DISPATCH_ORDER = ("5min", "15min", "1h", "4h")
PROVIDER_GRACE_SECONDS = 75
_TWELVE_DATA_DISPATCH_ADVISORY_LOCK_ID = 7_412_012_026
_TWELVE_DATA_DISPATCH_PROCESS_LOCK = Lock()


def refresh_due_twelvedata_xauusd(
    *,
    now: datetime | None = None,
    storage_root: Path | str = "storage",
    outputsize: int = 10,
) -> dict[str, Any]:
    """Sequentially refresh all provider intervals due in the current round."""
    collected_at = _as_utc(now or datetime.now(UTC))
    due_intervals = _due_intervals(collected_at)
    with _twelvedata_dispatch_lock() as lock_acquired:
        if not lock_acquired:
            return {
                "status": "dispatch_busy",
                "run_id": f"twelvedata-dispatch-{collected_at.strftime('%Y%m%dT%H%M%SZ')}",
                "due_intervals": due_intervals,
                "executed_intervals": [],
                "results": [],
                "stopped_reason": "dispatcher_lock_unavailable",
            }
        results: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        for interval in due_intervals:
            summary = refresh_twelvedata_xauusd(
                interval,
                now=collected_at,
                storage_root=storage_root,
                outputsize=outputsize,
            )
            results.append(summary)
            if summary.get("status") == "minute_quota_exhausted" or summary.get("credits_left") == 0:
                stopped_reason = "minute_quota_exhausted"
                break
    return {
        "status": "partial" if stopped_reason else "ok",
        "run_id": f"twelvedata-dispatch-{collected_at.strftime('%Y%m%dT%H%M%SZ')}",
        "due_intervals": due_intervals,
        "executed_intervals": [str(item.get("interval")) for item in results],
        "results": results,
        "stopped_reason": stopped_reason,
    }


@contextmanager
def _twelvedata_dispatch_lock():
    if not _TWELVE_DATA_DISPATCH_PROCESS_LOCK.acquire(blocking=False):
        yield False
        return
    advisory_session = None
    advisory_acquired = False
    try:
        advisory_session = SessionLocal()
        if advisory_session.get_bind().dialect.name == "postgresql":
            advisory_acquired = bool(
                advisory_session.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _TWELVE_DATA_DISPATCH_ADVISORY_LOCK_ID},
                ).scalar()
            )
            if not advisory_acquired:
                yield False
                return
        yield True
    finally:
        if advisory_session is not None:
            if advisory_acquired:
                advisory_session.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": _TWELVE_DATA_DISPATCH_ADVISORY_LOCK_ID},
                )
            advisory_session.close()
        _TWELVE_DATA_DISPATCH_PROCESS_LOCK.release()


def refresh_twelvedata_xauusd(
    interval: str,
    *,
    now: datetime | None = None,
    storage_root: Path | str = "storage",
    outputsize: int = 10,
) -> dict[str, Any]:
    """Fetch one native interval and persist only closed XAU/USD bars."""
    if interval not in TWELVE_DATA_INTERVALS:
        raise ValueError(f"unsupported Twelve Data interval: {interval}")

    collected_at = _as_utc(now or datetime.now(UTC))
    timeframe, interval_seconds = TWELVE_DATA_INTERVALS[interval]
    root = Path(storage_root)
    run_id = f"twelvedata-{timeframe}-{collected_at.strftime('%Y%m%dT%H%M%SZ')}"

    with SessionLocal() as session:
        ensure_analysis_tables(session)
        if _minute_quota_exhausted(session, collected_at):
            summary = {
                "status": "minute_quota_exhausted",
                "interval": interval,
                "timeframe": timeframe,
                "run_id": run_id,
                "persisted": 0,
                "request_count": 0,
                "fallback_count": 0,
                "fallback_open_times": [],
                "comparison": _comparison_summary([]),
                "credits_used": None,
                "credits_left": 0,
                "credit_scope": "minute",
            }
            summary["diagnostics_path"] = _archive_diagnostics(root, summary, collected_at=collected_at)
            _record_status(session, summary=summary, collected_at=collected_at, error="minute quota exhausted")
            session.commit()
            return summary

    try:
        result = TwelveDataClient(storage_root=root).fetch_time_series(
            interval=interval,
            outputsize=outputsize,
        )
        closed_before = collected_at - timedelta(seconds=PROVIDER_GRACE_SECONDS)
        closed = [
            candle
            for candle in result.candles
            if candle.open_time + timedelta(seconds=interval_seconds) <= closed_before
        ]

        with SessionLocal() as session:
            ensure_analysis_tables(session)
            local_rows = _local_primary_rows(session, timeframe=timeframe, limit=max(outputsize + 4, 20))
            local_by_time = {_as_utc(row.open_time): row for row in local_rows}
            comparison_bps: list[float] = []
            fallback_count = 0
            fallback_open_times: list[str] = []

            for candle in closed:
                local = local_by_time.get(candle.open_time)
                is_fallback = local is None
                if is_fallback:
                    fallback_count += 1
                    fallback_open_times.append(candle.open_time.isoformat())
                else:
                    comparison_bps.append(_price_diff_bps(float(local.close), candle.close))

                source_ref = {
                    **result.source_ref(),
                    "quality_status": "accepted_fallback" if is_fallback else "accepted_validation",
                    "source_role": "fallback" if is_fallback else "validation",
                    "fallback_reason": "jin10_incomplete_or_stale" if is_fallback else None,
                    "provider_timestamp": candle.open_time.isoformat(),
                    "provider_grace_seconds": PROVIDER_GRACE_SECONDS,
                    "volume_semantics": "unavailable",
                }
                upsert_market_candle(
                    session,
                    asset="XAUUSD",
                    timeframe=timeframe,
                    open_time=candle.open_time,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=None,
                    source=f"twelvedata_xauusd_{timeframe}",
                    source_ref=source_ref,
                    raw_path=result.raw_path,
                )

            diagnostics = {
                "status": "ok" if closed else "no_closed_bars",
                "interval": interval,
                "timeframe": timeframe,
                "run_id": run_id,
                "retrieved_at": result.retrieved_at.isoformat(),
                "closed_before": closed_before.isoformat(),
                "persisted": len(closed),
                "request_count": 1,
                "fallback_count": fallback_count,
                "fallback_open_times": fallback_open_times,
                "comparison": _comparison_summary(comparison_bps),
                "credits_used": result.credits_used,
                "credits_left": result.credits_left,
                "credit_scope": "minute",
                "raw_path": result.raw_path,
            }
            diagnostics_path = _archive_diagnostics(root, diagnostics, collected_at=collected_at)
            diagnostics["diagnostics_path"] = diagnostics_path
            _record_status(session, summary=diagnostics, collected_at=collected_at)
            session.commit()
            return diagnostics
    except Exception as exc:
        logger.warning("Twelve Data %s refresh failed: %s", interval, exc)
        with SessionLocal() as session:
            ensure_analysis_tables(session)
            quota_exhausted = isinstance(exc, TwelveDataQuotaError)
            summary = {
                "status": "quota_exhausted" if quota_exhausted else "error",
                "interval": interval,
                "timeframe": timeframe,
                "run_id": run_id,
                "persisted": 0,
                "request_count": 1,
                "fallback_count": 0,
                "fallback_open_times": [],
                "comparison": _comparison_summary([]),
                "credits_used": None,
                "credits_left": 0 if quota_exhausted else None,
                "credit_scope": "minute",
            }
            summary["diagnostics_path"] = _archive_diagnostics(root, summary, collected_at=collected_at)
            _record_status(session, summary=summary, collected_at=collected_at, error=str(exc))
            session.commit()
        return summary


def _local_primary_rows(session: Any, *, timeframe: str, limit: int) -> list[Any]:
    if timeframe == "5m":
        return list_market_candles(
            session,
            asset="XAUUSD",
            timeframe="5m",
            limit=limit,
            source="jin10_mcp_derived_5m",
        )

    five_minute_rows = list_market_candles(
        session,
        asset="XAUUSD",
        timeframe="5m",
        limit=(limit + 2) * (TWELVE_DATA_INTERVALS[_provider_interval(timeframe)][1] // 300),
    )
    canonical = select_canonical_xauusd_rows(five_minute_rows)
    return aggregate_complete_candles(
        canonical,
        source_timeframe="5m",
        target_timeframe=timeframe,
        source=f"canonical_xauusd_5m_aggregate_{timeframe}",
    )


def _record_status(
    session: Any,
    *,
    summary: dict[str, Any],
    collected_at: datetime,
    error: str | None = None,
) -> None:
    existing = get_data_source_status(session, TWELVE_DATA_SOURCE_KEY)
    metadata = dict(existing.source_metadata or {}) if existing is not None else {}
    intervals = dict(metadata.get("intervals") or {})
    timeframe = str(summary["timeframe"])
    intervals[timeframe] = dict(summary)
    metadata.update(
        {
            "provider_role": "validation_and_fallback",
            "entitlement": "trial",
            "production_guaranteed": False,
            "daily_request_budget": 800,
            "normal_scheduled_requests_per_day": 414,
            "credit_headers_scope": "minute",
            "provider_grace_seconds": PROVIDER_GRACE_SECONDS,
            "latest_health_at": collected_at.isoformat(),
            "intervals": intervals,
        }
    )
    upsert_data_source_status(
        session,
        {
            "source_key": TWELVE_DATA_SOURCE_KEY,
            "source_name": "Twelve Data XAU/USD",
            "source_group": "market",
            "source_type": "api",
            "access_method": "rest_time_series",
            "configured": error is None or "not configured" not in error.lower(),
            "raw_ingested": bool(summary.get("raw_path")) or bool(existing and existing.raw_ingested),
            "parsed": summary.get("persisted", 0) > 0 or bool(existing and existing.parsed),
            "analysis_ready": summary.get("persisted", 0) > 0 or bool(existing and existing.analysis_ready),
            "latest_raw_time": collected_at
            if summary.get("raw_path")
            else existing.latest_raw_time
            if existing is not None
            else None,
            "latest_parsed_time": collected_at
            if summary.get("persisted", 0) > 0
            else existing.latest_parsed_time
            if existing is not None
            else None,
            "latest_snapshot_id": summary.get("diagnostics_path"),
            "row_count": summary.get("persisted", 0),
            "status": "ok" if summary.get("status") == "ok" else "degraded",
            "error_message": error,
            "last_run_id": summary.get("run_id"),
            "source_metadata": metadata,
        },
    )


def _minute_quota_exhausted(session: Any, collected_at: datetime) -> bool:
    status = get_data_source_status(session, TWELVE_DATA_SOURCE_KEY)
    if status is None or not isinstance(status.source_metadata, dict):
        return False
    intervals = status.source_metadata.get("intervals")
    if not isinstance(intervals, dict):
        return False
    for item in intervals.values():
        if not isinstance(item, dict) or item.get("credits_left") != 0:
            continue
        retrieved_at = _parse_datetime(item.get("retrieved_at"))
        if retrieved_at is not None and retrieved_at.replace(second=0, microsecond=0) == collected_at.replace(
            second=0,
            microsecond=0,
        ):
            return True
    return False


def _due_intervals(collected_at: datetime) -> list[str]:
    minute = collected_at.minute
    if minute % 5 != 1:
        return []
    intervals = ["5min"]
    if minute % 15 == 1:
        intervals.append("15min")
    if minute == 1:
        intervals.append("1h")
        try:
            from zoneinfo import ZoneInfo

            new_york_hour = collected_at.astimezone(ZoneInfo("America/New_York")).hour
        except Exception:
            new_york_hour = -1
        if new_york_hour in {1, 5, 9, 13, 17, 21}:
            intervals.append("4h")
    return [interval for interval in TWELVE_DATA_DISPATCH_ORDER if interval in intervals]


def _archive_diagnostics(root: Path, payload: dict[str, Any], *, collected_at: datetime) -> str:
    directory = root / "monitoring" / "market_data" / "twelvedata" / collected_at.date().isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['timeframe']}-{collected_at.strftime('%H%M%S%f')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.relative_to(root).as_posix()


def _comparison_summary(values: list[float]) -> dict[str, float | int | None]:
    latest = values[-1] if values else None
    ordered = sorted(values)
    return {
        "sample_count": len(ordered),
        "latest_bps": latest,
        "median_bps": median(ordered) if ordered else None,
        "p95_bps": _percentile(ordered, 0.95),
        "max_bps": max(ordered) if ordered else None,
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = min(round((len(values) - 1) * quantile), len(values) - 1)
    return values[index]


def _price_diff_bps(primary: float, comparison: float) -> float:
    midpoint = (primary + comparison) / 2
    return 0.0 if midpoint == 0 else abs(primary - comparison) / midpoint * 10_000


def _provider_interval(timeframe: str) -> str:
    for provider_interval, (candidate, _) in TWELVE_DATA_INTERVALS.items():
        if candidate == timeframe:
            return provider_interval
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
