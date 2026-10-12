"""Versioned market-session quality facts for the gold research snapshot.

The session layer describes calendar and observation quality.  It deliberately
keeps CME settlement availability separate from OTC spot observations: a CME
holiday is not evidence that an OTC quote or daily close is unavailable.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

SESSION_SCHEMA_VERSION = "research_session.v1"
SESSION_CALENDAR_VERSION = "cme_otc_session_calendar.v1"
HOLIDAY_CONFIDENCE_MULTIPLIER = 0.7
CME_LABOR_DAY_2026_REFERENCE = (
    "https://www.cmegroup.com/tools-information/holiday-calendar/files/2026/labor-day-holiday-settlement-times-2026.pdf"
)

_SESSION_CLASSES = {"NORMAL", "HOLIDAY", "EARLY_CLOSE", "PARTIAL", "LOW_LIQUIDITY"}
_LIQUIDITY_CLASSES = {"NORMAL", "LOW_LIQUIDITY", "UNKNOWN"}
_RULE_REFERENCE = {
    "source": "session_calendar_rule",
    "reference": f"{SESSION_CALENDAR_VERSION}:us_observed_holidays",
}


def build_session_quality(
    snapshot: Mapping[str, Any] | None,
    calendar: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a traceable session classification from a snapshot.

    ``calendar=None`` uses the versioned built-in US observed-holiday rules.
    Passing an empty or malformed calendar intentionally produces ``PARTIAL``;
    callers must not infer a normal session when the supplied calendar is
    missing.  Calendar entries describe CME settlement only and never erase an
    OTC observation supplied by the snapshot.
    """

    source_snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    trade_date = _first_date(
        source_snapshot.get("trade_date"),
        source_snapshot.get("analysis_date"),
        source_snapshot.get("analysis_time"),
    )
    trade_date_value = date.fromisoformat(trade_date) if trade_date else None
    supplied_calendar = calendar
    if supplied_calendar is None and "session_calendar" in source_snapshot:
        supplied_calendar = source_snapshot.get("session_calendar")
    calendar_state = _normalise_calendar(supplied_calendar, trade_date)
    entry = calendar_state["entries"].get(trade_date) if trade_date else None
    calendar_known = bool(calendar_state["available"] and (entry or calendar_state["rule_based"]))

    explicit = _explicit_session_fields(source_snapshot)
    entry_class = _session_class(entry.get("session_class")) if isinstance(entry, Mapping) else None
    explicit_class = _session_class(
        explicit.get("session_class") or explicit.get("session_status") or explicit.get("status")
    )
    base_class = explicit_class or entry_class
    day_type = "WEEKEND" if trade_date_value and trade_date_value.weekday() >= 5 else "WEEKDAY"
    if base_class is None and day_type == "WEEKEND":
        base_class = "HOLIDAY"

    if not trade_date or not calendar_state["available"] or not calendar_known:
        session_class = "PARTIAL"
        if day_type == "WEEKEND":
            reason = "calendar_missing_for_weekend_or_unknown_session"
        elif not trade_date:
            reason = "trade_date_missing_or_invalid"
        else:
            reason = "session_calendar_entry_missing"
    elif base_class == "PARTIAL" or explicit.get("status") in {"partial", "unavailable"}:
        session_class = "PARTIAL"
        reason = "upstream_session_quality_partial"
    elif base_class in {"HOLIDAY", "EARLY_CLOSE", "LOW_LIQUIDITY", "NORMAL"}:
        session_class = base_class
        reason = str((entry or {}).get("reason") or explicit.get("reason") or "calendar_and_snapshot_checked")
    else:
        session_class = "NORMAL"
        reason = "calendar_and_snapshot_checked"

    liquidity_class = _liquidity_class(explicit.get("liquidity_class") or explicit.get("liquidity_status"))
    if explicit.get("low_liquidity") is True or liquidity_class == "LOW_LIQUIDITY":
        liquidity_class = "LOW_LIQUIDITY"
    elif session_class == "LOW_LIQUIDITY":
        liquidity_class = "LOW_LIQUIDITY"
    elif liquidity_class is None:
        liquidity_class = "UNKNOWN"

    otc = _otc_observation(source_snapshot, trade_date)
    cme = _cme_settlement(source_snapshot, trade_date, entry)
    if session_class == "HOLIDAY" and day_type == "WEEKEND":
        day_type = "WEEKEND"
    elif session_class == "HOLIDAY":
        day_type = "HOLIDAY"

    calendar_refs = _refs(calendar_state.get("source_refs"))
    entry_refs = _refs(entry.get("source_refs")) if isinstance(entry, Mapping) else []
    source_refs = _dedupe_refs(
        [*calendar_refs, *entry_refs, *_refs(otc.get("source_refs")), *_refs(cme.get("source_refs"))]
    )
    if session_class == "HOLIDAY" and trade_date == "2026-09-07":
        # Keep the official CME Labor Day document visible even when a caller
        # supplied a compact calendar entry without copying its source refs.
        source_refs = _dedupe_refs(
            [
                *source_refs,
                {"source": "CME holiday calendar 2026", "reference": CME_LABOR_DAY_2026_REFERENCE},
            ]
        )

    limitations: list[str] = []
    if not calendar_state["available"]:
        limitations.append("session calendar unavailable; session class is PARTIAL")
    elif not calendar_known:
        limitations.append("calendar has no entry/rule for this date; normal session not assumed")
    if session_class == "HOLIDAY" and cme.get("status") == "unavailable":
        limitations.append("CME settlement is not published for this holiday")
    if otc.get("status") != "available":
        limitations.append("OTC daily close/quote status is not fully verified for this date")
    if liquidity_class == "LOW_LIQUIDITY":
        limitations.append("low liquidity is an observed or explicitly supplied condition")

    multiplier = HOLIDAY_CONFIDENCE_MULTIPLIER if session_class == "HOLIDAY" else 1.0
    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "calendar_version": calendar_state.get("version"),
        "trade_date": trade_date,
        "session_class": session_class,
        "session_status": session_class,
        "status": session_class,
        "base_session_class": base_class or session_class,
        "day_type": day_type,
        "reason": reason,
        "calendar_available": bool(calendar_state["available"]),
        "calendar_known": calendar_known,
        "calendar_entry": deepcopy(entry) if isinstance(entry, Mapping) else None,
        "otc_daily_close": otc,
        "otc": otc,
        "cme_settlement": cme,
        "cme": cme,
        "liquidity_class": liquidity_class,
        "confidence": 0.9 if calendar_known else 0.3,
        "confidence_multiplier": multiplier,
        "confidence_note": (
            "holiday level confidence is multiplied by 0.7; this is a rule coefficient, not a statistical probability"
            if multiplier != 1.0
            else "session confidence is a calendar/data-quality rule, not a statistical probability"
        ),
        "limitations": limitations,
        "source_refs": source_refs,
    }


