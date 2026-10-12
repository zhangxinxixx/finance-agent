from __future__ import annotations

import pytest

from apps.features.research.levels import build_key_levels


def _snapshot(
    *, as_of: str = "2026-09-08", technical_levels: list[dict] | None = None, options: dict | None = None
) -> dict:
    return {
        "trade_date": as_of,
        "technical": {
            "data": {
                "as_of": as_of,
                "ma20": 100.0,
                "source_refs": [{"source": "spot"}],
                "key_levels": technical_levels or [],
            }
        },
        "options": {"data": options or {}},
    }


def test_spot_levels_only_come_from_technical_and_ma20() -> None:
    result = build_key_levels(
        _snapshot(
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-05",
                    "status": "not_broken",
                }
            ],
            options={"support_resistance": {"support": [{"strike": 90}], "resistance": [{"strike": 110}]}},
        )
    )
    assert {item["instrument"] for item in result[:2]} == {"XAUUSD spot"}
    assert {item["source_type"] for item in result[:2]} == {"technical.key_levels", "technical.ma20"}
    assert all(item["price"] != 90 for item in result if item["instrument"] == "XAUUSD spot")
    assert any(item["instrument"] == "GC futures" for item in result)


def test_reversal_requires_prior_level_and_progressed_window_not_same_day_rerun() -> None:
    initial = build_key_levels(
        _snapshot(
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-05",
                    "evaluation_date": "2026-09-08",
                    "status": "not_broken",
                }
            ]
        )
    )
    same_day = build_key_levels(
        _snapshot(
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-05",
                    "evaluation_date": "2026-09-08",
                    "status": "broken_on_close",
                }
            ]
        ),
        initial,
    )
    same_day_level = next(
        item for item in same_day if item["price"] == 95 and item["source_type"] == "technical.key_levels"
    )
    assert same_day_level["role"] == "support"
    assert same_day_level["eligible_for_target"] is False
    progressed = build_key_levels(
        _snapshot(
            as_of="2026-09-09",
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-06",
                    "evaluation_date": "2026-09-09",
                    "status": "broken_on_close",
                }
            ],
        ),
        same_day,
    )
    level = next(item for item in progressed if item["price"] == 95 and item["source_type"] == "technical.key_levels")
    assert level["role"] == "resistance"
    assert level["previous_role"] == "support"

    repeated = build_key_levels(
        _snapshot(
            as_of="2026-09-10",
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-07",
                    "evaluation_date": "2026-09-10",
                    "status": "broken_on_close",
                }
            ],
        ),
        progressed,
    )
    assert (
        next(item for item in repeated if item["price"] == 95 and item["source_type"] == "technical.key_levels")["role"]
        == "resistance"
    )


def test_missing_rolling_level_is_retained_as_stale() -> None:
    previous = build_key_levels(
        _snapshot(
            technical_levels=[
                {
                    "price": 95,
                    "kind": "prior_5d_low",
                    "date": "2026-09-05",
                    "window_end": "2026-09-05",
                    "status": "not_broken",
                }
            ]
        )
    )
    current = build_key_levels(
        _snapshot(
            as_of="2026-09-09",
            technical_levels=[
                {
                    "price": 96,
                    "kind": "prior_5d_low",
                    "date": "2026-09-08",
                    "window_end": "2026-09-08",
                    "status": "not_broken",
                }
            ],
        ),
        previous,
    )
    old = next(item for item in current if item["price"] == 95)
    assert old["status"] == "Stale"
    assert old["eligible_for_target"] is False


def test_previous_invalidated_level_stays_invalidated_when_removed() -> None:
    previous = build_key_levels(
        _snapshot(technical_levels=[{"price": 95, "kind": "prior_5d_low", "status": "invalidated"}])
    )
    current = build_key_levels(_snapshot(), previous)
    old = next(item for item in current if item["price"] == 95)
    assert old["status"] == "Invalidated"
    assert old["eligible_for_target"] is False


