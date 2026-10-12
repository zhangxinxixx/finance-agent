from __future__ import annotations

from copy import deepcopy

import pytest

from apps.features.research.workflow import _row_time_valid, build_gold_workflow, select_real_rate


REFS = [{"source": "FRED", "reference": "https://example.test/fred"}]


def _row(
    symbol: str,
    value: float,
    *,
    change: float = 0.01,
    refs: list[dict] | None = None,
    components: list[dict] | None = None,
    observation_date: str = "2026-09-08",
    previous_date: str = "2026-09-05",
    frequency: str | None = None,
) -> dict:
    row = {
        "symbol": symbol,
        "value": value,
        "change": change,
        "source_refs": deepcopy(REFS if refs is None else refs),
        "status": "fresh",
        "lineage_status": "verified",
        "observation_date": observation_date,
        "previous_date": previous_date,
        "components": deepcopy(components or []),
    }
    if frequency is not None:
        row["frequency"] = frequency
    return row


def _options() -> dict:
    return {
        "walls": [{"strike": 110.0, "side": "CALL"}],
        "source_refs": deepcopy(REFS),
        "data_source": {"status": "FINAL", "report_date": "2026-09-08"},
        "parameters": {
            "expiry_dates": {
                "OCT26": {
                    "expiry_date": "2026-10-24",
                    "source": "cme_contract_calendar",
                }
            },
            "expiry_sources": {
                "OCT26": {
                    "expiry_date": "2026-10-24",
                    "expiry_source": "cme_contract_calendar",
                }
            },
        },
    }


def _snapshot(
    *,
    rows: list[dict] | None = None,
    options: dict | None = None,
    instrument_type: str = "spot",
    price_time: str = "2026-09-08T11:55:00+00:00",
    trend: str = "bullish",
    technical_refs: list[dict] | None = None,
) -> dict:
    passport = rows or [
        _row("REAL10Y", 2.42, change=0.01),
        _row("REAL_10Y", 2.41, change=0.01),
        _row("BROAD_DOLLAR", 100.0, change=0.01),
        _row("XAUUSD_DAILY", 100.0, change=0.01),
        _row("SOFR", 3.66),
        _row("EFFR", 3.63),
        _row("HY_OAS", 2.66),
        _row("RESERVES", 2.89, change=-0.01),
        _row("TGA_WEEKLY_AVERAGE", 0.96, change=0.01),
        _row("BREAKEVEN_10Y", 2.35),
        _row("BRENT_SPOT", 92.68),
    ]
    technical_source_refs = REFS if technical_refs is None else technical_refs
    return {
        "snapshot_id": "XAUUSD:2026-09-08:run",
        "trade_date": "2026-09-08",
        "snapshot_time": "2026-09-08T12:00:00+00:00",
        "run_id": "run",
        "input_snapshot_ids": {"macro": "macro:run"},
        "source_refs": deepcopy(REFS),
        "daily_research": {
            "passport": deepcopy(passport),
            "spot_anchor": {
                "status": "verified",
                "instrument_type": instrument_type,
                "price": 100.0,
                "price_time": price_time,
                "source_refs": deepcopy(REFS),
            },
            "official_etf": {
                "shares_source_refs": deepcopy(REFS),
                "source_refs": deepcopy(REFS),
                "shares_reported_on": "2026-09-08",
                "shares_delta": 1.0,
                "shares_weekly_delta": 1.0,
            },
            "cot_reports": {"combined": {}},
            "source_refs": deepcopy(REFS),
        },
        "technical": {
            "status": "available",
            "data": {
                "as_of": "2026-09-08",
                "price": 100.0,
                "trend": trend,
                "ma20": 98.0,
                "source_refs": deepcopy(technical_source_refs),
                "key_levels": [
                    {
                        "price": 95.0,
                        "kind": "prior_5d_low",
                        "source_refs": deepcopy(technical_source_refs),
                    }
                ],
            },
        },
        "options": {"status": "available", "data": deepcopy(_options() if options is None else options)},
        "news": {"status": "available", "data": {"daily_market_brief": {}}},
    }


def _quality(workflow: dict, code: str) -> dict:
    return next(item for item in workflow["quality_gate"]["checks"] if item["id"] == code)


