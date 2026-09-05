from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.analysis.strategy.live import (
    CANONICAL_CANDLE_DURATION_SECONDS,
    CANONICAL_FRESHNESS_SECONDS,
    build_live_strategy,
)
from apps.analysis.strategy.live_input_gates import evaluate_live_input_gates
from apps.analysis.strategy import live as live_module


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
LATEST_CANDLE_OPEN_AT = NOW - timedelta(seconds=CANONICAL_CANDLE_DURATION_SECONDS)


def _baseline() -> dict:
    return {
        "strategy_card_id": "baseline-1",
        "asset": "XAUUSD",
        "trade_date": "2026-07-17",
        "run_id": "run-1",
        "snapshot_id": "snapshot-1",
        "updated_at": "2026-07-17T06:00:00+00:00",
        "json": {"version": "1.0", "bias": "bullish", "confidence": 0.7},
        "source_refs": [{"source_ref": "snapshot://baseline-1"}],
        "artifact_refs": ["storage/outputs/strategy_card/XAUUSD/2026-07-17/run-1/strategy_card.json"],
    }


def _gold_baseline(
    *,
    direction: str = "long",
    status: str = "accepted",
    quality_status: str = "accepted",
) -> dict:
    strategy_status = {"long": "LONG_WATCH", "short": "SHORT_WATCH"}.get(direction, "NO_TRADE")
    return {
        "status": status,
        "reason_code": "gold_daily_close_head_accepted" if status == "accepted" else "gold_strategy_status_not_directional",
        "asset": "XAUUSD",
        "scope": "daily_close",
        "direction": direction,
        "strategy_status": strategy_status,
        "quality_status": quality_status,
        "decision_as_of": "2026-07-17T06:00:00+00:00",
        "strategy_decision_as_of": "2026-07-17T06:00:00+00:00",
        "state_as_of": "2026-07-17T06:00:00+00:00",
        "gold_head_held": False,
        "authority_ready": status in {"accepted", "held"} and direction in {"long", "short"} and quality_status == "accepted",
        "lineage_verified": True,
        "receipt_id": "gold_daily_close_canonical_receipt.v1:" + "1" * 64,
        "result_id": "gold_daily_close_loop_result.v1:" + "2" * 64,
        "feature_snapshot_id": "feature_snapshot.v1:" + "3" * 64,
        "state_id": "analysis_state.v1:" + "4" * 64,
        "transition_decision_hash": "5" * 64,
        "strategy_id": "strategy_decision.v1:" + "6" * 64,
        "consistency_decision_id": "analysis_strategy_consistency_decision.v1:" + "7" * 64,
        "strategy_policy_version": "gold_strategy_policy.v1",
        "is_trade_instruction": False,
        "confidence": 0.7,
        "market_regime": "direction_decision",
        "source_refs": [{"source_ref": "gold://daily-close"}],
        "artifact_refs": ["analysis/gold_mainlines/test/daily_close"],
    }


def _market(*, price: float = 100.0, latest_at: datetime = LATEST_CANDLE_OPEN_AT) -> dict:
    candles = []
    for index in range(15):
        close = price if index == 14 else 100.0
        candles.append(
            {
                "time": (latest_at - timedelta(minutes=(14 - index) * 5)).isoformat(),
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "source": "canonical_test",
            }
        )
    return {
        "provider": "jin10_mcp",
        "candles": candles,
        "source_trace": {"primary_source": "market_candles:XAUUSD:5m", "latest_raw_path": "raw/test.json"},
    }


def _market_15m(*, open_at: datetime = NOW - timedelta(minutes=15), close: float = 100.8, partial: bool = False) -> dict:
    return {
        "timeframe": "15m",
        "candles": [
            {
                "time": open_at.isoformat(),
                "open": close - 0.1,
                "high": close + 0.1,
                "low": close - 0.2,
                "close": close,
                "partial": partial,
                "source": "canonical_test",
            }
        ],
    }


