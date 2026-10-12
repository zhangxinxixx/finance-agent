from __future__ import annotations

from copy import deepcopy

import pytest

from apps.api.services.research_source_health_service import build_research_source_health_view


NOW = "2026-09-17T14:00:00Z"


def _record(source_key: str, **metadata):
    return {
        "source_key": source_key,
        "status": "ok",
        "configured": True,
        "error_message": None,
        "source_metadata": {
            "source_key": source_key,
            "collector_status": "success",
            **metadata,
        },
    }


def _item(record, *, evaluated_at=NOW):
    return build_research_source_health_view([record], evaluated_at=evaluated_at)["items"][0]


def test_old_market_probe_is_reclassified_but_recorded_judgment_is_preserved() -> None:
    record = _record(
        "tv_xauusd",
        ticker="OANDA:XAUUSD",
        retrieved_at="2026-09-14T04:40:21Z",
        actual_latest_date="2026-09-14T04:40:00Z",
        delay_seconds=0,
        source_health="HEALTHY",
        staleness="FRESH_MINUTE_BAR",
        reason="FRESH_MINUTE_BAR",
    )
    original = deepcopy(record)

    item = _item(record)

    assert item["source_health"] == "FAILED"
    assert item["staleness"] == "STALE_CAPTURE"
    assert item["reason"] == "market_probe_stale"
    assert item["recorded_source_health"] == "HEALTHY"
    assert item["recorded_staleness"] == "FRESH_MINUTE_BAR"
    assert item["recorded"]["source_health"] == "HEALTHY"
    assert item["current"]["retrieval_age_seconds"] > 3 * 24 * 60 * 60
    assert record == original


def test_recent_market_probe_and_observation_remain_healthy() -> None:
    item = _item(
        _record(
            "tv_xauusd",
            ticker="OANDA:XAUUSD",
            retrieved_at="2026-09-17T13:59:00Z",
            actual_latest_date="2026-09-17T13:58:00Z",
            delay_seconds=0,
            source_health="HEALTHY",
            staleness="FRESH_MINUTE_BAR",
        )
    )

    assert item["source_health"] == "HEALTHY"
    assert item["staleness"] == "FRESH_MINUTE_BAR"
    assert item["current"]["market_session"]["asset_class"] == "fx_metals"


@pytest.mark.parametrize("delay_seconds", [None, float("nan"), -1])
def test_unknown_or_invalid_provider_delay_is_not_upgraded_to_fresh(delay_seconds: float | None) -> None:
    item = _item(
        _record(
            "tv_xauusd",
            ticker="OANDA:XAUUSD",
            retrieved_at="2026-09-17T13:59:00Z",
            actual_latest_date="2026-09-17T13:58:00Z",
            delay_seconds=delay_seconds,
        )
    )

    assert item["source_health"] == "UNKNOWN"
    assert item["staleness"] == "DELAY_UNVERIFIED"


def test_delayed_energy_without_observation_clock_cannot_be_healthy() -> None:
    item = _item(
        _record(
            "tv_wti",
            ticker="NYMEX:CL1!",
            retrieved_at="2026-09-17T13:59:00Z",
            actual_latest_date=None,
            delay_seconds=600,
            source_health="EXPECTED_STALE",
            staleness="DELAYED_CLOCK_UNVERIFIED",
        )
    )

    assert item["source_health"] == "FAILED"
    assert item["staleness"] == "CLOCK_UNVERIFIED"
    assert item["reason"] == "observation_time_missing_or_timezone_invalid"
    assert item["critical_freshness_failure"] == "ENERGY_INTRADAY"
    assert item["recorded"].get("critical_freshness_failure") is None


def test_monthly_official_observation_stays_healthy_before_next_release() -> None:
    item = _item(
        _record(
            "ism_manufacturing",
            retrieved_at="2026-09-14T04:39:45Z",
            actual_latest_date="2026-08-01",
            official_latest_date="2026-08-01",
            expected_release_time="2026-10-01T10:00:00-04:00",
            source_health="HEALTHY",
            staleness="fresh",
        )
    )

    assert item["source_health"] == "HEALTHY"
    assert item["staleness"] == "RELEASE_NOT_DUE"
    assert item["current"]["release_check"]["status"] == "not_due"


def test_date_only_release_due_is_unknown_until_probe_is_refreshed() -> None:
    item = _item(
        _record(
            "gdp_now",
            retrieved_at="2026-09-14T04:39:28Z",
            actual_latest_date="2026-09-10",
            official_latest_date="2026-09-10",
            expected_release_date="2026-09-16",
            expected_release_time=None,
            source_health="HEALTHY",
            staleness="fresh",
        )
    )

    assert item["source_health"] == "UNKNOWN"
    assert item["staleness"] == "RELEASE_DUE_UNVERIFIED"
    assert item["reason"] == "expected_release_due_probe_not_refreshed"
    assert item["current"]["release_check"]["time_precision"] == "date"


@pytest.mark.parametrize(
    ("actual", "official", "health", "staleness"),
    [
        ("2026-09-18", "2026-09-18", "FAILED", "INVALID_TIME"),
        ("2026-09-17", "2026-09-16", "UNKNOWN", "OFFICIAL_DATE_CONFLICT"),
    ],
)
def test_official_future_or_conflicting_dates_degrade(
    actual: str,
    official: str,
    health: str,
    staleness: str,
) -> None:
    item = _item(
        _record(
            "gdp_now",
            retrieved_at="2026-09-17T13:59:00Z",
            actual_latest_date=actual,
            official_latest_date=official,
            expected_release_date="2026-09-20",
        )
    )

    assert item["source_health"] == health
    assert item["staleness"] == staleness


