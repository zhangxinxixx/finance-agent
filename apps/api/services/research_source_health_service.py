"""Query-time projection for persisted Gold research source-health records."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


VIEW_SCHEMA_VERSION = "gold_core_source_health_view.v2"
EVALUATION_VERSION = "gold_core_source_health_current.v1"
_MARKET_PROBE_TTL = timedelta(minutes=15)
_OFFICIAL_PROBE_TTL = timedelta(hours=24)
_CLOCK_SKEW = timedelta(minutes=1)
_SUCCESS_STATUSES = {"available", "ok", "published", "success"}
_FAILURE_STATUSES = {
    "auth_failed",
    "error",
    "failed",
    "fetch_failed",
    "future_observation",
    "invalid",
    "missing",
    "not_configured",
    "not_connected",
    "unavailable",
}
_OFFICIAL_LOW_FREQUENCY = {"gdp_now", "ism_manufacturing", "ism_services"}


def build_research_source_health_view(
    records: Iterable[Any],
    *,
    evaluated_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Return immutable recorded evidence plus a query-time health projection."""

    now = _evaluation_time(evaluated_at)
    items = [_project_record(record, now=now) for record in records]
    alerts = [
        {"source_key": item["source_key"], "severity": "error", "reason": item["reason"]}
        for item in items
        if item["alert_required"]
    ]
    statuses = {str(item["source_health"]) for item in items}
    if not items:
        overall = "UNKNOWN"
    elif "FAILED" in statuses:
        overall = "FAILED"
    elif "UNKNOWN" in statuses:
        overall = "UNKNOWN"
    else:
        overall = "HEALTHY"
    return {
        "schema_version": VIEW_SCHEMA_VERSION,
        "evaluation_version": EVALUATION_VERSION,
        "evaluated_at": now.isoformat(),
        "items": items,
        "overall_status": overall,
        "production_ready": bool(items) and all(
            item["source_health"] in {"HEALTHY", "WAITING_RELEASE", "EXPECTED_STALE"}
            for item in items
        ),
        "alerts": alerts,
    }


def _project_record(record: Any, *, now: datetime) -> dict[str, Any]:
    metadata, context = _record_parts(record)
    source_key = str(metadata.get("source_key") or context.get("source_key") or "unknown")
    recorded = deepcopy(metadata)
    recorded.update(
        {
            "persisted_status": context.get("status"),
            "persisted_error_message": context.get("error_message"),
            "persisted_updated_at": context.get("updated_at"),
        }
    )

    if source_key.startswith("tv_"):
        current = _evaluate_market_source(metadata, context=context, now=now)
    elif source_key in _OFFICIAL_LOW_FREQUENCY:
        current = _evaluate_official_source(metadata, context=context, now=now)
    elif source_key == "fedwatch":
        current = _evaluate_intraday_probe(metadata, context=context, now=now)
    else:
        current = _evaluate_generic_source(metadata, context=context, now=now)

    result = deepcopy(metadata)
    result.update(
        {
            "source_key": source_key,
            "source_health": current["source_health"],
            "staleness": current["staleness"],
            "reason": current["reason"],
            "alert_required": current["alert_required"],
            "evaluated_at": now.isoformat(),
            "recorded_source_health": metadata.get("source_health"),
            "recorded_staleness": metadata.get("staleness"),
            "recorded_reason": metadata.get("reason"),
            "recorded": recorded,
            "current": current,
        }
    )
    if _market_asset_class(metadata) == "energy":
        current_failure = (
            "ENERGY_INTRADAY"
            if current["source_health"] in {"FAILED", "UNKNOWN"}
            else None
        )
        result["critical_freshness_failure"] = current_failure
        current["critical_freshness_failure"] = current_failure
    return result