def _options(*, strike: float = 102.0) -> dict:
    return {
        "status": "available",
        "meta": {
            "current_trade_date": "2026-07-17",
            "previous_trade_date": "2026-07-16",
            "comparison_status": "available",
        },
        "oi_summary": {"comparison_status": "available", "total": {"current": 12000.0, "delta": 450.0, "pct_change": 3.9}},
        "oi_change_rankings": {
            "largest_increases": [{"expiry": "AUG26", "strike": 102.0, "option_type": "CALL", "current_oi": 2500.0, "delta": 300.0}],
            "largest_decreases": [{"expiry": "AUG26", "strike": 98.0, "option_type": "PUT", "current_oi": 1800.0, "delta": -120.0}],
        },
        "large_oi_levels": [{"expiry": "AUG26", "strike": 102.0, "call_oi": 2500.0, "put_oi": 500.0, "total_oi": 3000.0, "total_oi_change": 320.0, "volume": 700.0, "dominant_side": "CALL"}],
        "nearby_large_oi_levels": [{"expiry": "AUG26", "strike": 102.0, "call_oi": 2500.0, "put_oi": 500.0, "total_oi": 3000.0, "total_oi_change": 320.0, "volume": 700.0, "dominant_side": "CALL", "distance_pct": 2.0}],
        "pnt_summary": {"status": "available", "totals": {"call": 150.0, "put": 0.0, "total": 150.0}, "top_activity": []},
        "intent_summary": {"type": "I2_structured_rebalance", "wording": "I2 修复型再平衡", "scores": {}, "evidence": []},
        "structure_summary": {"state": "negative_gamma_repair", "label": "负 Gamma 区内结构修复", "summary": "结构修复；尚未确认。", "repair_detected": True, "trend_launch_watch": True, "trend_confirmed": False},
        "scenario_paths": [{"path_id": "base_repair_range", "label": "主路径：修复震荡"}],
        "gamma_summary": {"regime": "negative_gamma"},
        "key_levels": [{"strike": strike, "role": "primary_resistance", "strength": 8.0}],
        "data_quality": {"cme_status": "FINAL"},
        "source_refs": [{"source_ref": "cme://decision"}],
        "artifact_refs": ["storage/features/cme/decision.json"],
    }


def _options_with_levels() -> dict:
    payload = _options(strike=102.0)
    payload["key_levels"] = [
        {"strike": 98.0, "role": "primary_support", "strength": 7.0},
        {"strike": 100.0, "role": "primary_resistance", "strength": 8.0},
        {"strike": 103.0, "role": "secondary_resistance", "strength": 6.0},
    ]
    return payload


def _build(**overrides: object) -> dict:
    inputs: dict[str, object] = {
        "asset": "XAUUSD",
        "baseline": _baseline(),
        "gold_baseline": _gold_baseline(),
        "canonical_market": _market(),
        "canonical_market_15m": _market_15m(),
        "options_decision": _options(),
        "quote_cache": None,
        "now": NOW,
    }
    inputs.update(overrides)
    return build_live_strategy(**inputs)


def _confirmed_break_market() -> dict:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    return market


def test_missing_or_stale_canonical_candle_suspends_data() -> None:
    missing = _build(canonical_market={"candles": []})
    stale = _build(
        canonical_market=_market(
            latest_at=NOW - timedelta(minutes=20)
        )
    )

    assert missing["strategy_status"] == "SUSPENDED_DATA"
    assert missing["update_reason"]["reason_code"] == "canonical_candle_unavailable"
    assert stale["strategy_status"] == "SUSPENDED_DATA"
    assert stale["update_reason"]["reason_code"] == "canonical_candle_stale"
    assert stale["live_market"]["price"] == 100.0
    assert stale["market_state"]["latest_price_event"] is None
    assert [setup["status"] for setup in stale["setups"]] == ["blocked_data", "blocked_data"]
    assert "fresh_canonical_5m_required" in stale["no_trade"]["waiting_conditions"]
    assert stale["event_overlay"]["status"] == "unavailable"


