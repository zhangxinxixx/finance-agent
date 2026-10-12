"""Shared decision-date eligibility for published CME daily bulletins.

Keep the bulletin's own trade date.  T-1 means the preceding session under
the project's existing CME calendar, not one elapsed calendar day.
Publication/cutoff and PRELIM/FINAL checks remain the caller's responsibility.
"""

from datetime import date, timedelta

from apps.features.research.sessions import build_session_quality


CME_BULLETIN_DATE_POLICY = "cme_bulletin_dates.v2"


def eligible_cme_bulletin_dates(decision_date: date) -> tuple[date, ...]:
    def is_session(day: date) -> bool:
        if day.weekday() >= 5:
            return False
        quality = build_session_quality({"trade_date": day.isoformat()})
        return quality["calendar_known"] and quality["session_class"] != "HOLIDAY"

    dates = [decision_date] if is_session(decision_date) else []
    previous = decision_date - timedelta(days=1)
    for _ in range(14):
        if is_session(previous):
            return (*dates, previous)
        previous -= timedelta(days=1)
    return tuple(dates)


def cme_bulletin_date_eligible(bulletin_date: date, decision_date: date) -> bool:
    return bulletin_date in eligible_cme_bulletin_dates(decision_date)
