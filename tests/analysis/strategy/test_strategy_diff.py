from __future__ import annotations

from apps.analysis.strategy.strategy_diff import DIFF_SCHEMA_VERSION, diff_live_strategy


def _strategy() -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "strategy_id": "strategy-a",
        "strategy_version": "live_strategy.rules.v2",
        "strategy_status": "WATCHING",
        "updated_at": "2026-07-18T09:00:00+00:00",
        "market_state": {
            "nearest_level": {"role": "primary_support", "value": 2360.0},
            "key_levels": [{"role": "primary_support", "value": 2360.0}],
        },
        "setups": [
            {
                "direction": "long",
                "risk_reward": {"tp1": 2380.0, "tp2": 2400.0},
                "stop_reference": 2348.0,
            }
        ],
        "event_overlay": {"status": "unavailable", "observed_at": "2026-07-18T08:59:00+00:00"},
    }


def test_identical_models_are_stable_and_ignore_only_top_level_updated_at() -> None:
    previous = _strategy()
    current = _strategy()
    current["updated_at"] = "2026-07-18T09:05:00+00:00"

    first = diff_live_strategy(previous, current)
    second = diff_live_strategy(previous, current)

    assert first == second
    assert first["schema_version"] == DIFF_SCHEMA_VERSION
    assert first["changed"] is False
    assert first["changes"] == []


def test_nested_decision_changes_and_event_overlay_are_visible() -> None:
    previous = _strategy()
    current = _strategy()
    current["strategy_status"] = "ARMED"
    current["market_state"]["nearest_level"]["value"] = 2362.0
    current["market_state"]["key_levels"].append({"role": "gamma_flip", "value": 2370.0})
    current["setups"][0]["risk_reward"]["tp1"] = 2382.0
    current["event_overlay"] = {"status": "eligible", "recompute_candidate": True}

    diff = diff_live_strategy(previous, current)
    paths = {change["path"] for change in diff["changes"]}

    assert diff["changed"] is True
    assert diff["from_strategy_id"] == "strategy-a"
    assert diff["to_strategy_id"] == "strategy-a"
    assert "strategy_status" in paths
    assert "market_state.nearest_level.value" in paths
    assert "market_state.key_levels[1]" in paths
    assert "setups[0].risk_reward.tp1" in paths
    assert "event_overlay.status" in paths
    assert "event_overlay.recompute_candidate" in paths


def test_missing_fields_are_explicit_and_list_order_is_semantic() -> None:
    previous = {"strategy_id": "a", "strategy_version": "v1", "setups": [{"direction": "long"}]}
    current = {"strategy_id": "b", "strategy_version": "v2", "setups": [{"direction": "short"}, {"direction": "long"}]}

    diff = diff_live_strategy(previous, current)
    by_path = {change["path"]: change for change in diff["changes"]}

    assert by_path["strategy_id"]["old_value"] == "a"
    assert by_path["strategy_id"]["new_value"] == "b"
    assert by_path["setups[0].direction"]["old_value"] == "long"
    assert by_path["setups[0].direction"]["new_value"] == "short"
    assert by_path["setups[1]"]["old_present"] is False
    assert by_path["setups[1]"]["new_present"] is True


def test_nested_missing_value_is_not_hidden_by_timestamp_allowlist() -> None:
    previous = {"event_overlay": {"observed_at": "2026-07-18T08:00:00+00:00"}}
    current = {"event_overlay": {"observed_at": "2026-07-18T08:05:00+00:00"}}

    diff = diff_live_strategy(previous, current)

    assert diff["changed"] is True
    assert diff["changes"][0]["path"] == "event_overlay.observed_at"


def test_same_content_with_different_mapping_insertion_order_has_same_diff_id() -> None:
    previous = {"strategy_id": "a", "market_state": {"b": 2, "a": 1}}
    current = {"strategy_id": "b", "market_state": {"a": 1, "b": 3}}
    reordered_previous = {"market_state": {"a": 1, "b": 2}, "strategy_id": "a"}
    reordered_current = {"market_state": {"b": 3, "a": 1}, "strategy_id": "b"}

    assert diff_live_strategy(previous, current)["diff_id"] == diff_live_strategy(
        reordered_previous, reordered_current
    )["diff_id"]