def test_future_canonical_timestamp_suspends_instead_of_appearing_fresh() -> None:
    payload = _build(canonical_market=_market(latest_at=NOW + timedelta(seconds=31)))

    assert payload["strategy_status"] == "SUSPENDED_DATA"
    assert payload["update_reason"]["reason_code"] == "canonical_candle_future"
    assert payload["live_market"]["freshness_seconds"] == -(CANONICAL_CANDLE_DURATION_SECONDS + 31)
    assert "canonical_candle_future" in payload["data_quality"]["warnings"]


def test_completed_candle_freshness_starts_at_bar_close() -> None:
    payload = _build(
        canonical_market=_market(
            latest_at=NOW - timedelta(seconds=CANONICAL_CANDLE_DURATION_SECONDS + CANONICAL_FRESHNESS_SECONDS)
        )
    )

    assert payload["live_market"]["freshness_seconds"] == CANONICAL_FRESHNESS_SECONDS
    assert payload["data_quality"]["canonical_candle"]["closed_at"] == (NOW - timedelta(seconds=CANONICAL_FRESHNESS_SECONDS)).isoformat()
    assert "canonical_candle_stale" not in payload["data_quality"]["warnings"]
    assert payload["strategy_status"] == "WAITING"


def test_15m_gate_uses_the_latest_complete_bucket_at_the_5m_close() -> None:
    five_minute_close_1155 = _market(latest_at=NOW - timedelta(minutes=10))
    aligned = evaluate_live_input_gates(
        canonical_market=five_minute_close_1155,
        canonical_market_15m=_market_15m(open_at=NOW - timedelta(minutes=30)),
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )
    future_bucket = evaluate_live_input_gates(
        canonical_market=five_minute_close_1155,
        canonical_market_15m=_market_15m(open_at=NOW - timedelta(minutes=15)),
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )
    previous_bucket = evaluate_live_input_gates(
        canonical_market=_market(),
        canonical_market_15m=_market_15m(open_at=NOW - timedelta(minutes=30)),
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )

    assert aligned["canonical_5m"]["closed_at"] == (NOW - timedelta(minutes=5)).isoformat()
    assert aligned["canonical_15m"]["ready"] is True
    assert aligned["canonical_15m"]["expected_closed_at"] == (NOW - timedelta(minutes=15)).isoformat()
    assert future_bucket["canonical_15m"]["ready"] is False
    assert future_bucket["canonical_15m"]["reason_code"] == "canonical_15m_scope_mismatch"
    assert previous_bucket["canonical_15m"]["ready"] is False
    assert previous_bucket["canonical_15m"]["reason_code"] == "canonical_15m_stale"


def test_input_gate_rejects_naive_and_nonfinite_or_nonpositive_ohlc() -> None:
    naive_market = _market()
    naive_market["candles"][-1]["time"] = "2026-07-17T11:55:00"
    nonfinite_market = _market_15m()
    nonfinite_market["candles"][0]["high"] = float("inf")
    nonpositive_market = _market_15m()
    nonpositive_market["candles"][0]["low"] = 0

    naive = evaluate_live_input_gates(
        canonical_market=naive_market,
        canonical_market_15m=_market_15m(),
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )
    nonfinite = evaluate_live_input_gates(
        canonical_market=_market(),
        canonical_market_15m=nonfinite_market,
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )
    nonpositive = evaluate_live_input_gates(
        canonical_market=_market(),
        canonical_market_15m=nonpositive_market,
        options_decision=_options(),
        effective_trade_date="2026-07-17",
        now=NOW,
    )

    assert naive["canonical_5m"]["ready"] is False
    assert naive["canonical_5m"]["reason_code"] == "canonical_candle_unavailable"
    assert nonfinite["canonical_15m"]["reason_code"] == "canonical_15m_invalid"
    assert nonpositive["canonical_15m"]["reason_code"] == "canonical_15m_invalid"


