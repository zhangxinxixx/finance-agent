from apps.analysis.services.market_odds_comparison import compare_market_odds


def _event(probability: float) -> dict:
    return {
        "asset": "XAUUSD",
        "event_type": "price_level",
        "predicate": "touch_above",
        "target_value": 4200.0,
        "target_unit": "USD_per_oz",
        "probability_semantics": "ever_touch_before_horizon",
        "horizon_start": "2026-07-03",
        "horizon_end": "2026-07-31",
        "observed_at": "2026-07-03T14:00:00+08:00",
        "probability": probability,
        "evidence_refs": [{"source_ref": "fixture"}],
    }


def test_identical_events_support_without_aggregation() -> None:
    result = compare_market_odds(external=_event(0.94), internal=_event(0.87))
    assert result["comparison_status"] == "supports"
    assert result["probability_gap"] == 0.07
    assert result["aggregation_allowed"] is False
    assert "aggregate_probability" not in result


def test_large_probability_gap_conflicts() -> None:
    result = compare_market_odds(external=_event(0.94), internal=_event(0.60))
    assert result["comparison_status"] == "conflicts"


def test_semantics_horizon_target_or_unit_mismatch_is_not_comparable() -> None:
    for field, value in (
        ("probability_semantics", "above_at_expiry"),
        ("horizon_end", "2026-08-31"),
        ("target_value", 4300.0),
        ("target_unit", "CNY_per_gram"),
    ):
        internal = _event(0.87)
        internal[field] = value
        result = compare_market_odds(external=_event(0.94), internal=internal)
        assert result["comparison_status"] == "not_comparable"
        assert result["aggregation_allowed"] is False


def test_missing_or_distant_observation_time_is_not_comparable() -> None:
    missing = _event(0.87)
    missing.pop("observed_at")
    assert compare_market_odds(external=_event(0.94), internal=missing)["reason_codes"] == [
        "observation_time_missing_or_invalid"
    ]

    distant = _event(0.87)
    distant["observed_at"] = "2026-07-05T14:00:01+08:00"
    result = compare_market_odds(external=_event(0.94), internal=distant)
    assert result["comparison_status"] == "not_comparable"
    assert result["reason_codes"] == ["observation_time_not_close"]
