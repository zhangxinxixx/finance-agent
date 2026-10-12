"""DWS/ADS economic-calendar read model for browser pages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.page_data_boundary import sanitize_page_payload


_MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
_STALE_AFTER_SECONDS = 48 * 60 * 60
_SNAPSHOT_ASSETS = ("XAUUSD", "GC", "GOLD")


def get_calendar_summary(
    *,
    project_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the newest calendar projection already present in feature data.

    The loader only visits named feature artifacts. It never reads collector
    caches, Raw/parsed files, or source documents.
    """

    root = project_root or _PROJECT_ROOT
    evaluated_at = _aware_utc(now or datetime.now(UTC))
    candidates = [
        candidate
        for path in _feature_paths(root)
        if (candidate := _load_candidate(path)) is not None
    ]
    if not candidates:
        return _unavailable(evaluated_at, reason="dws_calendar_unavailable")

    candidate = max(candidates, key=_candidate_sort_key)
    generated_at = _parse_time(candidate.get("generated_at"))
    age_seconds = int((evaluated_at - generated_at).total_seconds()) if generated_at is not None else None
    stale = age_seconds is None or age_seconds < 0 or age_seconds > _STALE_AFTER_SECONDS
    events = [_project_event(item, now=evaluated_at) for item in candidate.get("events") or [] if isinstance(item, dict)]
    events = [item for item in events if item.get("title") and item.get("pub_time")]
    events.sort(key=_event_sort_key)

    source_status = str(candidate.get("status") or "").strip().lower()
    if source_status in {"blocked", "failed", "error", "unavailable", "invalid"}:
        status = "unavailable"
        reason = str(candidate.get("reason") or "dws_calendar_unavailable")
    elif generated_at is None:
        status = "unavailable"
        reason = "source_timestamp_unavailable"
    elif events:
        status = "stale" if stale else "available"
        reason = "source_stale" if stale else None
    elif source_status in {"empty", "available", "ok"}:
        status = "empty"
        reason = str(candidate.get("reason") or "no_calendar_events")
    else:
        status = "unavailable"
        reason = str(candidate.get("reason") or "dws_calendar_unavailable")

    event_dates = [str(item["event_date"]) for item in events if item.get("event_date")]
    payload = {
        "generated_at": candidate.get("generated_at"),
        "status": status,
        "reason": reason,
        "stats": {
            "total": len(events),
            "upcoming": sum(item.get("release_state") == "upcoming" for item in events),
            "released": sum(item.get("release_state") == "released" for item in events),
            "pending": sum(item.get("release_state") == "pending" for item in events),
            "high_impact": sum(item.get("is_high_impact") is True for item in events),
            "earliest_event_date": min(event_dates) if event_dates else None,
            "latest_event_date": max(event_dates) if event_dates else None,
            "window_start_date": candidate.get("window_start_date"),
            "window_end_date": candidate.get("window_end_date"),
        },
        "freshness": {
            "is_stale": stale,
            "reason": reason or ("fresh" if generated_at is not None else "source_timestamp_unavailable"),
            "age_seconds": age_seconds,
            "stale_after_seconds": _STALE_AFTER_SECONDS,
        },
        "events": events,
        "source_refs": list(candidate.get("source_refs") or []),
        "page_layer": "ADS",
    }
    return sanitize_page_payload(payload)


def _feature_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    news_root = root / "storage" / "features" / "news"
    if news_root.is_dir():
        for filename in ("official_calendar.json", "daily_market_brief.json", "event_candidates.json"):
            paths.extend(news_root.glob(f"*/*/{filename}"))
    snapshot_root = root / "storage" / "features" / "snapshots"
    for asset in _SNAPSHOT_ASSETS:
        asset_root = snapshot_root / asset
        if asset_root.is_dir():
            paths.extend(asset_root.glob("*/*/premarket_snapshot.json"))
    return sorted(set(paths))[-500:]


