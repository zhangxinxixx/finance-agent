from __future__ import annotations

from apps.features.research.scenario_display import build_scenario_display


def test_rule_weights_are_normalized_to_five_percent_buckets_and_raw_values_stay() -> None:
    scenarios = [
        {"id": "main", "weight": 0.50, "trigger": "价格区间保持"},
        {"id": "bull", "weight": 0.30, "trigger": "实际利率回落"},
        {"id": "bear", "weight": 0.20, "trigger": "实际利率上行"},
    ]
    result = build_scenario_display(scenarios)

    assert result["status"] == "available"
    assert [item["display_weight_pct"] for item in result["scenarios"]] == [50, 30, 20]
    assert result["display_weights_sum"] == 100
    assert result["raw_scenarios"] == scenarios
    assert result["uncalibrated"] is True
    assert result["is_probability"] is False
    assert result["calibration_status"] == "uncalibrated"
    assert result["brier_score"] is None


def test_largest_remainder_keeps_display_sum_at_100_and_level_mode_is_qualitative() -> None:
    result = build_scenario_display(
        {"main": {"weight": 1}, "bull": {"weight": 1}, "bear": {"weight": 1}},
        mode="level",
    )

    assert result["status"] == "available"
    assert [item["display_weight_pct"] for item in result["scenarios"]] == [None, None, None]
    assert [item["display_level"] for item in result["scenarios"]] == ["Medium", "Medium", "Medium"]
    assert result["weight_semantics"] == "rule_weight_display"
    assert result["note"].endswith("不是统计概率；当前没有校准或 Brier 评估。")


def test_zero_or_negative_weights_remain_raw_without_fabricated_display() -> None:
    result = build_scenario_display(
        [
            {"id": "main", "weight": 0},
            {"id": "bear", "weight": -1},
        ]
    )

    assert result["status"] == "partial"
    assert result["display_weights_sum"] is None
    assert all(item["display_weight_pct"] is None for item in result["scenarios"])
    assert result["raw_scenarios"][1]["weight"] == -1


def test_workflow_weight_pct_and_high_medium_alias_are_supported() -> None:
    result = build_scenario_display(
        {
            "scenario_engine": {
                "scenarios": [
                    {"id": "range", "weight_pct": 50},
                    {"id": "bull", "weight_pct": 30},
                    {"id": "bear", "weight_pct": 20},
                ]
            }
        },
        mode="High/Medium",
    )

    assert result["display_mode"] == "level"
    assert [item["raw_weight"] for item in result["scenarios"]] == [50, 30, 20]
    assert [item["display_level"] for item in result["scenarios"]] == ["Medium", "Medium", "Low"]