def test_middle_5m_gap_blocks_event_consumption() -> None:
    market = _confirmed_break_market()
    market["candles"].insert(
        0,
        {
            "time": (LATEST_CANDLE_OPEN_AT - timedelta(minutes=5)).isoformat(),
            "open": 100.0,
            "high": 100.1,
            "low": 99.9,
            "close": 100.0,
            "source": "canonical_test",
        },
    )
    market["candles"].pop(-4)
    payload = _build(
        canonical_market=market,
        canonical_market_15m=_market_15m(),
        options_decision=_options_with_levels(),
    )

    assert payload["strategy_status"] != "TRIGGERED"
    assert payload["market_state"]["latest_price_event"] is None
    assert payload["data_quality"]["input_gates"]["canonical_5m"]["reason_code"] == "canonical_candle_window_gap"
    assert "canonical_candle_window_gap" in payload["feasibility"]["reasons"]["input_gates"]


def test_missing_gold_authority_or_option_levels_waits_with_gap_reason() -> None:
    missing_baseline = _build(gold_baseline=None)
    missing_levels = _build(options_decision={"meta": {"current_trade_date": "2026-07-17"}})

    assert missing_baseline["strategy_status"] == "WAITING"
    assert missing_baseline["update_reason"]["reason_code"] == "gold_direction_authority_unavailable"
    assert missing_baseline["active_scenario"] is None
    assert [setup["status"] for setup in missing_baseline["setups"]] == ["unavailable", "unavailable"]
    assert "verified_gold_direction_required" in missing_baseline["no_trade"]["waiting_conditions"]
    assert missing_levels["strategy_status"] == "WAITING"
    assert missing_levels["update_reason"]["reason_code"] == "option_key_levels_unavailable"
    assert missing_levels["active_scenario"] is None
    assert [setup["status"] for setup in missing_levels["setups"]] == ["unavailable", "unavailable"]


def test_far_approach_and_touch_map_to_frozen_states() -> None:
    far = _build(options_decision=_options(strike=102.0))
    approach = _build(options_decision=_options(strike=100.8), gold_baseline=_gold_baseline(direction="short"))
    touch = _build(options_decision=_options(strike=100.05), gold_baseline=_gold_baseline(direction="short"))

    assert (far["strategy_status"], far["update_reason"]["reason_code"]) == ("WAITING", "outside_approach_range")
    assert (approach["strategy_status"], approach["update_reason"]["reason_code"]) == ("WATCHING", "approach")
    assert (touch["strategy_status"], touch["update_reason"]["reason_code"]) == ("ARMED", "touch")
    assert touch["market_state"]["touch_threshold"] == 0.1
    assert touch["market_state"]["approach_threshold"] == 1.0
    assert touch["market_state"]["nearest_level"]["value"] == 100.05
    assert touch["market_state"]["level_event"] == "touch"
    assert touch["update_reason"]["related_level"]["role"] == "primary_resistance"
    assert touch["feasibility"]["reasons"]["execution_ready"] == ["execution_intentionally_not_supported"]
    assert touch["live_market"]["timestamps"]["canonical"] == LATEST_CANDLE_OPEN_AT.isoformat()
    assert touch["live_market"]["timestamps"]["canonical_closed_at"] == NOW.isoformat()
    assert touch["live_market"]["freshness_seconds"] == 0


def test_stale_quote_cache_never_populates_supplemental_fields() -> None:
    payload = _build(
        quote_cache={
            "generated_at": (NOW - timedelta(seconds=121)).isoformat(),
            "quotes": {"XAUUSD": {"price": 99.0, "bid": 99.9, "ask": 100.1, "change_pct": 1.2}},
        }
    )

    assert payload["live_market"]["price"] == 100.0
    assert payload["live_market"]["bid"] is None
    assert payload["live_market"]["ask"] is None
    assert payload["live_market"]["change_pct"] is None
    assert "quote_cache_stale" in payload["data_quality"]["warnings"]


