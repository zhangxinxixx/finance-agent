from datetime import date

import pytest

from apps.features.options.bulletin_dates import (
    cme_bulletin_date_eligible,
    eligible_cme_bulletin_dates,
)


@pytest.mark.parametrize(
    ("decision_date", "expected"),
    [
        (date(2026, 8, 7), (date(2026, 8, 7), date(2026, 8, 6))),
        (date(2026, 8, 10), (date(2026, 8, 10), date(2026, 8, 7))),
        (date(2026, 8, 8), (date(2026, 8, 7),)),
        (date(2026, 8, 9), (date(2026, 8, 7),)),
        (date(2026, 9, 7), (date(2026, 9, 4),)),
        (date(2026, 9, 8), (date(2026, 9, 8), date(2026, 9, 4))),
    ],
)
def test_eligible_dates_follow_project_sessions(
    decision_date: date,
    expected: tuple[date, ...],
) -> None:
    assert eligible_cme_bulletin_dates(decision_date) == expected


def test_same_day_and_previous_session_are_eligible_but_t2_and_future_are_not() -> None:
    decision_date = date(2026, 8, 10)

    assert cme_bulletin_date_eligible(date(2026, 8, 10), decision_date) is True
    assert cme_bulletin_date_eligible(date(2026, 8, 7), decision_date) is True
    assert cme_bulletin_date_eligible(date(2026, 8, 6), decision_date) is False
    assert cme_bulletin_date_eligible(date(2026, 8, 11), decision_date) is False
