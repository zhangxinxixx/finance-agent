"""Point-in-time projection of official scheduled calendar events."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from apps.collectors.news.base import RawNewsItem
from apps.parsers.news.fred_calendar import FRED_CALENDAR_SOURCE_KEY

FOMC_SOURCE_KEY = "fomc_calendar"
FOMC_FEED_KEY = "fomc_meetings"
FOMC_EVENT_TYPE = "fomc_meeting"
OFFICIAL_CALENDAR_SOURCE_KEY = "official_calendar"
OFFICIAL_CALENDAR_FEED_KEY = "upcoming_events"
OFFICIAL_CALENDAR_HORIZON_DAYS = 14
_CALENDAR_SOURCE_KEYS = {
    FOMC_SOURCE_KEY,
    FRED_CALENDAR_SOURCE_KEY,
    "bls_calendar",
    "bea_calendar",
    "eia_energy",
}
_CALENDAR_LINEAGE_SOURCE_KEYS = set(_CALENDAR_SOURCE_KEYS)
_CALENDAR_EVENT_TYPES = {
    FOMC_EVENT_TYPE,
    "inflation_release",
    "labor_release",
    "pce_release",
    "gdp_release",
    "energy_inventory_release",
}


def build_official_calendar_snapshot(
    items: Iterable[RawNewsItem | Mapping[str, Any]],
    *,
    as_of: str,
    source_refs: Iterable[Mapping[str, Any]] | None = None,
    horizon_days: int = OFFICIAL_CALENDAR_HORIZON_DAYS,
) -> dict[str, Any]:
    """Project collected official schedules into a date-only future calendar.

    Scheduled meetings are deliberately kept outside the ordinary event
    candidate/reaction path.  The official source publishes meeting dates but
    no clock time, so this projection contains ``start_date``/``end_date`` and
    ``time_precision="day"`` without an ``event_time`` or timezone conversion.
    """

    anchor = _parse_as_of(as_of)
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days < 0:
        raise ValueError("horizon_days must be a non-negative integer")
    window_start = anchor.date()
    window_end = window_start + timedelta(days=horizon_days)

    normalized_refs = _dedupe_refs(
        dict(ref) for ref in (source_refs or ()) if isinstance(ref, Mapping) and _is_calendar_source(ref)
    )
    events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for raw_item in items:
        item = _item_dict(raw_item)
        if not _is_official_calendar_item(item):
            continue
        event = _calendar_event(item)
        if event is None or event["event_id"] in seen_event_ids:
            continue
        start = date.fromisoformat(event["start_date"])
        end = date.fromisoformat(event["end_date"])
        if end < window_start or start > window_end:
            continue
        seen_event_ids.add(event["event_id"])
        events.append(event)
        normalized_refs.extend(ref for ref in event["source_refs"] if ref not in normalized_refs)

    events.sort(key=lambda event: (event["start_date"], event["end_date"], event["event_id"]))
    status = "available" if events else _empty_status(normalized_refs)
    source_keys = sorted(
        {
            str(ref.get("source") or ref.get("source_key"))
            for ref in normalized_refs
            if ref.get("source") or ref.get("source_key")
        }
        | {
            str(event_ref.get("source"))
            for event in events
            for event_ref in event.get("source_refs", [])
            if event_ref.get("source")
        }
    )
    payload: dict[str, Any] = {
        "status": status,
        "source_key": OFFICIAL_CALENDAR_SOURCE_KEY,
        "feed_key": OFFICIAL_CALENDAR_FEED_KEY,
        "source_keys": source_keys,
        "as_of": as_of,
        "window_start_date": window_start.isoformat(),
        "window_end_date": window_end.isoformat(),
        "horizon_days": horizon_days,
        "time_precision": "day",
        "events": events,
        "source_refs": normalized_refs,
    }
    if not events:
        payload["reason"] = "no_upcoming_events_in_window" if status == "empty" else "official_calendar_unavailable"
    return payload


def _item_dict(item: RawNewsItem | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, RawNewsItem):
        return item.to_dict()
    return dict(item) if isinstance(item, Mapping) else {}


def _is_official_calendar_item(item: Mapping[str, Any]) -> bool:
    return (
        str(item.get("source_key") or "") in _CALENDAR_SOURCE_KEYS
        and str(item.get("event_type") or "") in _CALENDAR_EVENT_TYPES
    )


def _is_fomc_item(item: Mapping[str, Any]) -> bool:
    """Backward-compatible alias for callers that only need calendar items."""

    return _is_official_calendar_item(item)


def _calendar_event(item: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_payload = item.get("raw_payload")
    payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
    source_key = str(item.get("source_key") or "")
    event_type = str(item.get("event_type") or "official_macro_release")
    if source_key not in _CALENDAR_SOURCE_KEYS or event_type not in _CALENDAR_EVENT_TYPES:
        return None
    start = _coerce_date(payload.get("start_date") or payload.get("release_date") or item.get("published_at"))
    end = _coerce_date(payload.get("end_date") or start)
    if start is None or end is None or end < start:
        return None
    event_id = str(item.get("duplicate_key") or "").strip()
    if not event_id:
        event_id = f"{source_key}:{event_type}:{start.isoformat()}:{end.isoformat()}"
    source_ref = _event_source_ref(item=item, event_id=event_id)
    date_text = str(payload.get("date_text") or payload.get("release_date") or start.isoformat()).strip() or None
    return {
        "event_id": event_id,
        "event_type": event_type,
        "title": str(item.get("title") or "FOMC Meeting").strip(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "date_text": date_text,
        "is_sep": bool(payload.get("is_sep")) if source_key == FOMC_SOURCE_KEY else False,
        "event_status": "scheduled",
        "verification_status": str(item.get("verification_status") or "official_confirmed"),
        "time_precision": "day",
        "time_status": "unavailable",
        "source_refs": [source_ref],
    }


def _event_source_ref(*, item: Mapping[str, Any], event_id: str) -> dict[str, Any]:
    source_key = str(item.get("source_key") or OFFICIAL_CALENDAR_SOURCE_KEY)
    raw_payload = item.get("raw_payload")
    payload_source_url = raw_payload.get("source_url") if isinstance(raw_payload, Mapping) else None
    source_url = str(payload_source_url or item.get("url") or "").strip() or None
    reference_url = str(item.get("url") or "").strip() or None
    return {
        "source_ref": event_id,
        "source": source_key,
        "source_key": source_key,
        "feed_key": str(item.get("feed_key") or OFFICIAL_CALENDAR_FEED_KEY),
        "source_type": str(item.get("source_type") or "official"),
        "source_url": source_url,
        "reference": reference_url or source_url,
        "raw_path": item.get("raw_path"),
        "parsed_path": item.get("parsed_path"),
        "retrieved_at": item.get("fetched_at"),
    }


def _is_calendar_source(ref: Mapping[str, Any]) -> bool:
    return str(ref.get("source") or ref.get("source_key") or "") in _CALENDAR_LINEAGE_SOURCE_KEYS


def _is_fomc_source(ref: Mapping[str, Any]) -> bool:
    """Backward-compatible alias for source filtering."""

    return _is_calendar_source(ref)


def _empty_status(refs: list[dict[str, Any]]) -> str:
    if not refs:
        return "unavailable"
    statuses = {str(ref.get("status") or "") for ref in refs}
    if statuses & {"failed", "unavailable", "network_blocked", "rate_limited"} and not statuses & {
        "available",
        "ok",
    }:
        return "unavailable"
    return "empty"


def _dedupe_refs(refs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        payload = dict(ref)
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _coerce_date(value: Any) -> date | None:
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


def _parse_as_of(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("as_of must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be an ISO datetime string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