def test_future_quote_cache_never_populates_supplemental_fields() -> None:
    payload = _build(
        quote_cache={
            "generated_at": (NOW + timedelta(seconds=31)).isoformat(),
            "quotes": {"XAUUSD": {"bid": 99.9, "ask": 100.1, "change_pct": 1.2}},
        }
    )

    assert payload["live_market"]["bid"] is None
    assert payload["live_market"]["ask"] is None
    assert "quote_cache_future" in payload["data_quality"]["warnings"]


def test_identical_inputs_produce_deterministic_strategy_id_and_version() -> None:
    first = _build()
    second = _build()

    assert first["strategy_id"] == second["strategy_id"]
    assert first["strategy_version"] == second["strategy_version"] == "live_strategy.rules.v2"


def test_projects_cme_positioning_without_frontend_calculation() -> None:
    payload = _build()

    cme = payload["cme_positioning"]
    assert cme["status"] == "available"
    assert cme["trade_date"] == "2026-07-17"
    assert cme["previous_trade_date"] == "2026-07-16"
    assert cme["baseline_trade_date"] == "2026-07-17"
    assert cme["aligned_with_baseline"] is True
    assert cme["source_status"] == "FINAL"
    assert cme["total_oi"] == {"current": 12000.0, "delta": 450.0, "pct_change": 3.9}
    assert cme["large_oi_levels"][0]["total_oi"] == 3000.0
    assert cme["largest_increases"][0]["delta"] == 300.0
    assert cme["largest_decreases"][0]["delta"] == -120.0
    assert cme["structure_summary"]["repair_detected"] is True
    assert cme["intent_summary"]["type"] == "I2_structured_rebalance"
    assert cme["scenario_paths"][0]["path_id"] == "base_repair_range"


def test_missing_cme_positioning_fails_closed() -> None:
    payload = _build(options_decision={"meta": {"current_trade_date": "2026-07-17"}})

    assert payload["cme_positioning"]["status"] == "unavailable"
    assert payload["cme_positioning"]["large_oi_levels"] == []
    assert payload["cme_positioning"]["largest_increases"] == []
    assert payload["cme_positioning"]["largest_decreases"] == []


@pytest.mark.parametrize(
    ("options_status", "cme_status", "reason_code"),
    [
        ("available", "PRELIM", "cme_quality_not_final"),
        ("partial", "FINAL", "cme_unavailable"),
    ],
)
def test_cme_gate_blocks_directional_trigger_but_keeps_observation(
    options_status: str,
    cme_status: str,
    reason_code: str,
) -> None:
    options = _options_with_levels()
    options["status"] = options_status
    options["data_quality"]["cme_status"] = cme_status
    payload = _build(
        canonical_market=_confirmed_break_market(),
        canonical_market_15m=_market_15m(),
        options_decision=options,
    )

    assert payload["strategy_status"] == "WAITING"
    assert payload["active_scenario"] is None
    assert payload["feasibility"]["trigger_ready"] is False
    assert payload["setups"][0]["gate"]["reasons"] == [reason_code]
    assert payload["cme_positioning"]["source_status"] == cme_status
    assert payload["market_state"]["key_levels"]
    assert payload["data_quality"]["input_gates"]["cme"]["reason_code"] == reason_code