def test_official_tips_has_precedence_and_mismatched_estimate_is_rejected() -> None:
    workflow = build_gold_workflow(_snapshot())
    assert workflow["real_rate"]["method"] == "official_tips"
    assert workflow["real_rate"]["symbol"] == "REAL10Y"

    rows = [row for row in _snapshot()["daily_research"]["passport"] if row["symbol"] != "REAL10Y"]
    estimated = next(row for row in rows if row["symbol"] == "REAL_10Y")
    estimated["components"] = [
        {"date": "2026-09-08", "source_symbol": "US10Y", "value": 4.7},
        {"date": "2026-09-07", "source_symbol": "BREAKEVEN_10Y", "value": 2.3},
    ]
    rejected = build_gold_workflow(_snapshot(rows=rows))
    assert rejected["real_rate"]["method"] == "unavailable"
    assert _quality(rejected, "Q3")["passed"] is False

    rows = [row for row in _snapshot()["daily_research"]["passport"] if row["symbol"] != "REAL10Y"]
    estimated = next(row for row in rows if row["symbol"] == "REAL_10Y")
    estimated["components"] = [
        {"date": "2026-09-08", "source_symbol": "US10Y", "value": 4.7},
        {"date": "2026-09-08", "source_symbol": "BREAKEVEN_10Y", "value": 2.3},
    ]
    estimated["observation_date"] = "2026-09-09"
    row_date_mismatch = build_gold_workflow(_snapshot(rows=rows))
    assert row_date_mismatch["real_rate"]["method"] == "unavailable"


def test_same_observation_revision_is_not_classified_as_new_observation() -> None:
    current = _snapshot()
    previous_rows = deepcopy(current["daily_research"]["passport"])
    previous_real = next(row for row in previous_rows if row["symbol"] == "REAL10Y")
    previous_real["value"] = 2.40
    previous = {
        "status": "verified",
        "snapshot_id": "previous",
        "snapshot_time": "2026-09-08T09:00:00+00:00",
        "passport": previous_rows,
        "source_refs": deepcopy(REFS),
    }
    result = build_gold_workflow(current, previous=previous)
    delta = next(item for item in result["delta_vs_previous"]["rows"] if item["symbol"] == "REAL10Y")
    assert delta["change_kind"] == "same_observation_revised"
    assert delta["delta"] == pytest.approx(0.02)


def test_missing_options_zeroes_coverage_and_renormalizes_remaining_weights() -> None:
    snapshot = _snapshot(options={})
    snapshot["options"] = {"status": "unavailable", "reason": "missing"}
    result = build_gold_workflow(snapshot)
    engine = result["scenario_engine"]
    assert engine["coverage"]["options"] == 0.0
    assert engine["normalized_weights"]["options"] == 0.0
    assert sum(engine["normalized_weights"].values()) == 1.0


def test_observed_options_and_news_do_not_invent_neutral_direction_votes():
    snapshot = _snapshot()
    options = snapshot["options"]["data"]
    options["walls"] = [{"strike": 110, "oi": 200}]
    options["source_refs"] = [{"source": "cme", "raw_path": "raw/cme/bulletin.pdf", "source_url": "https://www.cmegroup.com/bulletin"}]
    snapshot["news"]["data"]["daily_market_brief"] = {"candidate_events": [{"title": "unverified event"}]}
    engine = build_gold_workflow(snapshot)["scenario_engine"]
    for key in ("options", "events"):
        assert engine["coverage"][key] > 0
        assert engine["signal_status"][key] == "direction_unavailable"
        assert engine["normalized_weights"][key] == 0
    assert sum(engine["normalized_weights"].values()) == pytest.approx(1)


def test_liquidity_prices_enter_macro_score_but_inflation_is_not_a_duplicate_rate_vote():
    snapshot = _snapshot()
    rows = snapshot["daily_research"]["passport"]
    rows.append(_row("SOFR_MINUS_IORB", .02, change=.01))
    for row in rows:
        if row["symbol"] == "BROAD_DOLLAR":
            row["change"] = -.01
        if row["symbol"] == "RESERVES":
            row["weekly_change"] = -10
        if row["symbol"] == "TGA_WEEKLY_AVERAGE":
            row["weekly_change"] = 5
    flow = build_gold_workflow(snapshot)
    liquidity = next(x for x in flow["factor_families"] if x["family"] == "liquidity_credit")
    assert liquidity["direction"] == "bearish"
    assert "liquidity_credit" in flow["scenario_engine"]["macro_scoring_families"]
    assert "inflation" not in flow["scenario_engine"]["macro_scoring_families"]
    original_score = flow["scenario_engine"]["direction_signals"]["macro"]
    rows[-1]["status"] = "stale"
    degraded = build_gold_workflow(snapshot)
    assert "liquidity_credit" not in degraded["scenario_engine"]["macro_scoring_families"]
    assert degraded["scenario_engine"]["direction_signals"]["macro"] > original_score


def test_future_or_futures_timestamp_cannot_verify_spot_anchor() -> None:
    future_instrument = build_gold_workflow(_snapshot(instrument_type="future"))
    assert future_instrument["price_anchor"]["status"] == "partial"
    assert _quality(future_instrument, "Q1")["passed"] is False

    future_timestamp = build_gold_workflow(
        _snapshot(price_time="2026-09-08T12:01:00+00:00")
    )
    assert future_timestamp["price_anchor"]["status"] == "partial"
    assert _quality(future_timestamp, "Q1")["passed"] is False


