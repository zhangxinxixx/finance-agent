from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.analysis.strategy.live import build_live_strategy


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


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


def _market(*, price: float = 100.0, latest_at: datetime = NOW) -> dict:
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


def _options(*, strike: float = 102.0) -> dict:
    return {
        "meta": {"current_trade_date": "2026-07-17"},
        "gamma_summary": {"regime": "negative_gamma"},
        "key_levels": [{"strike": strike, "role": "primary_resistance", "strength": 8.0}],
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
        "canonical_market": _market(),
        "options_decision": _options(),
        "quote_cache": None,
        "now": NOW,
    }
    inputs.update(overrides)
    return build_live_strategy(**inputs)


def test_missing_or_stale_canonical_candle_suspends_data() -> None:
    missing = _build(canonical_market={"candles": []})
    stale = _build(canonical_market=_market(latest_at=NOW - timedelta(seconds=601)))

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
    assert payload["live_market"]["freshness_seconds"] == -31
    assert "canonical_candle_future" in payload["data_quality"]["warnings"]


def test_missing_baseline_or_option_levels_waits_with_gap_reason() -> None:
    missing_baseline = _build(baseline=None)
    missing_levels = _build(options_decision={"meta": {"current_trade_date": "2026-07-17"}})

    assert missing_baseline["strategy_status"] == "WAITING"
    assert missing_baseline["update_reason"]["reason_code"] == "baseline_unavailable"
    assert missing_baseline["active_scenario"] is None
    assert [setup["status"] for setup in missing_baseline["setups"]] == ["unavailable", "unavailable"]
    assert missing_levels["strategy_status"] == "WAITING"
    assert missing_levels["update_reason"]["reason_code"] == "option_key_levels_unavailable"
    assert missing_levels["active_scenario"] is None
    assert [setup["status"] for setup in missing_levels["setups"]] == ["unavailable", "unavailable"]


def test_far_approach_and_touch_map_to_frozen_states() -> None:
    far = _build(options_decision=_options(strike=102.0))
    approach = _build(options_decision=_options(strike=100.8))
    touch = _build(options_decision=_options(strike=100.05))

    assert (far["strategy_status"], far["update_reason"]["reason_code"]) == ("WAITING", "outside_approach_range")
    assert (approach["strategy_status"], approach["update_reason"]["reason_code"]) == ("WATCHING", "approach")
    assert (touch["strategy_status"], touch["update_reason"]["reason_code"]) == ("ARMED", "touch")
    assert touch["market_state"]["touch_threshold"] == 0.1
    assert touch["market_state"]["approach_threshold"] == 1.0
    assert touch["market_state"]["nearest_level"]["value"] == 100.05
    assert touch["market_state"]["level_event"] == "touch"
    assert touch["update_reason"]["related_level"]["role"] == "primary_resistance"
    assert touch["feasibility"]["reasons"]["execution_ready"] == ["execution_intentionally_not_supported"]
    assert touch["live_market"]["timestamps"]["canonical"] == NOW.isoformat()


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


def test_strategy_id_changes_when_confirmation_window_changes() -> None:
    confirmed_market = _market(price=100.7)
    confirmed_market["candles"][-2]["close"] = 100.7
    confirmed_market["candles"][-2]["high"] = 100.8
    confirmed_market["candles"][-1]["high"] = 100.8
    unconfirmed_market = _market(price=100.7)
    confirmation_15m = {"candles": [{"time": NOW.isoformat(), "close": 100.8, "partial": False}]}

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
        canonical_market_15m={"candles": [{"time": NOW.isoformat(), "close": 100.8, "partial": False}]},
        options_decision=_options_with_levels(),
    )

    assert payload["market_state"]["latest_price_event"]["event_type"] == "accepted_break"
    assert payload["market_state"]["confirmation_15m"] == {
        "confirmed": True,
        "close": 100.8,
        "timestamp": NOW.isoformat(),
    }
    assert payload["strategy_status"] == "TRIGGERED"
    assert payload["active_scenario"] == "long"
    assert payload["setups"][0]["stop_reference"] < payload["setups"][0]["reference_level"]["value"]
    assert payload["no_trade"]["reasons"] == []
    assert payload["no_trade"]["waiting_conditions"] == []
    assert payload["feasibility"]["execution_ready"] is False


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
        canonical_market=_market(latest_at=NOW - timedelta(seconds=601)),
        event_observation=event,
    )

    assert payload["strategy_status"] == "SUSPENDED_DATA"
    assert payload["event_overlay"]["recompute_candidate"] is True
    assert payload["event_overlay"]["status"] == "eligible"