def _normalise_calendar(
    calendar: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    trade_date: str | None,
) -> dict[str, Any]:
    if calendar is None:
        years = {date.fromisoformat(trade_date).year} if trade_date else set()
        if trade_date:
            current_year = date.fromisoformat(trade_date).year
            years.update({current_year - 1, current_year + 1})
        entries: dict[str, dict[str, Any]] = {}
        refs = [_RULE_REFERENCE]
        for year in years:
            generated, generated_refs = _default_entries(year)
            entries.update(generated)
            refs.extend(generated_refs)
        return {
            "version": SESSION_CALENDAR_VERSION,
            "available": bool(trade_date),
            "rule_based": True,
            "entries": entries,
            "source_refs": _dedupe_refs(refs),
        }

    if isinstance(calendar, Mapping):
        version = str(calendar.get("version") or calendar.get("schema_version") or "provided_calendar")
        raw_entries = calendar.get("entries", calendar.get("holidays"))
        default_rules = bool(calendar.get("rule_based"))
        top_refs = _refs(calendar.get("source_refs"))
    elif isinstance(calendar, Sequence) and not isinstance(calendar, (str, bytes, bytearray)):
        version = "provided_calendar"
        raw_entries = calendar
        default_rules = False
        top_refs = []
    else:
        return {"version": "missing", "available": False, "rule_based": False, "entries": {}, "source_refs": []}

    entries: dict[str, dict[str, Any]] = {}
    if isinstance(raw_entries, Mapping):
        iterable = [
            {"date": key, **value} if isinstance(value, Mapping) else {"date": key, "session_class": value}
            for key, value in raw_entries.items()
        ]
    elif isinstance(raw_entries, Sequence) and not isinstance(raw_entries, (str, bytes, bytearray)):
        iterable = [dict(item) for item in raw_entries if isinstance(item, Mapping)]
    else:
        iterable = []
    refs = list(top_refs)
    for item in iterable:
        entry_date = _first_date(item.get("date"), item.get("trade_date"))
        if not entry_date:
            continue
        normalized = deepcopy(item)
        normalized["date"] = entry_date
        normalized["session_class"] = _session_class(item.get("session_class") or item.get("status")) or "PARTIAL"
        normalized["source_refs"] = _refs(item.get("source_refs"))
        refs.extend(normalized["source_refs"])
        entries[entry_date] = normalized
    return {
        "version": version,
        "available": bool(entries) or default_rules,
        "rule_based": default_rules,
        "entries": entries,
        "source_refs": _dedupe_refs(refs),
    }