def test_hold_uses_effective_strategy_date_instead_of_latest_receipt_date() -> None:
    authority = _gold_baseline(status="held")
    authority.update(
        decision_as_of="2026-07-17T11:00:00+00:00",
        strategy_decision_as_of="2026-07-16T06:00:00+00:00",
        state_as_of="2026-07-16T06:00:00+00:00",
        gold_head_held=True,
    )
    payload = _build(
        canonical_market=_confirmed_break_market(),
        canonical_market_15m=_market_15m(),
        options_decision=_options_with_levels(),
        gold_baseline=authority,
    )

    assert payload["baseline"]["trade_date"] == "2026-07-16"
    assert payload["baseline"]["effective_strategy_as_of"] == "2026-07-16T06:00:00+00:00"
    assert payload["strategy_status"] == "WAITING"
    assert payload["active_scenario"] is None
    assert "cme_gold_trade_date_mismatch" in payload["data_quality"]["input_gates"]["cme"]["reasons"]
    assert "live_candle_scope_mismatch" in payload["data_quality"]["input_gates"]["utc_scope"]["reasons"]


def test_strategy_id_ignores_display_age_but_changes_when_gate_status_changes() -> None:
    first = _build(now=NOW)
    one_second_later = _build(now=NOW + timedelta(seconds=1))
    stale = _build(now=NOW + timedelta(minutes=11))

    assert first["strategy_id"] == one_second_later["strategy_id"]
    assert stale["strategy_id"] != first["strategy_id"]
    assert stale["data_quality"]["input_gates"]["canonical_5m"]["reason_code"] == "canonical_candle_stale"


def test_strategy_id_changes_when_confirmation_window_changes() -> None:
    confirmed_market = _market(price=100.7)
    confirmed_market["candles"][-2]["close"] = 100.7
    confirmed_market["candles"][-2]["high"] = 100.8
    confirmed_market["candles"][-1]["high"] = 100.8
    unconfirmed_market = _market(price=100.7)
    confirmation_15m = _market_15m()

    confirmed = _build(
        canonical_market=confirmed_market,
        canonical_market_15m=confirmation_15m,
        options_decision=_options_with_levels(),
    )
    unconfirmed = _build(
        canonical_market=unconfirmed_market,
        canonical_market_15m=confirmation_15m,
        options_decision=_options_with_levels(),
    )

    assert confirmed["live_market"]["price"] == unconfirmed["live_market"]["price"]
    assert confirmed["strategy_id"] != unconfirmed["strategy_id"]


def test_confirmed_break_with_passing_rr_triggers_without_active_execution() -> None:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    payload = _build(
        canonical_market=market,
        canonical_market_15m=_market_15m(),
        options_decision=_options_with_levels(),
    )

    assert payload["market_state"]["latest_price_event"]["event_type"] == "accepted_break"
    assert payload["market_state"]["confirmation_15m"] == {
        "confirmed": True,
        "close": 100.8,
        "timestamp": (NOW - timedelta(minutes=15)).isoformat(),
    }
    assert payload["strategy_status"] == "TRIGGERED"
    assert payload["active_scenario"] == "long"
    assert payload["setups"][0]["stop_reference"] < payload["setups"][0]["reference_level"]["value"]
    assert payload["no_trade"]["reasons"] == []
    assert payload["no_trade"]["waiting_conditions"] == []
    assert payload["feasibility"]["execution_ready"] is False


@pytest.mark.parametrize(
    ("canonical_market_15m", "reason_code"),
    [
        ({"candles": []}, "canonical_15m_missing"),
        (_market_15m(partial=True), "canonical_15m_partial"),
        (_market_15m(open_at=NOW), "canonical_15m_future"),
        (_market_15m(open_at=NOW - timedelta(minutes=30)), "canonical_15m_stale"),
    ],
)
def test_confirmed_break_requires_a_complete_aligned_15m_window(
    canonical_market_15m: dict,
    reason_code: str,
) -> None:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    payload = _build(
        canonical_market=market,
        canonical_market_15m=canonical_market_15m,
        options_decision=_options_with_levels(),
    )

    assert payload["strategy_status"] != "TRIGGERED"
    assert payload["active_scenario"] is None
    assert payload["feasibility"]["trigger_ready"] is False
    assert payload["data_quality"]["input_gates"]["canonical_15m"]["reason_code"] == reason_code
    assert reason_code in payload["feasibility"]["reasons"]["input_gates"]


