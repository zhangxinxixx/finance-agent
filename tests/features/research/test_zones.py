from __future__ import annotations

from apps.features.research.zones import build_execution_zones


LEVELS = [
    {
        "price": 2500.0,
        "instrument": "XAUUSD spot",
        "role": "support",
        "status": "Active",
        "eligible_for_target": True,
        "source_type": "technical.key_levels",
        "source_date": "2026-09-08",
        "source_refs": [{"source": "spot", "reference": "fixture:spot"}],
    },
    {
        "price": 2530.0,
        "instrument": "XAUUSD spot",
        "role": "resistance",
        "status": "Active",
        "eligible_for_target": True,
        "source_type": "technical.key_levels",
        "source_date": "2026-09-08",
        "source_refs": [{"source": "spot", "reference": "fixture:spot"}],
    },
    {
        "price": 2515.0,
        "instrument": "GC futures",
        "role": "resistance",
        "status": "Active",
        "eligible_for_target": True,
        "source_type": "cme.options.wall",
        "source_refs": [{"source": "CME", "reference": "fixture:cme"}],
    },
]


def _snapshot(**technical_values: float) -> dict:
    return {
        "trade_date": "2026-09-08",
        "technical": {
            "data": {
                **technical_values,
                "source_refs": [{"source": "technical", "reference": "fixture:technical"}],
            }
        },
    }


def test_zones_use_observed_inputs_and_keep_futures_out_of_spot_execution() -> None:
    result = build_execution_zones(
        _snapshot(atr14=100.0, spread=0.5, intraday_vol=3.0, source_dispersion=2.0),
        LEVELS,
    )

    support = next(item for item in result["zones"] if item["role"] == "support")
    assert result["status"] == "available"
    assert (
        result["zone_method"]
        == "execution_zones.width_policy.v1:max_scaled_observed_atr0.1_spread1_intraday_vol0.5_source_dispersion1"
    )
    assert support["lower"] == 2490.0
    assert support["upper"] == 2510.0
    assert support["raw_lower"] == 2490.0
    assert support["display_lower"] == 2490
    assert support["display_upper"] == 2510
    assert support["display_label"] == "2490-2510"
    assert result["excluded_levels"] == [{"price": 2515.0, "reason": "futures_or_non_spot_level"}]
    assert support["eligible_for_target"] is True


def test_missing_spread_and_dispersion_remain_explicitly_missing() -> None:
    result = build_execution_zones(_snapshot(atr14=100.0), LEVELS[:1])

    assert result["status"] == "available"
    assert result["inputs"]["spread"] is None
    assert result["inputs"]["source_dispersion"] is None
    assert set(result["missing_inputs"]) == {"spread", "intraday_vol", "source_dispersion"}
    assert "spread" not in result["zone_method"]


def test_zero_atr_without_any_other_positive_width_is_unavailable() -> None:
    result = build_execution_zones(_snapshot(atr14=0.0, spread=0.0, intraday_vol=0.0), LEVELS[:1])

    zone = result["zones"][0]
    assert result["status"] == "unavailable"
    assert zone["zone_status"] == "unavailable"
    assert zone["lower"] is None and zone["upper"] is None
    assert zone["eligible_for_target"] is False


def test_role_multipliers_and_holiday_confidence_are_rules_with_clear_bounds() -> None:
    result = build_execution_zones(
        _snapshot(atr14=100.0),
        LEVELS[:2],
        {"session_class": "HOLIDAY", "confidence_multiplier": 0.7},
        role_multipliers={"support": 1.0, "resistance": 0.5},
    )

    support, resistance = result["zones"]
    assert support["width"] == 10.0
    assert resistance["width"] == 5.0
    assert support["holiday_confidence_multiplier"] == 0.7
    assert support["confidence"] < 0.7
    assert "收盘有效跌破" in support["invalidation"]
    assert "收盘有效站上" in resistance["invalidation"]
    assert result["confidence_note"].endswith("not a calibrated probability")


def test_holiday_level_is_discounted_exactly_once_in_level_to_zone_chain() -> None:
    raw_level = {
        **LEVELS[0],
        "base_confidence": 0.65,
        "confidence": 0.65,
    }
    adjusted_level = {
        **raw_level,
        "confidence": 0.455,
        "confidence_multiplier": 0.7,
        "session_confidence_applied": True,
    }
    snapshot = _snapshot(
        atr14=100.0,
        spread=1.0,
        intraday_vol=10.0,
        source_dispersion=2.0,
    )
    session = {"session_class": "HOLIDAY", "confidence_multiplier": 0.7}

    direct = build_execution_zones(snapshot, [raw_level], session)["zones"][0]
    chained = build_execution_zones(snapshot, [adjusted_level], session)["zones"][0]

    assert direct["confidence"] == 0.455
    assert chained["confidence"] == direct["confidence"]
