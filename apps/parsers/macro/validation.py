"""Validate parsed observations before they enter features or database tables."""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from urllib.parse import urlsplit

from apps.parsers.macro.models import MacroPoint


def validate_macro_points(
    points: list[MacroPoint], *, cutoff: datetime, source_refs: list[dict] | None = None,
) -> tuple[list[MacroPoint], dict]:
    """Keep valid history; reject malformed observations and ambiguous revisions.

    Freshness is a downstream eligibility decision. A historical observation
    remains a valid database record, with its original date and retrieval time.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("macro validation cutoff must include a timezone")
    refs = source_refs or []
    grouped: dict[tuple[str, str, str], list[tuple[MacroPoint, datetime]]] = {}
    rejected = []

    def reject(point: MacroPoint, reasons: list[str]) -> None:
        rejected.append({"symbol": point.symbol, "source": point.source,
                         "observation_date": point.date, "raw_path": point.raw_path,
                         "reason_codes": sorted(set(reasons))})

    for point in points:
        reasons = []
        scheduled_event = isinstance(point.symbol, str) and point.symbol.startswith("NEWS_EVENT:")
        try:
            finite = type(point.value) in (int, float) and isfinite(point.value)
        except OverflowError:
            finite = False
        if not finite:
            reasons.append("non_finite_or_invalid_value")
        if not all(isinstance(value, str) and value.strip()
                   for value in (point.symbol, point.source, point.source_url, point.raw_path)):
            reasons.append("missing_source_lineage")
        try:
            url = urlsplit(point.source_url)
            local_calendar_ref = (scheduled_event and point.source == "jin10_mcp"
                                  and point.source_url == point.raw_path
                                  and point.raw_path.startswith(("raw/", "storage/raw/"))
                                  and ".." not in point.raw_path.split("/"))
            if not local_calendar_ref and (url.scheme not in {"http", "https"} or not url.netloc):
                reasons.append("invalid_source_url")
        except (TypeError, ValueError):
            reasons.append("invalid_source_url")
        try:
            if scheduled_event:
                event_time = datetime.fromisoformat(point.date.replace("Z", "+00:00"))
                if event_time.tzinfo is None or event_time.utcoffset() is None:
                    reasons.append("event_timezone_missing")
                observed = event_time.date()
            else:
                observed = date.fromisoformat(point.date)
            if not scheduled_event and observed > cutoff.date():
                reasons.append("future_observation_date")
        except (TypeError, ValueError):
            reasons.append("invalid_observation_date")
        retrieved = None
        try:
            retrieved = datetime.fromisoformat(point.retrieved_at.replace("Z", "+00:00"))
            if retrieved.tzinfo is None or retrieved.utcoffset() is None:
                reasons.append("retrieval_timezone_missing")
            elif retrieved > cutoff:
                reasons.append("future_retrieval_time")
        except (AttributeError, TypeError, ValueError):
            reasons.append("invalid_retrieval_time")
        matching_refs = [ref for ref in refs if isinstance(ref, dict)
                         and ref.get("source") == point.source
                         and (not ref.get("symbol") or ref["symbol"] == point.symbol)
                         and (not ref.get("raw_path") or ref["raw_path"] == point.raw_path)]
        if any(str(ref.get(key, "")).lower() in {"failed", "error", "missing", "unavailable", "invalid"}
               for ref in matching_refs for key in ("status", "collector_status", "collection_status")):
            reasons.append("source_collection_failed")
        if reasons:
            reject(point, reasons)
        else:
            grouped.setdefault((point.source, point.symbol, point.date), []).append((point, retrieved))

    accepted = []
    duplicate_count = 0
    for candidates in grouped.values():
        latest = max(retrieved for _, retrieved in candidates)
        latest_points = [point for point, retrieved in candidates if retrieved == latest]
        if len({point.value for point in latest_points}) > 1:
            for point, _ in candidates:
                reject(point, ["conflicting_same_time_observation"])
            continue
        # Stable selection when multiple collectors emit the same observation.
        accepted.append(min(latest_points, key=lambda point: (point.raw_path, point.source_url)))
        duplicate_count += len(candidates) - 1

    accepted.sort(key=lambda point: (point.source, point.symbol, point.date, point.raw_path))
    return accepted, {
        "schema_version": "macro_point_validation.v1", "cutoff": cutoff.isoformat(),
        "input_count": len(points), "accepted_count": len(accepted),
        "rejected_count": len(rejected), "duplicate_count": duplicate_count,
        "rejections": rejected,
    }
