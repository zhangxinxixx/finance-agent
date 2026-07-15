from __future__ import annotations

from apps.analysis.strategy.risk_plan import build_risk_plan


LEVELS = [
    {"reference_price": 98.0, "role": "primary_support", "strength": 7.0},
    {"reference_price": 100.0, "role": "primary_resistance", "strength": 8.0},
    {"reference_price": 103.0, "role": "secondary_resistance", "strength": 6.0},
    {"reference_price": 105.0, "role": "tail_protection", "strength": 4.0},
]


def _event(direction: str = "above") -> dict:
    return {"event_type": "accepted_break", "direction": direction, "confirmed": True, "related_level": {"role": "primary_resistance", "value": 100.0, "strength": 8.0}}


def test_long_and_short_stops_are_on_correct_sides_and_targets_are_levels() -> None:
    long_plan = build_risk_plan(price=100.7, key_levels=LEVELS, atr14=2.0, latest_price_event=_event())
    short_plan = build_risk_plan(price=99.3, key_levels=LEVELS, atr14=2.0, latest_price_event=_event("below"))
    long_setup, short_setup = long_plan["setups"]

    assert long_setup["stop_reference"] < long_setup["reference_level"]["value"]
    assert short_plan["setups"][1]["stop_reference"] > short_plan["setups"][1]["reference_level"]["value"]
    assert {target["price"] for target in long_setup["targets"]}.issubset({item["reference_price"] for item in LEVELS})
    assert short_setup["status"] == "watching"


def test_rr_gate_blocks_trigger_and_result_is_deterministic() -> None:
    levels = [{"reference_price": 100.0, "role": "primary_resistance", "strength": 8.0}, {"reference_price": 100.4, "role": "secondary_resistance", "strength": 6.0}]
    first = build_risk_plan(price=100.7, key_levels=levels, atr14=2.0, latest_price_event=_event())
    second = build_risk_plan(price=100.7, key_levels=levels, atr14=2.0, latest_price_event=_event())

    assert first == second
    assert first["setups"][0]["status"] == "blocked_rr"
    assert "risk_reward_insufficient" in first["setups"][0]["gate"]["reasons"]
    assert first["active_scenario"] == "no_trade"
    assert first["no_trade"]["range"] is None
    assert "risk_reward_gate_required" in first["no_trade"]["waiting_conditions"]


def test_no_trade_range_uses_only_existing_support_and_resistance() -> None:
    plan = build_risk_plan(price=100.7, key_levels=LEVELS, atr14=2.0, latest_price_event=None)

    assert plan["no_trade"]["range"] == [98.0, 103.0]
    assert "confirmed_price_event_required" in plan["no_trade"]["waiting_conditions"]