def _evaluate_market_source(
    metadata: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = _evaluation_base(metadata, now=now)
    failure = _collection_failure(metadata, context)
    if failure:
        return _finish(base, "FAILED", "COLLECTION_FAILED", failure)

    fetched = _aware_time(metadata.get("retrieved_at"))
    observed = _aware_time(
        metadata.get("observed_at")
        or metadata.get("minute_bar_time")
        or metadata.get("actual_latest_date")
    )
    base.update(
        {
            "retrieved_at": _iso(fetched),
            "observed_at": _iso(observed),
            "retrieval_age_seconds": _age_seconds(now, fetched),
            "observation_age_seconds": _age_seconds(now, observed),
        }
    )

    if fetched is None:
        return _finish(base, "UNKNOWN", "PROBE_TIME_UNVERIFIED", "market_probe_time_missing_or_timezone_invalid")
    if fetched > now + _CLOCK_SKEW:
        return _finish(base, "FAILED", "INVALID_TIME", "market_probe_time_is_in_the_future")
    if now - fetched > _MARKET_PROBE_TTL:
        return _finish(base, "FAILED", "STALE_CAPTURE", "market_probe_stale")
    if observed is None:
        return _finish(base, "FAILED", "CLOCK_UNVERIFIED", "observation_time_missing_or_timezone_invalid")
    if observed > now + _CLOCK_SKEW:
        return _finish(base, "FAILED", "INVALID_TIME", "market_observation_time_is_in_the_future")

    delay_seconds = _number(metadata.get("delay_seconds"))
    if delay_seconds is None or not isfinite(delay_seconds) or delay_seconds < 0:
        return _finish(base, "UNKNOWN", "DELAY_UNVERIFIED", "provider_delay_seconds_missing_or_invalid")
    if delay_seconds > 0:
        return _finish(base, "FAILED", "DELAYED_BAR", "provider_reports_delayed_market_data")

    asset_class = _market_asset_class(metadata)
    session = _market_session(asset_class, metadata=metadata, now=now)
    base["market_session"] = session

    observation_age = now - observed
    if session["state"] == "CLOSED":
        expected_close = _aware_time(session.get("latest_expected_close"))
        if expected_close is None:
            if observation_age > timedelta(days=4):
                return _finish(base, "FAILED", "STALE_BAR", "closed_market_observation_is_too_old")
            return _finish(base, "UNKNOWN", "SESSION_UNVERIFIED", "latest_expected_market_session_unverified")
        if observed < expected_close - _MARKET_PROBE_TTL:
            return _finish(base, "FAILED", "STALE_BAR", "observation_predates_latest_expected_market_session")
        return _finish(base, "EXPECTED_STALE", "EXPECTED_STALE", "market_closed_recent_session_observation")

    if observation_age > _MARKET_PROBE_TTL:
        if session["state"] == "UNVERIFIED":
            return _finish(base, "UNKNOWN", "SESSION_UNVERIFIED", "stale_observation_and_instrument_session_unverified")
        return _finish(base, "FAILED", "STALE_BAR", "market_observation_stale")
    if session["state"] == "UNKNOWN":
        return _finish(base, "UNKNOWN", "SESSION_UNKNOWN", "market_asset_class_unrecognized")
    return _finish(base, "HEALTHY", "FRESH_MINUTE_BAR", "fresh_probe_and_observation")


def _evaluate_official_source(
    metadata: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = _evaluation_base(metadata, now=now)
    failure = _collection_failure(metadata, context, allow_not_published=True)
    if failure:
        return _finish(base, "FAILED", "COLLECTION_FAILED", failure)

    fetched = _aware_time(metadata.get("retrieved_at"))
    base.update(
        {
            "retrieved_at": _iso(fetched),
            "retrieval_age_seconds": _age_seconds(now, fetched),
            "observation_date": _date_value(metadata.get("actual_latest_date")),
            "official_latest_date": _date_value(metadata.get("official_latest_date")),
        }
    )
    if fetched is None:
        return _finish(base, "UNKNOWN", "PROBE_TIME_UNVERIFIED", "official_probe_time_missing_or_timezone_invalid")
    if fetched > now + _CLOCK_SKEW:
        return _finish(base, "FAILED", "INVALID_TIME", "official_probe_time_is_in_the_future")

    actual = _date_value(metadata.get("actual_latest_date"))
    official = _date_value(metadata.get("official_latest_date"))
    if not actual or not official:
        return _finish(base, "UNKNOWN", "OBSERVATION_UNVERIFIED", "official_latest_observation_unverified")
    if actual > now.date() or official > now.date():
        return _finish(base, "FAILED", "INVALID_TIME", "official_observation_date_is_in_the_future")
    if actual < official:
        return _finish(base, "FAILED", "COLLECTOR_STALE", "official_published_data_newer_than_local")
    if actual > official:
        return _finish(base, "UNKNOWN", "OFFICIAL_DATE_CONFLICT", "local_observation_newer_than_recorded_official_latest")

    release = _release_schedule(metadata, now=now)
    base["release_check"] = release
    collector_status = str(metadata.get("collector_status") or "").lower()
    if release["status"] == "invalid":
        return _finish(base, "UNKNOWN", "RELEASE_SCHEDULE_UNVERIFIED", "expected_release_time_invalid_or_timezone_missing")
    if release["status"] == "not_due":
        health = "WAITING_RELEASE" if collector_status == "not_published" else "HEALTHY"
        return _finish(base, health, "RELEASE_NOT_DUE", "next_official_release_not_due")
    if release["status"] == "date_in_progress":
        return _finish(base, "WAITING_RELEASE", "RELEASE_DATE_IN_PROGRESS", "date_only_release_window_still_in_progress")
    if release["status"] == "due":
        checked_after_due = _probe_after_release(fetched, release)
        if checked_after_due and collector_status in _SUCCESS_STATUSES:
            return _finish(base, "HEALTHY", "RELEASE_CHECKED", "official_release_checked_after_due")
        return _finish(base, "UNKNOWN", "RELEASE_DUE_UNVERIFIED", "expected_release_due_probe_not_refreshed")

    if now - fetched > _OFFICIAL_PROBE_TTL:
        return _finish(base, "UNKNOWN", "PROBE_STALE", "official_probe_stale_and_release_schedule_unverified")
    if collector_status == "not_published":
        return _finish(base, "UNKNOWN", "RELEASE_SCHEDULE_UNVERIFIED", "not_published_without_verified_release_schedule")
    return _finish(base, "HEALTHY", "PROBE_CURRENT", "official_probe_current")


def _evaluate_intraday_probe(
    metadata: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = _evaluation_base(metadata, now=now)
    failure = _collection_failure(metadata, context)
    if failure:
        return _finish(base, "FAILED", "COLLECTION_FAILED", failure)
    fetched = _aware_time(metadata.get("retrieved_at"))
    observed = _aware_time(metadata.get("observed_at") or metadata.get("actual_latest_date"))
    base.update(
        {
            "retrieved_at": _iso(fetched),
            "observed_at": _iso(observed),
            "retrieval_age_seconds": _age_seconds(now, fetched),
            "observation_age_seconds": _age_seconds(now, observed),
        }
    )
    if fetched is None or observed is None:
        return _finish(base, "UNKNOWN", "CLOCK_UNVERIFIED", "intraday_probe_or_observation_time_unverified")
    if fetched > now + _CLOCK_SKEW or observed > now + _CLOCK_SKEW:
        return _finish(base, "FAILED", "INVALID_TIME", "intraday_probe_or_observation_time_is_in_the_future")
    if now - fetched > _MARKET_PROBE_TTL or now - observed > _MARKET_PROBE_TTL:
        return _finish(base, "FAILED", "STALE_INTRADAY", "intraday_probe_SLA_exceeded")
    return _finish(base, "HEALTHY", "FRESH_INTRADAY", "intraday_probe_and_observation_current")


def _evaluate_generic_source(
    metadata: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    base = _evaluation_base(metadata, now=now)
    failure = _collection_failure(metadata, context)
    if failure:
        return _finish(base, "FAILED", "COLLECTION_FAILED", failure)
    fetched = _aware_time(metadata.get("retrieved_at"))
    base.update({"retrieved_at": _iso(fetched), "retrieval_age_seconds": _age_seconds(now, fetched)})
    if fetched is None:
        return _finish(base, "UNKNOWN", "PROBE_TIME_UNVERIFIED", "probe_time_missing_or_timezone_invalid")
    if fetched > now + _CLOCK_SKEW:
        return _finish(base, "FAILED", "INVALID_TIME", "probe_time_is_in_the_future")
    if now - fetched > _OFFICIAL_PROBE_TTL:
        return _finish(base, "UNKNOWN", "PROBE_STALE", "probe_stale")
    return _finish(base, "HEALTHY", "PROBE_CURRENT", "probe_current")


def _release_schedule(metadata: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    raw_time = metadata.get("expected_release_time")
    raw_date = metadata.get("expected_release_date")
    if raw_time:
        release_time = _aware_time(raw_time)
        if release_time is None:
            return {"status": "invalid", "time_precision": "timestamp", "expected_release_time": str(raw_time)}
        return {
            "status": "due" if now >= release_time else "not_due",
            "time_precision": "timestamp",
            "expected_release_time": release_time.isoformat(),
            "expected_release_date": release_time.date().isoformat(),
        }
    release_date = _date_value(raw_date)
    if raw_date and release_date is None:
        return {"status": "invalid", "time_precision": "date", "expected_release_date": str(raw_date)}
    if release_date:
        if now.date() > release_date:
            status = "due"
        elif now.date() == release_date:
            status = "date_in_progress"
        else:
            status = "not_due"
        return {"status": status, "time_precision": "date", "expected_release_date": release_date.isoformat()}
    return {"status": "unverified", "time_precision": "unknown", "expected_release_date": None}


def _probe_after_release(fetched: datetime, release: Mapping[str, Any]) -> bool:
    if release.get("time_precision") == "timestamp":
        release_time = _aware_time(release.get("expected_release_time"))
        return bool(release_time and fetched >= release_time)
    release_date = _date_value(release.get("expected_release_date"))
    return bool(release_date and fetched.date() > release_date)


def _market_asset_class(metadata: Mapping[str, Any]) -> str:
    source_key = str(metadata.get("source_key") or "").lower()
    symbol = source_key.removeprefix("tv_").upper()
    ticker = str(metadata.get("ticker") or "").upper()
    if symbol in {"WTI", "BRENT"} or any(marker in ticker for marker in (":CL", ":BRN")):
        return "energy"
    if symbol in {"SPX", "SPY", "NDX", "QQQ", "DJI", "DJIA"} or ticker.startswith(
        ("NASDAQ:", "NYSE:", "AMEX:", "SP:")
    ):
        return "us_equity"
    if symbol in {"US02Y", "US03M", "US05Y", "US10Y", "US30Y"}:
        return "us_rates"
    if symbol in {"XAUUSD", "DXY", "EURUSD", "GBPUSD", "USDJPY"}:
        return "fx_metals"
    return "unknown"


def _market_session(
    asset_class: str,
    *,
    metadata: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    eastern = now.astimezone(ZoneInfo("America/New_York"))
    weekday = eastern.weekday()
    hour = eastern.hour + eastern.minute / 60
    result: dict[str, Any] = {
        "asset_class": asset_class,
        "state": "UNKNOWN",
        "reason": "instrument_session_unrecognized",
        "timezone": "America/New_York",
        "latest_expected_close": None,
    }
    if asset_class == "unknown":
        return result

    if asset_class == "us_equity":
        holiday = _us_holiday(eastern.date())
        if weekday >= 5 or holiday:
            result.update(state="CLOSED", reason="us_equity_weekend_or_holiday_calendar_scope_unverified")
        elif hour < 9.5:
            result.update(state="CLOSED", reason="us_equity_preopen_calendar_scope_unverified")
        elif hour >= 16:
            result.update(state="CLOSED", reason="us_equity_after_close_calendar_scope_unverified")
        else:
            result.update(state="UNVERIFIED", reason="us_equity_regular_hours_but_exchange_calendar_unverified")
        explicit_close = _aware_time(metadata.get("expected_session_close"))
        if explicit_close is not None and explicit_close <= now + _CLOCK_SKEW:
            result["latest_expected_close"] = explicit_close.isoformat()
            result["reason"] = "explicit_instrument_session_close"
        return result

    if weekday == 5:
        result.update(state="CLOSED", reason=f"{asset_class}_weekend_product_calendar_unverified")
        return result
    if weekday == 6:
        reopen_hour = 17 if asset_class == "fx_metals" else 18 if asset_class == "energy" else None
        if reopen_hour is None or hour < reopen_hour:
            result.update(state="CLOSED", reason=f"{asset_class}_weekend_product_calendar_unverified")
            return result
        result.update(state="UNVERIFIED", reason=f"{asset_class}_sunday_reopen_product_hours_unverified")
        return result
    if asset_class == "fx_metals":
        result.update(state="OPEN", reason="fx_metals_weekday_continuous_window")
    else:
        result.update(state="UNVERIFIED", reason=f"{asset_class}_product_hours_unverified")
    return result


def _us_holiday(value: date) -> bool:
    from apps.features.research.sessions import build_session_quality

    return build_session_quality({"trade_date": value.isoformat()}).get("session_class") == "HOLIDAY"


def _collection_failure(
    metadata: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    allow_not_published: bool = False,
) -> str | None:
    collector_status = str(metadata.get("collector_status") or "").lower()
    persisted_status = str(context.get("status") or "").lower()
    configured = metadata.get("configured", context.get("configured"))
    if collector_status in _FAILURE_STATUSES:
        return f"collector_status_{collector_status}"
    if persisted_status in _FAILURE_STATUSES:
        return f"persisted_status_{persisted_status}"
    if context.get("error_message"):
        return "persisted_collection_error"
    if configured is False:
        return "source_not_configured"
    if collector_status == "not_published" and not allow_not_published:
        return "collector_status_not_published"
    return None


def _record_parts(record: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(record, Mapping):
        nested = record.get("source_metadata")
        metadata = deepcopy(dict(nested)) if isinstance(nested, Mapping) else deepcopy(dict(record))
        getter = record.get
    else:
        nested = getattr(record, "source_metadata", None)
        metadata = deepcopy(dict(nested)) if isinstance(nested, Mapping) else {}

        def getter(key: str, default: Any = None) -> Any:
            return getattr(record, key, default)
    context = {
        "source_key": getter("source_key"),
        "status": getter("status"),
        "error_message": getter("error_message"),
        "configured": getter("configured"),
        "updated_at": _serializable_time(getter("updated_at")),
    }
    metadata.setdefault("source_key", context["source_key"])
    return metadata, context


def _evaluation_base(metadata: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    return {
        "evaluation_version": EVALUATION_VERSION,
        "evaluated_at": now.isoformat(),
        "source_key": str(metadata.get("source_key") or "unknown"),
    }


def _finish(base: dict[str, Any], health: str, staleness: str, reason: str) -> dict[str, Any]:
    base.update(
        {
            "source_health": health,
            "staleness": staleness,
            "reason": reason,
            "alert_required": health in {"FAILED", "UNKNOWN"},
        }
    )
    return base


def _evaluation_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("evaluated_at must include timezone")
        return value.astimezone(UTC)
    parsed = _aware_time(value)
    if parsed is None:
        raise ValueError("evaluated_at must be a timezone-aware ISO timestamp")
    return parsed


def _aware_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _age_seconds(now: datetime, value: datetime | None) -> float | None:
    return None if value is None else (now - value).total_seconds()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serializable_time(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