def _load_candidate(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_ARTIFACT_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    calendar: dict[str, Any] = {}
    brief: dict[str, Any] = {}
    event_rows: list[dict[str, Any]] = []
    if path.name == "premarket_snapshot.json":
        news = payload.get("news") if isinstance(payload.get("news"), dict) else {}
        news_data = news.get("data") if isinstance(news.get("data"), dict) else {}
        calendar = news_data.get("official_calendar") if isinstance(news_data.get("official_calendar"), dict) else {}
        brief = news_data.get("daily_market_brief") if isinstance(news_data.get("daily_market_brief"), dict) else {}
        generated_at = calendar.get("as_of") or brief.get("as_of") or payload.get("snapshot_time")
    elif path.name == "official_calendar.json":
        calendar = payload.get("official_calendar") if isinstance(payload.get("official_calendar"), dict) else payload
        generated_at = calendar.get("as_of") or payload.get("generated_at")
    elif path.name == "daily_market_brief.json":
        brief = payload.get("daily_market_brief") if isinstance(payload.get("daily_market_brief"), dict) else payload
        generated_at = brief.get("as_of") or payload.get("generated_at")
    else:
        raw_events = payload.get("event_candidates") or payload.get("events") or []
        event_rows = [
            dict(item)
            for item in raw_events
            if isinstance(item, dict) and str(item.get("event_status") or "") == "scheduled"
        ]
        generated_at = payload.get("as_of") or payload.get("generated_at")

    calendar_events = [dict(item) for item in calendar.get("events") or [] if isinstance(item, dict)]
    brief_events = [dict(item) for item in brief.get("next_7d_calendar") or [] if isinstance(item, dict)]
    events = _merge_events(calendar_events or event_rows, brief_events)
    if not calendar and not brief and not event_rows:
        return None
    return {
        "generated_at": generated_at,
        "status": calendar.get("status") or brief.get("status") or payload.get("status"),
        "reason": calendar.get("reason") or brief.get("reason") or payload.get("reason"),
        "window_start_date": calendar.get("window_start_date"),
        "window_end_date": calendar.get("window_end_date"),
        "events": events,
        "source_refs": calendar.get("source_refs") or brief.get("source_refs") or payload.get("source_refs") or [],
        "path_key": path.as_posix(),
    }


def _merge_events(primary: list[dict[str, Any]], supplemental: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*primary, *supplemental]:
        key = str(
            item.get("event_id")
            or item.get("id")
            or f"{item.get('title') or item.get('event_name')}:{item.get('event_time') or item.get('start_date')}"
        )
        merged[key] = {**merged.get(key, {}), **item}
    return list(merged.values())


def _project_event(item: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    pub_time = item.get("pub_time") or item.get("event_time") or item.get("start_date")
    parsed_time = _parse_time(pub_time)
    importance = item.get("importance")
    star = item.get("star")
    try:
        star = int(star) if star is not None else None
    except (TypeError, ValueError):
        star = None
    if star is None and isinstance(importance, str):
        star = {"high": 5, "medium": 3, "low": 1}.get(importance.lower())
    release_state = item.get("release_state")
    if release_state not in {"upcoming", "released", "pending"}:
        release_state = "released" if item.get("actual") is not None else "upcoming"
        if item.get("actual") is None and parsed_time is not None and parsed_time <= now:
            release_state = "pending"
    event_date = item.get("event_date") or (str(pub_time)[:10] if pub_time else None)
    impact_summary = item.get("impact_summary") or item.get("expected_impact_path") or item.get("affect_txt")
    return {
        "event_id": item.get("event_id") or item.get("id"),
        "title": item.get("title") or item.get("event_name") or item.get("what_happened"),
        "pub_time": pub_time,
        "star": star,
        "importance": importance,
        "actual": item.get("actual"),
        "consensus": item.get("consensus") if "consensus" in item else item.get("expected"),
        "expected": item.get("expected") if "expected" in item else item.get("consensus"),
        "previous": item.get("previous"),
        "affect_txt": item.get("affect_txt"),
        "impact_summary": impact_summary,
        "release_state": release_state,
        "event_date": event_date,
        "is_high_impact": (star >= 4) if star is not None else (importance == "high" if importance else None),
        "verification_status": item.get("verification_status"),
        "source_refs": list(item.get("source_refs") or []),
    }


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[datetime, str]:
    timestamp = _parse_time(candidate.get("generated_at")) or datetime.min.replace(tzinfo=UTC)
    return timestamp, str(candidate.get("path_key") or "")


def _event_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return (0 if item.get("release_state") == "upcoming" else 1, str(item.get("pub_time") or ""))


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _unavailable(now: datetime, *, reason: str) -> dict[str, Any]:
    return {
        "generated_at": None,
        "status": "unavailable",
        "reason": reason,
        "stats": {
            "total": 0,
            "upcoming": 0,
            "released": 0,
            "high_impact": 0,
            "earliest_event_date": None,
            "latest_event_date": None,
            "window_start_date": None,
            "window_end_date": None,
        },
        "freshness": {
            "is_stale": False,
            "reason": reason,
            "age_seconds": None,
            "stale_after_seconds": _STALE_AFTER_SECONDS,
            "evaluated_at": now.isoformat(),
        },
        "events": [],
        "source_refs": [],
        "page_layer": "ADS",
    }
