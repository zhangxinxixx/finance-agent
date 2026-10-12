"""ADS history projection backed only by persisted FedWatch factors."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.page_data_boundary import sanitize_page_payload
from database.models.fedwatch import FedWatchFactor, FedWatchRawSnapshot


def get_latest_fedwatch_factor_view(
    db: Session,
    *,
    as_of: str,
    allowed_staleness_seconds: int,
) -> dict[str, Any]:
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    row = db.scalars(
        select(FedWatchFactor)
        .where(FedWatchFactor.as_of <= cutoff)
        .order_by(FedWatchFactor.as_of.desc(), FedWatchFactor.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return _missing_view(as_of, allowed_staleness_seconds)

    factor = deepcopy(dict(row.payload or {}))
    health = dict(factor.get("health") or {})
    source_as_of = _parse_time(health.get("source_as_of")) or row.as_of
    if source_as_of is not None and source_as_of.tzinfo is None:
        source_as_of = source_as_of.replace(tzinfo=UTC)
    age_seconds = int((cutoff - source_as_of).total_seconds()) if source_as_of is not None else None
    evaluated_at = _parse_time(health.get("evaluated_at"))
    original_age = health.get("age_seconds")
    if evaluated_at is not None and isinstance(original_age, (int, float)) and not isinstance(original_age, bool):
        oldest_age = int(original_age + (cutoff - evaluated_at).total_seconds())
        age_seconds = max(age_seconds, oldest_age) if age_seconds is not None else oldest_age
    stale = age_seconds is None or age_seconds < 0 or age_seconds > allowed_staleness_seconds
    original_status = str(health.get("status") or "unknown")
    actionable = not stale and original_status == "fresh" and health.get("actionable") is True
    health.update(
        {
            "snapshot_id": row.snapshot_id,
            "evaluated_at": as_of,
            "age_seconds": age_seconds,
            "freshness_seconds": age_seconds,
            "allowed_staleness_seconds": allowed_staleness_seconds,
            "status": "stale" if stale else original_status,
            "reason": "factor_stale" if stale else health.get("reason"),
            "actionable": actionable,
        }
    )
    # ADS operational metadata is selected explicitly; no ODS values or bodies
    # enter the page read model. A failed newer attempt must still block action.
    attempt = db.execute(
        select(FedWatchRawSnapshot.snapshot_id, FedWatchRawSnapshot.collected_at,
               FedWatchRawSnapshot.parse_status, FedWatchRawSnapshot.reason)
        .where(FedWatchRawSnapshot.collected_at <= cutoff)
        .order_by(FedWatchRawSnapshot.collected_at.desc()).limit(1)
    ).mappings().first()
    observed_at = _parse_time(health.get("collected_at")) or _parse_time(row.as_of)
    attempt_at = _parse_time(attempt["collected_at"]) if attempt else None
    if attempt and attempt["parse_status"] != "ok" and attempt_at and observed_at and attempt_at >= observed_at:
        health.update(status="stale", actionable=False, reason="latest_collection_failed_cached_snapshot")
    elif attempt and attempt["snapshot_id"] != row.snapshot_id and attempt_at and observed_at and attempt_at >= observed_at:
        health.update(status="stale", actionable=False, reason="latest_collection_not_materialized")
    factor["health"] = health
    if not health["actionable"]:
        factor["status"] = "degraded"
        repricing = dict(factor.get("repricing") or {})
        repricing.update(
            {
                "status": "unavailable",
                "direction": None,
                "strength": None,
                "score": None,
                "reason": "fedwatch_" + health["status"],
            }
        )
        factor["repricing"] = repricing

    path = factor.get("market_implied_path") if isinstance(factor.get("market_implied_path"), dict) else {}
    meetings = list(path.get("meetings") or [])
    complete = bool(path.get("next_meeting") and path.get("year_end") and meetings and all(
        all(window in meeting.get("comparisons", {}) for window in ("1d", "1w", "1m")) for meeting in meetings
    ))
    return sanitize_page_payload(
        {
            "schema_version": "fedwatch_page_view.v1",
            "as_of": source_as_of.isoformat() if source_as_of else None,
            "evaluated_at": as_of,
            "snapshot_id": row.snapshot_id,
            "source_health": health,
            "factor": factor,
            "source_refs": list(row.source_refs or factor.get("source_refs") or []),
            "quality_summary": health.get("quality_summary"),
            "next_meeting": path.get("next_meeting"),
            "year_end": path.get("year_end"),
            "repricing": factor.get("repricing"),
            "latest_attempt": dict(attempt) if attempt else None,
            "coverage_status": "complete" if complete else "partial",
            "status": "available" if health["actionable"] and complete and factor.get("status") == "available" else "degraded",
            "page_layer": "ADS",
        }
    )


def get_fedwatch_factor_history(
    db: Session,
    *,
    meeting_date: str | None,
    limit: int,
    as_of: str,
) -> dict[str, Any]:
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    fetch_limit = min(max(limit * 5, limit), 500)
    statement = (
        select(FedWatchFactor)
        .where(FedWatchFactor.as_of <= cutoff)
        .order_by(FedWatchFactor.as_of.desc(), FedWatchFactor.created_at.desc())
        .limit(fetch_limit)
    )
    items: list[dict[str, Any]] = []
    for row in db.scalars(statement).all():
        factor = dict(row.payload or {})
        if meeting_date and not _factor_has_meeting(factor, meeting_date):
            continue
        health = factor.get("health") if isinstance(factor.get("health"), dict) else {}
        path = factor.get("market_implied_path") if isinstance(factor.get("market_implied_path"), dict) else {}
        items.append(
            {
                "snapshot_id": row.snapshot_id,
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "status": health.get("status") or factor.get("status") or "available",
                "quality_summary": health.get("quality_summary"),
                "next_meeting": path.get("next_meeting"),
                "year_end": path.get("year_end"),
                "repricing": factor.get("repricing"),
                "meetings": list(path.get("meetings") or []),
                "source_refs": list(row.source_refs or factor.get("source_refs") or []),
            }
        )
        if len(items) >= limit:
            break
    return sanitize_page_payload({"as_of": as_of, "items": items, "count": len(items), "page_layer": "ADS"})


def _factor_has_meeting(factor: dict[str, Any], meeting_date: str) -> bool:
    path = factor.get("market_implied_path") if isinstance(factor.get("market_implied_path"), dict) else {}
    return any(
        isinstance(item, dict) and str(item.get("meeting_date") or item.get("date") or "") == meeting_date
        for item in path.get("meetings") or []
    )


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _missing_view(as_of: str, allowed_staleness_seconds: int) -> dict[str, Any]:
    health = {
        "status": "missing",
        "reason": "dws_factor_unavailable",
        "actionable": False,
        "evaluated_at": as_of,
        "allowed_staleness_seconds": allowed_staleness_seconds,
        "quality_summary": None,
    }
    return sanitize_page_payload(
        {
            "schema_version": "fedwatch_page_view.v1",
            "as_of": None,
            "evaluated_at": as_of,
            "snapshot_id": None,
            "source_health": health,
            "factor": {"status": "unavailable", "health": health, "market_implied_path": {}, "repricing": None},
            "source_refs": [],
            "quality_summary": None,
            "next_meeting": None,
            "year_end": None,
            "repricing": None,
            "latest_attempt": None,
            "coverage_status": "partial",
            "status": "unavailable",
            "reason": "dws_factor_unavailable",
            "page_layer": "ADS",
        }
    )
