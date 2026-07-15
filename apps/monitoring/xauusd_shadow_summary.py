"""Read-only, durable XAU/USD provider shadow-run summaries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from apps.features.market_data import aggregate_complete_candles, select_canonical_xauusd_rows
from database.models.analysis import DataSourceStatus, MarketCandle


SHADOW_ARTIFACT_NAME = "shadow_summary.json"
SHADOW_DAYS_TARGET = 10
MIN_COMPARISON_SAMPLES = 20
FINALIZATION_GRACE_SECONDS = 10 * 60
_FIVE_MINUTE = timedelta(minutes=5)
_TIMEFRAMES = ("5m", "15m", "1h", "4h")
_TWELVE_SOURCES = {timeframe: f"twelvedata_xauusd_{timeframe}" for timeframe in _TIMEFRAMES}


class ShadowArtifactConflictError(RuntimeError):
    """A trade-date summary already exists with different observed inputs."""


def build_xauusd_shadow_summary(
    session: Any,
    *,
    trade_date: date | str,
    storage_root: Path | str,
    as_of: datetime | None = None,
    include_current_in_rollup: bool = True,
) -> dict[str, Any]:
    """Build a single deterministic daily observation without mutating upstream data."""
    day = _parse_trade_date(trade_date)
    root = Path(storage_root)
    window_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    observed_as_of = _as_utc(as_of or datetime.now(UTC))
    is_trade_day = day.weekday() < 5
    is_finalized = is_trade_day and observed_as_of >= window_end + timedelta(seconds=FINALIZATION_GRACE_SECONDS)

    all_rows = list(
        session.scalars(
            select(MarketCandle)
            .where(
                MarketCandle.asset == "XAUUSD",
                MarketCandle.open_time >= window_start,
                MarketCandle.open_time < window_end,
            )
            .order_by(MarketCandle.open_time.asc(), MarketCandle.id.asc())
        ).all()
    )
    five_minute_rows = [row for row in all_rows if row.timeframe == "5m"]
    jin10_rows = [row for row in five_minute_rows if row.source == "jin10_mcp_derived_5m"]
    canonical_rows = select_canonical_xauusd_rows(five_minute_rows)
    twelve_rows = {timeframe: [row for row in all_rows if row.source == source] for timeframe, source in _TWELVE_SOURCES.items()}

    jin10_times = {_as_utc(row.open_time) for row in jin10_rows}
    canonical_times = {_as_utc(row.open_time) for row in canonical_rows}
    observed_provider_times = jin10_times | {_as_utc(row.open_time) for row in twelve_rows["5m"]}
    expected_slots = len(observed_provider_times)
    diagnostics = _load_twelvedata_diagnostics(root, day)
    twelve_summary = _summarize_twelve(diagnostics, twelve_rows, session=session, trade_date=day)
    comparison = _comparison_summary(canonical_rows, twelve_rows["5m"])

    reasons: list[str] = []
    if not is_trade_day:
        reasons.append("not_utc_weekday")
    elif not is_finalized:
        reasons.append("sample_window_not_finalized")
    if not jin10_rows:
        reasons.append("jin10_5m_unavailable")
    elif len(jin10_times) < expected_slots:
        reasons.append("jin10_5m_incomplete")
    if not canonical_rows:
        reasons.append("canonical_5m_unavailable")
    elif len(canonical_times) < expected_slots:
        reasons.append("canonical_5m_incomplete")
    if comparison["availability"] != "available":
        reasons.append(f"comparison_{comparison['availability']}")
    if twelve_summary["request_count"] == 0:
        reasons.append("twelvedata_diagnostics_unavailable")
    if twelve_summary["quota"]["exhausted"]:
        reasons.append("twelvedata_quota_exhausted")

    if not is_trade_day:
        status = "unavailable"
    elif twelve_summary["quota"]["exhausted"]:
        status = "fail"
    elif not observed_provider_times:
        status = "unavailable"
    elif reasons:
        status = "partial"
    else:
        status = "pass"

    payload: dict[str, Any] = {
        "artifact_type": "xauusd_shadow_summary",
        "schema_version": 1,
        "trade_date": day.isoformat(),
        "finalization": {
            "as_of": observed_as_of.isoformat(),
            "finalized": is_finalized,
            "grace_seconds": FINALIZATION_GRACE_SECONDS,
            "is_trade_day": is_trade_day,
            "trade_day_basis": "utc_weekday_without_holiday_calendar",
        },
        "sample_window": {
            "timezone": "UTC",
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "expected_5m_slots": expected_slots,
            "expected_slots_method": "observed_provider_union",
            "coverage_limit": "joint_provider_outages_are_not_detectable_without_an_exchange_session_calendar",
        },
        "jin10": {
            "success": bool(jin10_rows),
            "success_rate": len(jin10_times) / expected_slots if expected_slots else None,
            "completeness": _completeness(len(jin10_times), expected_slots),
            "source": "jin10_mcp_derived_5m",
        },
        "canonical_5m": {
            "completeness": _completeness(len(canonical_times), expected_slots),
            "source_breakdown": _source_breakdown(canonical_rows),
        },
        "twelvedata": twelve_summary,
        "comparison": comparison,
        "boundary_diagnostics": _boundary_diagnostics(canonical_rows, twelve_rows, window_end=window_end),
        "status": status,
        "reasons": reasons,
        "source_refs": _source_refs(jin10_rows, canonical_rows, diagnostics),
        "artifact_refs": [path for path, _ in diagnostics],
    }
    payload["rollup"] = _build_rollup(
        root,
        current=payload if include_current_in_rollup and is_finalized else None,
    )
    return payload


def default_shadow_output_path(*, storage_root: Path | str, trade_date: date | str) -> Path:
    day = _parse_trade_date(trade_date)
    return Path(storage_root) / "monitoring" / "market_data" / "xauusd_shadow" / day.isoformat() / SHADOW_ARTIFACT_NAME


def write_xauusd_shadow_summary(payload: dict[str, Any], *, output_path: Path | str) -> tuple[Path, bool]:
    """Write once per exact payload; reject a same-date artifact with different inputs."""
    finalization = payload.get("finalization")
    if not isinstance(finalization, dict) or finalization.get("finalized") is not True:
        raise ValueError("shadow summary must be finalized before it is written")
    target = Path(output_path)
    encoded = _canonical_json(payload)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == encoded:
            return target, False
        raise ShadowArtifactConflictError(f"shadow artifact already exists with different content: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded, encoding="utf-8")
    return target, True


def _summarize_twelve(
    diagnostics: list[tuple[str, dict[str, Any]]],
    twelve_rows: dict[str, list[Any]],
    *,
    session: Any,
    trade_date: date,
) -> dict[str, Any]:
    by_timeframe: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in _TIMEFRAMES}
    for path, item in diagnostics:
        timeframe = str(item.get("timeframe") or "")
        if timeframe in by_timeframe:
            by_timeframe[timeframe].append({"path": path, **item})

    request_count = 0
    fallback_keys: set[tuple[str, str]] = set()
    used_values: list[int] = []
    credits_left: int | None = None
    quota_exhausted = False
    intervals: dict[str, Any] = {}
    artifact_refs: list[str] = []
    for timeframe in _TIMEFRAMES:
        items = by_timeframe[timeframe]
        artifact_refs.extend(item["path"] for item in items)
        requests = sum(int(item.get("request_count", 1)) for item in items)
        interval_fallback_times = {
            str(value)
            for item in items
            for value in item.get("fallback_open_times") or []
            if isinstance(value, str)
        }
        fallbacks = len(interval_fallback_times)
        latest = items[-1] if items else {}
        request_count += requests
        fallback_keys.update((timeframe, value) for value in interval_fallback_times)
        for item in items:
            if item.get("credits_used") is not None:
                used_values.append(int(item["credits_used"]))
            if item.get("credits_left") is not None:
                credits_left = int(item["credits_left"])
            quota_exhausted = quota_exhausted or item.get("status") in {"minute_quota_exhausted", "quota_exhausted"}
            quota_exhausted = quota_exhausted or item.get("credits_left") == 0
        intervals[timeframe] = {
            "request_count": requests,
            "fallback_count": fallbacks,
            "persisted_count": sum(int(item.get("persisted") or 0) for item in items),
            "market_candle_count": len(twelve_rows[timeframe]),
            "latest_status": latest.get("status") if latest else "unavailable",
            "diagnostic_refs": [item["path"] for item in items],
        }

    status_row = session.scalar(select(DataSourceStatus).where(DataSourceStatus.source_key == "twelvedata_xauusd"))
    metadata = status_row.source_metadata if status_row is not None and isinstance(status_row.source_metadata, dict) else {}
    status_intervals = metadata.get("intervals") if isinstance(metadata.get("intervals"), dict) else {}
    for item in status_intervals.values():
        if not isinstance(item, dict) or not _same_trade_date(item.get("retrieved_at"), trade_date):
            continue
        quota_exhausted = quota_exhausted or item.get("credits_left") == 0
        if credits_left is None and item.get("credits_left") is not None:
            credits_left = int(item["credits_left"])

    return {
        "request_count": request_count,
        "fallback_count": len(fallback_keys),
        "intervals": intervals,
        "credits": {
            "used_latest": used_values[-1] if used_values else None,
            "used_max_observed": max(used_values) if used_values else None,
            "left_latest": credits_left,
            "scope": "minute",
        },
        "quota": {
            "exhausted": quota_exhausted,
            "status": "exhausted" if quota_exhausted else "available",
            "request_count": request_count,
            "daily_request_budget": 800,
            "request_budget_utilization": request_count / 800,
        },
        "diagnostic_refs": artifact_refs,
    }


def _comparison_summary(canonical_rows: list[Any], twelve_rows: list[Any]) -> dict[str, Any]:
    canonical_by_time = {_as_utc(row.open_time): row for row in canonical_rows}
    values = sorted(
        _price_diff_bps(float(canonical_by_time[_as_utc(row.open_time)].close), float(row.close))
        for row in twelve_rows
        if _as_utc(row.open_time) in canonical_by_time
        and canonical_by_time[_as_utc(row.open_time)].source != row.source
    )
    if not values:
        availability = "unavailable"
    elif len(values) < MIN_COMPARISON_SAMPLES:
        availability = "partial"
    else:
        availability = "available"
    return {
        "availability": availability,
        "sample_count": len(values),
        "minimum_samples": MIN_COMPARISON_SAMPLES,
        "p50_bps": _percentile(values, 0.50) if availability == "available" else None,
        "p95_bps": _percentile(values, 0.95) if availability == "available" else None,
        "p99_bps": _percentile(values, 0.99) if availability == "available" else None,
    }


def _boundary_diagnostics(
    rows: list[Any],
    native_rows: dict[str, list[Any]],
    *,
    window_end: datetime,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    times = [_as_utc(row.open_time) for row in rows]
    for timeframe in _TIMEFRAMES:
        if timeframe == "5m":
            aligned = sum(1 for item in times if item.minute % 5 == 0 and item.second == 0 and item.microsecond == 0)
            result[timeframe] = {
                "observed_bars": len(times),
                "aligned_bars": aligned,
                "misaligned_bars": len(times) - aligned,
                "complete_buckets": aligned,
                "incomplete_buckets": 0,
                "native_observed_bars": len(native_rows[timeframe]),
            }
            continue
        aggregated = aggregate_complete_candles(
            rows,
            source_timeframe="5m",
            target_timeframe=timeframe,
            source=f"shadow_boundary_{timeframe}",
            closed_before=window_end,
        )
        expected_components = {"15m": 3, "1h": 12, "4h": 48}[timeframe]
        observed_buckets = {_bucket_marker(item, timeframe) for item in times}
        canonical_starts = {_as_utc(item.open_time).isoformat() for item in aggregated}
        native_starts = {_as_utc(item.open_time).isoformat() for item in native_rows[timeframe]}
        matched = canonical_starts & native_starts
        result[timeframe] = {
            "expected_components_per_bucket": expected_components,
            "observed_buckets": len(observed_buckets),
            "complete_buckets": len(aggregated),
            "incomplete_buckets": max(len(observed_buckets) - len(aggregated), 0),
            "complete_bucket_starts": [item.open_time.isoformat() for item in aggregated],
            "native_bucket_starts": sorted(native_starts),
            "matched_bucket_starts": sorted(matched),
            "canonical_only_bucket_starts": sorted(canonical_starts - native_starts),
            "native_only_bucket_starts": sorted(native_starts - canonical_starts),
            "overlap_alignment_ratio": len(matched) / len(native_starts) if native_starts else None,
            "native_coverage_ratio": len(matched) / len(canonical_starts) if canonical_starts else None,
            "boundary_mismatch_count": len(native_starts - canonical_starts),
        }
    return result


def _load_twelvedata_diagnostics(root: Path, trade_date: date) -> list[tuple[str, dict[str, Any]]]:
    directory = root / "monitoring" / "market_data" / "twelvedata" / trade_date.isoformat()
    if not directory.exists():
        return []
    result: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            result.append((path.relative_to(root).as_posix(), payload))
    return result


def _source_refs(jin10_rows: list[Any], canonical_rows: list[Any], diagnostics: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return {
        "jin10_raw_paths": _unique_paths(jin10_rows),
        "canonical_raw_paths": _unique_paths(canonical_rows),
        "twelvedata_diagnostic_paths": [path for path, _ in diagnostics],
    }


def _build_rollup(root: Path, *, current: dict[str, Any] | None) -> dict[str, Any]:
    directory = root / "monitoring" / "market_data" / "xauusd_shadow"
    artifacts: dict[str, dict[str, Any]] = {}
    if directory.exists():
        for path in directory.glob(f"*/{SHADOW_ARTIFACT_NAME}"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                day = _parse_trade_date(payload.get("trade_date"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            finalization = payload.get("finalization")
            if (
                payload.get("artifact_type") == "xauusd_shadow_summary"
                and isinstance(finalization, dict)
                and finalization.get("finalized") is True
                and finalization.get("is_trade_day") is True
            ):
                artifacts[day.isoformat()] = payload
    current_finalization = current.get("finalization") if isinstance(current, dict) else None
    if (
        current is not None
        and isinstance(current_finalization, dict)
        and current_finalization.get("finalized") is True
        and current_finalization.get("is_trade_day") is True
    ):
        artifacts[str(current["trade_date"])] = current
    completed = sorted(artifacts)
    statuses = {day: str(payload.get("status") or "unavailable") for day, payload in artifacts.items()}
    if len(completed) < SHADOW_DAYS_TARGET:
        status = "collecting"
    elif all(item == "pass" for item in statuses.values()):
        status = "pass"
    else:
        status = "fail"
    return {
        "completed_trade_days": len(completed),
        "target_trade_days": SHADOW_DAYS_TARGET,
        "status": status,
        "trade_dates": completed,
        "day_statuses": statuses,
    }


def _completeness(actual: int, expected: int) -> dict[str, Any]:
    if actual == 0:
        status = "unavailable"
    elif actual < expected:
        status = "partial"
    else:
        status = "complete"
    return {"status": status, "observed_slots": actual, "expected_slots": expected, "ratio": actual / expected if expected else None}


def _source_breakdown(rows: list[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        result[row.source] = result.get(row.source, 0) + 1
    return result


def _unique_paths(rows: list[Any]) -> list[str]:
    return sorted({str(row.raw_path) for row in rows if row.raw_path})


def _bucket_marker(value: datetime, timeframe: str) -> str:
    if timeframe == "15m":
        return value.replace(minute=value.minute - value.minute % 15, second=0, microsecond=0).isoformat()
    if timeframe == "1h":
        return value.replace(minute=0, second=0, microsecond=0).isoformat()
    # The canonical aggregator owns the New York session-aware 4h bucket semantics;
    # this marker is only an observed-boundary counter for diagnostics.
    return value.replace(hour=value.hour - value.hour % 4, minute=0, second=0, microsecond=0).isoformat()


def _percentile(values: list[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def _price_diff_bps(primary: float, comparison: float) -> float:
    midpoint = (primary + comparison) / 2
    return 0.0 if midpoint == 0 else abs(primary - comparison) / midpoint * 10_000


def _parse_trade_date(value: date | str | Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _same_trade_date(value: Any, expected: date) -> bool:
    if not value:
        return False
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00"))).date() == expected
    except ValueError:
        return False


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
