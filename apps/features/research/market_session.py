"""Conservative research session gate; exchange clocks remain instrument-specific."""

from datetime import datetime
from zoneinfo import ZoneInfo

from apps.features.research.sessions import build_session_quality


def resolve_market_session(as_of):
    try:
        if not isinstance(as_of, str):
            raise ValueError("invalid clock")
        t = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError("timezone missing")
        local = t.astimezone(ZoneInfo("America/New_York"))
    except (TypeError, ValueError):
        return {"state": "UNKNOWN", "new_intraday_confirmation_allowed": False, "reason": "invalid_clock"}
    quality = build_session_quality({"trade_date": local.date().isoformat()})
    h = local.hour + local.minute / 60
    if local.weekday() == 5 or local.weekday() == 6 and h < 18 or local.weekday() == 4 and h >= 17:
        state, reason = "CLOSED", "weekend_closure"
    elif local.weekday() == 6 and h >= 18:
        state, reason = "OPEN", "Sunday_reopen;provider_hours_must_also_match"
    elif not quality["calendar_known"]:
        state, reason = "UNKNOWN", "calendar_missing"
    elif quality["session_class"] == "HOLIDAY":
        state, reason = "HOLIDAY", "holiday_hours_require_instrument_calendar"
    elif quality["session_class"] == "EARLY_CLOSE":
        state, reason = "EARLY_CLOSE", "early_close_hours_require_instrument_calendar"
    elif 17 <= h < 18:
        state, reason = "MAINTENANCE", "conservative_US_daily_maintenance_window"
    else:
        state, reason = "OPEN", "regular_weekday_research_window;provider_hours_must_also_match"
    return {
        "state": state,
        "new_intraday_confirmation_allowed": state == "OPEN",
        "reason": reason,
        "as_of": as_of,
        "timezone": "America/New_York",
        "scope": "conservative_cross_asset_research_gate",
        "source_refs": quality.get("source_refs", []),
    }