@pytest.mark.parametrize(
    ("retrieved_at", "observed_at", "health", "staleness"),
    [
        ("2026-09-17T13:59:00", "2026-09-17T13:58:00Z", "UNKNOWN", "PROBE_TIME_UNVERIFIED"),
        ("2026-09-17T13:59:00Z", None, "FAILED", "CLOCK_UNVERIFIED"),
        ("2026-09-17T14:02:00Z", "2026-09-17T13:58:00Z", "FAILED", "INVALID_TIME"),
        ("2026-09-17T13:59:00Z", "2026-09-17T14:02:00Z", "FAILED", "INVALID_TIME"),
    ],
)
def test_missing_naive_and_future_market_times_degrade(
    retrieved_at: str,
    observed_at: str | None,
    health: str,
    staleness: str,
) -> None:
    item = _item(
        _record(
            "tv_xauusd",
            ticker="OANDA:XAUUSD",
            retrieved_at=retrieved_at,
            actual_latest_date=observed_at,
            delay_seconds=0,
        )
    )

    assert item["source_health"] == health
    assert item["staleness"] == staleness


def test_collection_failure_is_not_hidden_by_closed_equity_session() -> None:
    record = _record(
        "tv_spx",
        ticker="SP:SPX",
        retrieved_at="2026-09-19T14:59:00Z",
        actual_latest_date="2026-09-18T20:00:00Z",
        delay_seconds=0,
    )
    record["source_metadata"]["collector_status"] = "fetch_failed"

    item = _item(record, evaluated_at="2026-09-19T15:00:00Z")

    assert item["source_health"] == "FAILED"
    assert item["staleness"] == "COLLECTION_FAILED"
    assert item["reason"] == "collector_status_fetch_failed"


def test_closed_market_requires_verified_close_and_observation_in_close_window() -> None:
    recent = _item(
        _record(
            "tv_spx",
            ticker="SP:SPX",
            retrieved_at="2026-09-19T14:59:00Z",
            actual_latest_date="2026-09-18T20:00:00Z",
            expected_session_close="2026-09-18T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at="2026-09-19T15:00:00Z",
    )
    old = _item(
        _record(
            "tv_spx",
            ticker="SP:SPX",
            retrieved_at="2026-09-19T14:59:00Z",
            actual_latest_date="2026-09-18T13:30:00Z",
            expected_session_close="2026-09-18T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at="2026-09-19T15:00:00Z",
    )

    assert recent["source_health"] == "EXPECTED_STALE"
    assert old["source_health"] == "FAILED"
    assert old["reason"] == "observation_predates_latest_expected_market_session"


def test_closed_market_without_instrument_calendar_is_unknown_and_weeks_old_bar_fails() -> None:
    recent = _item(
        _record(
            "tv_spx",
            ticker="SP:SPX",
            retrieved_at="2026-09-19T14:59:00Z",
            actual_latest_date="2026-09-18T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at="2026-09-19T15:00:00Z",
    )
    old = _item(
        _record(
            "tv_spx",
            ticker="SP:SPX",
            retrieved_at="2026-09-19T14:59:00Z",
            actual_latest_date="2026-09-04T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at="2026-09-19T15:00:00Z",
    )

    assert recent["source_health"] == "UNKNOWN"
    assert recent["reason"] == "latest_expected_market_session_unverified"
    assert old["source_health"] == "FAILED"
    assert old["reason"] == "closed_market_observation_is_too_old"


def test_market_session_is_evaluated_per_asset_class() -> None:
    evaluated_at = "2026-09-20T21:30:00Z"  # Sunday 17:30 America/New_York
    xau = _item(
        _record(
            "tv_xauusd",
            ticker="OANDA:XAUUSD",
            retrieved_at="2026-09-20T21:29:30Z",
            actual_latest_date="2026-09-20T21:29:00Z",
            delay_seconds=0,
        ),
        evaluated_at=evaluated_at,
    )
    equity = _item(
        _record(
            "tv_spx",
            ticker="SP:SPX",
            retrieved_at="2026-09-20T21:29:30Z",
            actual_latest_date="2026-09-18T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at=evaluated_at,
    )
    energy = _item(
        _record(
            "tv_wti",
            ticker="NYMEX:CL1!",
            retrieved_at="2026-09-20T21:29:30Z",
            actual_latest_date="2026-09-18T20:00:00Z",
            delay_seconds=0,
        ),
        evaluated_at=evaluated_at,
    )

    assert xau["source_health"] == "HEALTHY"
    assert xau["current"]["market_session"]["state"] == "UNVERIFIED"
    assert equity["source_health"] == "UNKNOWN"
    assert equity["current"]["market_session"]["state"] == "CLOSED"
    assert energy["source_health"] == "UNKNOWN"
    assert energy["current"]["market_session"]["state"] == "CLOSED"
    assert energy["critical_freshness_failure"] == "ENERGY_INTRADAY"


def test_empty_source_list_is_not_ready() -> None:
    payload = build_research_source_health_view([], evaluated_at=NOW)

    assert payload["overall_status"] == "UNKNOWN"
    assert payload["production_ready"] is False


def test_fedwatch_metadata_configured_false_overrides_success_fixture() -> None:
    item = _item(
        _record(
            "fedwatch",
            configured=False,
            collector_status="success",
            retrieved_at="2026-09-17T13:59:00Z",
            observed_at="2026-09-17T13:58:00Z",
        )
    )

    assert item["source_health"] == "FAILED"
    assert item["reason"] == "source_not_configured"