@pytest.mark.parametrize("event_type", ["failed_break", "retest", "reclaim"])
def test_confirmed_price_events_are_blocked_without_15m_gate(monkeypatch, event_type: str) -> None:
    monkeypatch.setattr(
        live_module,
        "detect_latest_price_event",
        lambda **_: {
            "event_type": event_type,
            "direction": "above",
            "confirmed": True,
            "price": 100.7,
            "related_level": {"value": 100.0, "role": "primary_resistance"},
        },
    )
    payload = _build(
        canonical_market_15m={"candles": []},
        options_decision=_options_with_levels(),
    )

    assert payload["strategy_status"] != "TRIGGERED"
    assert payload["market_state"]["latest_price_event"] is None
    assert payload["data_quality"]["input_gates"]["canonical_15m"]["reason_code"] == "canonical_15m_missing"


def test_gold_authority_blocks_an_opposite_confirmed_break() -> None:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    payload = _build(
        canonical_market=market,
        canonical_market_15m=_market_15m(),
        options_decision=_options_with_levels(),
        gold_baseline=_gold_baseline(direction="short"),
    )

    assert payload["strategy_status"] == "WAITING"
    assert payload["update_reason"]["reason_code"] == "gold_direction_mismatch"
    assert payload["active_scenario"] is None
    assert payload["setups"][0]["status"] == "unavailable"
    assert payload["setups"][0]["gate"]["reasons"] == ["gold_direction_mismatch"]
    assert payload["feasibility"]["trigger_ready"] is False


def test_gold_authority_uses_failed_break_reversal_over_supplemental_card_bias() -> None:
    short_market = _market(price=99.9)
    short_market["candles"][-3].update(open=99.0, close=99.0, high=99.1, low=98.9)
    short_market["candles"][-2].update(open=100.5, close=100.5, high=100.6, low=100.4)
    short_market["candles"][-1].update(open=99.9, close=99.9, high=100.0, low=99.8)
    short = _build(
        canonical_market=short_market,
        options_decision=_options_with_levels(),
        gold_baseline=_gold_baseline(direction="short"),
    )

    long_market = _market(price=98.1)
    long_market["candles"][-3].update(open=99.0, close=99.0, high=99.1, low=98.9)
    long_market["candles"][-2].update(open=97.5, close=97.5, high=97.6, low=97.4)
    long_market["candles"][-1].update(open=98.1, close=98.1, high=98.2, low=98.0)
    long = _build(
        canonical_market=long_market,
        options_decision=_options_with_levels(),
        gold_baseline=_gold_baseline(direction="long"),
    )

    assert short["baseline"]["premarket_context"]["bias"] == "bullish"
    assert short["baseline"]["bias"] == "bearish"
    assert short["market_state"]["latest_price_event"]["event_type"] == "failed_break"
    assert short["market_state"]["latest_price_event"]["direction"] == "above"
    assert short["strategy_status"] == "TRIGGERED"
    assert short["active_scenario"] == "short"
    assert short["setups"][0]["status"] == "unavailable"
    assert short["setups"][1]["status"] == "triggered"

    assert long["market_state"]["latest_price_event"]["event_type"] == "failed_break"
    assert long["market_state"]["latest_price_event"]["direction"] == "below"
    assert long["strategy_status"] == "TRIGGERED"
    assert long["active_scenario"] == "long"
    assert long["setups"][0]["status"] == "triggered"
    assert long["setups"][1]["status"] == "unavailable"