def test_opposite_real_rate_and_dollar_directions_cannot_strong_confirm() -> None:
    rows = _snapshot()["daily_research"]["passport"]
    next(row for row in rows if row["symbol"] == "REAL10Y")["change"] = 0.01
    next(row for row in rows if row["symbol"] == "BROAD_DOLLAR")["change"] = -0.01
    result = build_gold_workflow(_snapshot(rows=rows))
    assert _quality(result, "Q9")["passed"] is False
    assert result["quality_gate"]["strong_direction_allowed"] is False


def test_missing_option_refs_expiry_and_level_refs_fail_quality_gate_closed() -> None:
    options = _options()
    options["source_refs"] = []
    options["parameters"]["expiry_dates"] = {
        "OCT26": {"source": "cme_contract_calendar"}
    }
    options["parameters"]["expiry_sources"] = {}
    result = build_gold_workflow(_snapshot(options=options, technical_refs=[]))
    assert _quality(result, "Q4")["passed"] is False
    assert _quality(result, "Q7")["passed"] is False
    assert _quality(result, "Q8")["passed"] is False


def test_research_candidate_does_not_replace_formal_state() -> None:
    result = build_gold_workflow(
        _snapshot(trend="bearish"),
        previous={
            "status": "verified",
            "snapshot_id": "previous",
            "snapshot_time": "2026-09-07T12:00:00+00:00",
            "research_state": {"current_state": "S6"},
            "passport": [],
            "source_refs": deepcopy(REFS),
        },
    )
    assert result["state"]["candidate_state"] == "S1"
    assert result["state"]["current_state"] is None
    assert result["state"]["formal_state_authority"] is False


def test_temporal_gate_rejects_future_and_old_daily_rows_but_keeps_weekly_monthly_windows() -> None:
    cutoff = "2026-09-08T12:00:00+00:00"
    trade_date = "2026-09-08"
    current_daily = _row("REAL10Y", 2.42, observation_date="2026-09-04")
    assert _row_time_valid(current_daily, analysis_cutoff=cutoff, trade_date=trade_date)

    future = deepcopy(current_daily)
    future["observation_date"] = "2026-09-09"
    assert not _row_time_valid(future, analysis_cutoff=cutoff, trade_date=trade_date)

    old = deepcopy(current_daily)
    old["observation_date"] = "2026-08-20"
    assert not _row_time_valid(old, analysis_cutoff=cutoff, trade_date=trade_date)

    weekly = _row("RESERVES", 2.89, observation_date="2026-09-01", frequency="weekly")
    assert _row_time_valid(weekly, analysis_cutoff=cutoff, trade_date=trade_date)

    monthly = _row("CPI", 330.0, observation_date="2026-07-01", frequency="monthly")
    assert _row_time_valid(monthly, analysis_cutoff=cutoff, trade_date=trade_date)
    monthly["observation_date"] = "2026-05-01"
    assert not _row_time_valid(monthly, analysis_cutoff=cutoff, trade_date=trade_date)


def test_q2_accepts_walcl_in_weekly_window_and_rejects_it_after_expiry() -> None:
    current = _snapshot(rows=[
        _row("WALCL", 7123.4567, observation_date="2026-09-09", frequency="weekly"),
    ])
    current["trade_date"] = "2026-09-17"
    current["snapshot_time"] = "2026-09-17T12:00:00+00:00"

    assert _quality(build_gold_workflow(current), "Q2")["passed"] is True

    current["daily_research"]["passport"][0]["observation_date"] = "2026-09-06"
    assert _quality(build_gold_workflow(current), "Q2")["passed"] is False


def test_real_rate_selection_rejects_future_or_expired_official_tips() -> None:
    context = {"analysis_cutoff": "2026-09-08T12:00:00+00:00", "trade_date": "2026-09-08"}
    estimated = _row(
        "REAL_10Y", 2.41,
        components=[
            {"date": "2026-09-08", "source_symbol": "US10Y", "value": 4.70},
            {"date": "2026-09-08", "source_symbol": "BREAKEVEN_10Y", "value": 2.29},
        ],
    )
    for invalid_date in ("2030-01-01", "2020-01-01"):
        official = _row("REAL10Y", 2.42, observation_date=invalid_date)
        selected, method = select_real_rate(
            {"REAL10Y": official, "REAL_10Y": estimated}, **context,
        )
        assert selected["symbol"] == "REAL_10Y"
        assert method == "estimated_same_date"


def test_q2_rejects_future_or_expired_observation_even_when_upstream_status_says_fresh(monkeypatch) -> None:
    monkeypatch.setattr("apps.features.research.levels.build_key_levels", lambda snapshot, previous_levels: [])
    for observation_date in ("2026-09-09", "2026-08-20"):
        snapshot = _snapshot()
        next(row for row in snapshot["daily_research"]["passport"] if row["symbol"] == "REAL10Y")["observation_date"] = observation_date
        result = build_gold_workflow(snapshot)
        assert _quality(result, "Q2")["passed"] is False