def _default_entries(year: int) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Generate only versioned observed US holiday rules.

    Early-close dates are intentionally not guessed here; callers must provide
    them as calendar entries because product-specific CME schedules differ.
    """

    holidays: list[tuple[date, str]] = [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
        (_last_weekday(year, 5, 0), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day"),
        (date(year, 12, 25), "Christmas Day"),
    ]
    entries: dict[str, dict[str, Any]] = {}
    refs: list[dict[str, Any]] = []
    for holiday, name in holidays:
        observed = _observed_date(holiday)
        entry = {
            "date": observed.isoformat(),
            "session_class": "HOLIDAY",
            "holiday_name": name,
            "cme_settlement_status": "unavailable",
            "otc_quote_expected": True,
            "reason": f"CME observed holiday: {name}",
            "source_refs": [_RULE_REFERENCE],
        }
        if observed == date(2026, 9, 7):
            entry["source_refs"] = [
                *_refs(entry["source_refs"]),
                {"source": "CME holiday calendar 2026", "reference": CME_LABOR_DAY_2026_REFERENCE},
            ]
        entries[observed.isoformat()] = entry
        refs.extend(entry["source_refs"])
    return entries, _dedupe_refs(refs)


def _explicit_session_fields(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("session_quality", "session"):
        value = snapshot.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    direct = {
        key: snapshot[key]
        for key in (
            "session_class",
            "session_status",
            "status",
            "liquidity_class",
            "liquidity_status",
            "low_liquidity",
            "reason",
        )
        if key in snapshot
    }
    return direct


def _otc_observation(snapshot: Mapping[str, Any], trade_date: str | None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    technical_section = snapshot.get("technical")
    technical = _section_data(technical_section)
    if technical:
        technical_refs = _refs(technical_section.get("source_refs")) if isinstance(technical_section, Mapping) else []
        candidates.append(
            {
                "observation_date": technical.get("as_of") or technical.get("observation_date"),
                "value": technical.get("price") or technical.get("close"),
                "source_refs": [*technical_refs, *_refs(technical.get("source_refs"))],
                "source": "technical",
            }
        )
    research = snapshot.get("daily_research")
    if isinstance(research, Mapping):
        passport = research.get("passport")
        if isinstance(passport, Sequence) and not isinstance(passport, (str, bytes, bytearray)):
            for row in passport:
                if isinstance(row, Mapping) and str(row.get("symbol")) in {"XAUUSD_DAILY", "XAUUSD"}:
                    candidates.append(
                        {
                            "observation_date": row.get("observation_date"),
                            "value": row.get("value"),
                            "source_refs": row.get("source_refs"),
                            "source": row.get("label") or "daily_research.passport",
                        }
                    )
    stale: dict[str, Any] | None = None
    future: dict[str, Any] | None = None
    for candidate in candidates:
        observed = _first_date(candidate.get("observation_date"))
        value = _number(candidate.get("value"))
        if not observed or value is None:
            continue
        refs = _refs(candidate.get("source_refs"))
        if trade_date and observed == trade_date:
            return {
                "status": "available",
                "observation_date": observed,
                "value": value,
                "source": candidate.get("source"),
                "source_refs": refs,
            }
        if trade_date and observed < trade_date and (stale is None or observed > stale.get("observation_date", "")):
            stale = {
                "status": "stale",
                "observation_date": observed,
                "value": value,
                "source": candidate.get("source"),
                "source_refs": refs,
            }
        elif trade_date and observed > trade_date and future is None:
            future = {
                "status": "unavailable",
                "observation_date": observed,
                "value": None,
                "source": candidate.get("source"),
                "source_refs": refs,
                "reason": "future_otc_observation",
            }
    if stale:
        stale["reason"] = "no_same_day_otc_daily_observation"
        return stale
    if future:
        return future
    return {
        "status": "unavailable",
        "observation_date": None,
        "value": None,
        "source": None,
        "source_refs": [],
        "reason": "otc_daily_observation_missing",
    }


def _cme_settlement(
    snapshot: Mapping[str, Any], trade_date: str | None, entry: Mapping[str, Any] | None
) -> dict[str, Any]:
    options_section = snapshot.get("options")
    options = _section_data(options_section)
    entry_status = str((entry or {}).get("cme_settlement_status") or "").lower()
    entry_available = (entry or {}).get("cme_settlement_available")
    outer_refs = _refs(options_section.get("source_refs")) if isinstance(options_section, Mapping) else []
    data_source = options.get("data_source") if isinstance(options.get("data_source"), Mapping) else {}
    refs = [*outer_refs, *_refs(options.get("source_refs")), *_refs(data_source.get("source_refs"))]
    report_date = _first_date(data_source.get("report_date"), options.get("report_date"))
    settlement_present = any(
        key in options for key in ("settlement", "settlements", "settlement_price", "settlement_prices")
    )
    if entry_status in {"unavailable", "not_published", "closed", "holiday"} or entry_available is False:
        return {
            "status": "unavailable",
            "available": False,
            "report_date": report_date,
            "reason": (entry or {}).get("reason") or "cme_settlement_not_published",
            "source_refs": refs,
        }
    if entry_available is True and settlement_present and report_date == trade_date:
        return {"status": "available", "available": True, "report_date": report_date, "source_refs": refs}
    return {
        "status": "unknown",
        "available": False,
        "report_date": report_date,
        "reason": "cme_settlement_observation_not_present_in_snapshot",
        "source_refs": refs,
    }


def _section_data(section: Any) -> dict[str, Any]:
    if not isinstance(section, Mapping):
        return {}
    data = section.get("data")
    return dict(data) if isinstance(data, Mapping) else dict(section)


def _session_class(value: Any) -> str | None:
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {"EARLYCLOSE": "EARLY_CLOSE", "LOWLIQUIDITY": "LOW_LIQUIDITY"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _SESSION_CLASSES else None


def _liquidity_class(value: Any) -> str | None:
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in {"LOW", "LOW_LIQUIDITY", "THIN"}:
        return "LOW_LIQUIDITY"
    if normalized in {"NORMAL", "AVAILABLE"}:
        return "NORMAL"
    if normalized in {"UNKNOWN", "UNAVAILABLE", "PARTIAL"}:
        return "UNKNOWN"
    return None


def _observed_date(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (nth - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return next_month - timedelta(days=(next_month.weekday() - weekday) % 7 + 1)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _first_date(*values: Any) -> str | None:
    for value in values:
        parsed = _date_text(value)
        if parsed:
            return parsed
    return None


def _date_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def _refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _dedupe_refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        marker = repr(sorted(item.items()))
        if marker not in seen:
            seen.add(marker)
            result.append(dict(item))
    return result


__all__ = [
    "CME_LABOR_DAY_2026_REFERENCE",
    "HOLIDAY_CONFIDENCE_MULTIPLIER",
    "SESSION_CALENDAR_VERSION",
    "SESSION_SCHEMA_VERSION",
    "build_session_quality",
]