def test_missing_gold_authority_does_not_use_ordinary_strategy_card_for_trigger() -> None:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    payload = _build(
        canonical_market=market,
        canonical_market_15m=_market_15m(),
        options_decision=_options_with_levels(),
        gold_baseline=None,
    )

    assert payload["baseline"]["premarket_context"]["strategy_card_id"] == "baseline-1"
    assert payload["strategy_status"] == "WAITING"
    assert payload["update_reason"]["reason_code"] == "gold_direction_authority_unavailable"
    assert payload["market_state"]["latest_price_event"] is None
    assert payload["active_scenario"] is None
    assert [setup["status"] for setup in payload["setups"]] == ["unavailable", "unavailable"]


def test_malformed_gold_authority_fails_closed_even_when_it_claims_ready() -> None:
    market = _market(price=100.7)
    market["candles"][-2]["close"] = 100.7
    market["candles"][-2]["high"] = 100.8
    market["candles"][-1]["high"] = 100.8
    invalid_values = {
        "lineage_verified": False,
        "result_id": None,
        "receipt_id": "x",
        "feature_snapshot_id": "x",
        "state_id": "x",
        "transition_decision_hash": "x",
        "strategy_id": "x",
        "consistency_decision_id": "x",
        "strategy_policy_version": "evil",
        "strategy_decision_as_of": (NOW + timedelta(seconds=1)).isoformat(),
        "state_as_of": (NOW + timedelta(seconds=1)).isoformat(),
        "is_trade_instruction": True,
        "direction": [],
        "status": [],
        "strategy_status": {},
    }

    for key, value in invalid_values.items():
        malformed = _gold_baseline()
        malformed[key] = value
        malformed["authority_ready"] = True
        payload = _build(
            canonical_market=market,
            canonical_market_15m=_market_15m(),
            options_decision=_options_with_levels(),
            gold_baseline=malformed,
        )

        assert payload["strategy_status"] == "WAITING", key
        assert payload["update_reason"]["reason_code"] == "gold_direction_authority_invalid", key
        assert payload["baseline"]["authority"]["status"] == "invalid", key
        assert payload["baseline"]["authority"]["direction"] == "none", key
        assert payload["market_state"]["latest_price_event"] is None, key
        assert payload["active_scenario"] is None, key
        assert [setup["status"] for setup in payload["setups"]] == ["unavailable", "unavailable"], key


def test_live_strategy_builder_rejects_non_xauusd_assets() -> None:
    with pytest.raises(ValueError, match="supports only XAUUSD"):
        _build(asset="GC")


def test_gold_authority_accepts_supported_v2_identity_contracts() -> None:
    authority = _gold_baseline()
    authority.update(
        feature_snapshot_id="feature_snapshot.v2:" + "3" * 64,
        state_id="analysis_state.v2:" + "4" * 64,
        strategy_id="strategy_decision.v2:" + "6" * 64,
        strategy_policy_version="gold_strategy_policy.v2",
    )

    payload = _build(gold_baseline=authority)

    assert payload["data_quality"]["gold_baseline"]["authority_ready"] is True
    assert payload["baseline"]["bias"] == "bullish"


def test_event_overlay_is_additive_and_does_not_flip_stale_strategy() -> None:
    event = {
        "event_id": "fed-2026-07-18",
        "event_type": "fomc_statement",
        "observed_at": "2026-07-18T12:00:00+00:00",
        "source_reliability": 0.95,
        "event_importance": 0.90,
        "surprise": 0.85,
        "gold_relevance": 0.90,
        "market_reaction_strength": 0.85,
        "reaction_persistence": 0.80,
        "official_source": True,
        "independent_source_count": 2,
        "observed_reaction": {"direction": "up", "window": "30m"},
        "evidence": [{"kind": "release", "id": "fed-2026-07-18"}],
        "source_refs": [{"source": "fed"}, {"source": "cme"}],
    }
    payload = _build(
        canonical_market=_market(
            latest_at=NOW - timedelta(minutes=20)
        ),
        event_observation=event,
    )

    assert payload["strategy_status"] == "SUSPENDED_DATA"
    assert payload["event_overlay"]["recompute_candidate"] is True
    assert payload["event_overlay"]["status"] == "eligible"