def test_cme_coordinates_expiry_and_max_pain_are_fail_closed() -> None:
    options = {
        "trade_date": "2026-09-04",
        "data_source": {"report_date": "2026-09-04", "status": "PRELIM"},
        "parameters": {
            "forward_by_expiry": {"OCT26": {"f_value": 110}},
        },
        "audit": {
            "black76_audit": {"OCT26": {"expiry_date": "2026-09-24", "expiry_source": "estimated_from_delivery_month"}}
        },
        "wall_scores": [{"strike": 110, "side": "CALL", "expiry": "OCT26", "wall_score": 0.8}],
        "max_pain": [
            {"strike": 100, "expiry": "SEP26", "expiry_date": "2026-09-01", "expiry_source": "cme_contract_calendar"}
        ],
    }
    result = build_key_levels(
        {**_snapshot(as_of="2026-09-08", options=options), "source_refs": [{"source": "CME Daily Bulletin"}]}
    )
    wall = next(item for item in result if item["source_type"] == "cme.options.wall")
    expired = next(item for item in result if item["source_type"] == "cme.options.max_pain")
    assert wall["instrument"] == "GC futures"
    assert wall["status"] == "Conditional"
    assert wall["source_date"] == "2026-09-04"
    assert expired["status"] == "Invalidated"
    assert expired["is_target"] is False


def test_analysis_date_controls_expiry_and_missing_cme_refs_block_target() -> None:
    options = {
        "data_source": {"report_date": "2026-09-04"},
        "parameters": {
            "forward_by_expiry": {"SEP26": {"f_value": 100}},
            "expiry_sources": {"SEP26": {"expiry_date": "2026-09-08", "expiry_source": "cme_contract_calendar"}},
        },
        "wall_scores": [{"strike": 100, "side": "PUT", "expiry": "SEP26"}],
    }
    result = build_key_levels(_snapshot(as_of="2026-09-08", options=options))
    level = next(item for item in result if item["source_type"] == "cme.options.wall")
    assert level["status"] == "Invalidated"
    assert level["is_target"] is False

    future = {
        **options,
        "parameters": {
            "forward_by_expiry": {"OCT26": {"f_value": 100}},
            "expiry_sources": {"OCT26": {"expiry_date": "2026-09-24", "expiry_source": "cme_contract_calendar"}},
        },
        "wall_scores": [{"strike": 100, "side": "PUT", "expiry": "OCT26"}],
    }
    level = next(
        item
        for item in build_key_levels(_snapshot(as_of="2026-09-08", options=future))
        if item["source_type"] == "cme.options.wall"
    )
    assert level["status"] == "Conditional"
    assert level["is_target"] is False


def test_future_technical_dates_are_conditional_and_not_targets() -> None:
    result = build_key_levels(
        _snapshot(
            technical_levels=[
                {"price": 95, "kind": "prior_5d_low", "date": "2030-01-01", "window_end": "2030-01-01"},
                {"price": 96, "kind": "prior_5d_high", "date": "2026-09-05", "window_end": "2030-01-01"},
            ]
        )
    )
    levels = [item for item in result if item["source_type"] == "technical.key_levels"]
    assert len(levels) == 2
    assert all(item["status"] == "Conditional" for item in levels)
    assert all(item["eligible_for_target"] is False and item["is_target"] is False for item in levels)


@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [("stale", "Stale"), ("invalidated", "Invalidated"), ("expired", "Invalidated")],
)
def test_upstream_lifecycle_statuses_fail_closed(
    upstream_status: str,
    expected_status: str,
) -> None:
    technical = _snapshot(
        technical_levels=[
            {"price": 95, "kind": "prior_5d_low", "status": upstream_status},
        ]
    )
    technical_level = next(
        item for item in build_key_levels(technical) if item["source_type"] == "technical.key_levels"
    )
    assert technical_level["status"] == expected_status
    assert technical_level["eligible_for_target"] is False
    assert technical_level["is_target"] is False

    options = {
        "data_source": {"report_date": "2026-09-08", "status": upstream_status},
        "parameters": {
            "expiry_sources": {"OCT26": {"expiry_date": "2026-10-24", "expiry_source": "cme_contract_calendar"}}
        },
        "wall_scores": [{"strike": 110, "side": "CALL", "expiry": "OCT26"}],
    }
    cme_level = next(
        item for item in build_key_levels(_snapshot(options=options)) if item["source_type"] == "cme.options.wall"
    )
    assert cme_level["status"] == expected_status
    assert cme_level["eligible_for_target"] is False
    assert cme_level["is_target"] is False


def test_future_cme_report_date_is_conditional_and_not_a_target() -> None:
    options = {
        "data_source": {"report_date": "2030-01-01", "status": "FINAL"},
        "parameters": {
            "expiry_sources": {"OCT26": {"expiry_date": "2030-10-24", "expiry_source": "cme_contract_calendar"}}
        },
        "wall_scores": [{"strike": 110, "side": "CALL", "expiry": "OCT26"}],
    }
    level = next(
        item for item in build_key_levels(_snapshot(options=options)) if item["source_type"] == "cme.options.wall"
    )
    assert level["source_date"] == "2030-01-01"
    assert level["status"] == "Conditional"
    assert level["eligible_for_target"] is False
    assert level["is_target"] is False


def test_section_lifecycle_status_is_applied_to_spot_and_cme_levels() -> None:
    snapshot = _snapshot(
        technical_levels=[{"price": 95, "kind": "prior_5d_low"}],
        options={
            "data_source": {"report_date": "2026-09-08", "status": "FINAL"},
            "parameters": {
                "expiry_sources": {"OCT26": {"expiry_date": "2026-10-24", "expiry_source": "cme_contract_calendar"}}
            },
            "wall_scores": [{"strike": 110, "side": "CALL", "expiry": "OCT26"}],
        },
    )
    snapshot["technical"]["status"] = "stale"
    snapshot["options"]["status"] = "expired"
    result = build_key_levels(snapshot)
    spot = next(item for item in result if item["source_type"] == "technical.key_levels")
    cme = next(item for item in result if item["source_type"] == "cme.options.wall")
    assert spot["status"] == "Stale"
    assert cme["status"] == "Invalidated"
    assert all(item["eligible_for_target"] is False for item in (spot, cme))


def test_holiday_confidence_is_scoped_to_the_observed_holiday_date() -> None:
    result = build_key_levels(
        _snapshot(
            as_of="2026-09-08",
            technical_levels=[
                {"price": 95, "kind": "prior_5d_low", "date": "2026-09-07"},
                {"price": 96, "kind": "prior_20d_low", "date": "2026-09-01"},
            ],
        ),
        session_quality={
            "session_class": "HOLIDAY",
            "trade_date": "2026-09-08",
            "calendar_entry": {"date": "2026-09-07"},
            "otc_daily_close": {"observation_date": "2026-09-07", "status": "available"},
            "confidence_multiplier": 0.7,
        },
    )
    holiday_level = next(item for item in result if item["price"] == 95)
    older_level = next(item for item in result if item["price"] == 96)
    ma20 = next(item for item in result if item["source_type"] == "technical.ma20")
    assert holiday_level["confidence"] == round(holiday_level["base_confidence"] * 0.7, 6)
    assert holiday_level["session_confidence_applied"] is True
    assert older_level["confidence"] == 0.65
    assert "session_confidence_applied" not in older_level
    assert "session_confidence_applied" not in ma20


def test_holiday_confidence_requires_explicit_spot_source_date_and_skips_cme() -> None:
    result = build_key_levels(
        _snapshot(
            as_of="2026-09-08",
            technical_levels=[
                # The window ended on the holiday, but the level's actual
                # extreme date is unavailable.  It must remain undiscounted.
                {"price": 95, "kind": "prior_5d_low", "window_end": "2026-09-07"},
                {"price": 96, "kind": "prior_20d_low", "evaluation_date": "2026-09-07"},
            ],
            options={
                "data_source": {"report_date": "2026-09-07", "status": "FINAL"},
                "parameters": {
                    "expiry_sources": {
                        "OCT26": {"expiry_date": "2026-10-24", "expiry_source": "cme_contract_calendar"}
                    }
                },
                "wall_scores": [{"strike": 110, "side": "CALL", "expiry": "OCT26"}],
            },
        ),
        session_quality={
            "session_class": "HOLIDAY",
            "trade_date": "2026-09-08",
            "calendar_entry": {"date": "2026-09-07"},
            "otc_daily_close": {"observation_date": "2026-09-07", "status": "available"},
            "confidence_multiplier": 0.7,
        },
    )

    prior_5d = next(item for item in result if item["price"] == 95)
    prior_20d = next(item for item in result if item["price"] == 96)
    ma20 = next(item for item in result if item["source_type"] == "technical.ma20")
    cme = next(item for item in result if item["source_type"] == "cme.options.wall")

    for level in (prior_5d, prior_20d, ma20, cme):
        assert "session_confidence_applied" not in level
        assert "confidence_multiplier" not in level

    assert prior_5d["source_date"] is None
    assert prior_5d["source_date_explicit"] is False
    assert prior_20d["source_date"] is None
    assert prior_20d["source_date_explicit"] is False
    # MA20 has a calculation date, but no single-session extreme date.
    assert ma20["source_date"] == "2026-09-08"
    assert ma20["source_date_explicit"] is False
    assert cme["instrument"] == "GC futures"
