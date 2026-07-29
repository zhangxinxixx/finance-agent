from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.analysis.gold_policy.analysis_policy import evaluate_gold_analysis_policy
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _snapshot(name: str):
    return build_feature_snapshot(_load_fixture(name))


def _with_changes(snapshot, **changes):
    payload = snapshot.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    for field, values in changes.items():
        payload[field].update(values)
    return build_feature_snapshot(payload)


@pytest.mark.parametrize(
    "name",
    [
        "feature_snapshot_v1_bullish_2025-01-17.json",
        "feature_snapshot_v1_bearish_2025-01-21.json",
        "feature_snapshot_v1_blocked_2025-01-22.json",
        "feature_snapshot_v1_mixed_2025-01-24.json",
        "feature_snapshot_v1_event_flat_2025-01-29.json",
    ],
)
def test_all_five_historical_fixtures_build_and_evaluate(name: str) -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    decision = evaluate_gold_analysis_policy(_snapshot(name), baseline)

    assert decision.policy_version == "gold_analysis_policy.v1"


def test_bullish_bearish_mixed_and_neutral_decisions() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    bullish = _with_changes(
        baseline,
        real10y={"value": 2.05},
        t10yie={"value": 2.40},
        broad_dollar={"value": 120.6},
        xauusd_spot={"value": 2712.0},
    )
    bearish = _with_changes(
        baseline,
        real10y={"value": 2.22},
        t10yie={"value": 2.29},
        broad_dollar={"value": 121.4},
        xauusd_spot={"value": 2694.0},
    )
    mixed = _with_changes(baseline, real10y={"value": 2.05}, broad_dollar={"value": 121.4})

    assert evaluate_gold_analysis_policy(bullish, baseline).direction == "bullish"
    assert evaluate_gold_analysis_policy(bearish, baseline).direction == "bearish"
    mixed_decision = evaluate_gold_analysis_policy(mixed, baseline)
    assert mixed_decision.direction == "mixed"
    assert mixed_decision.direction != "neutral"
    assert evaluate_gold_analysis_policy(baseline, baseline).direction == "neutral"


def test_blocked_input_is_unavailable_without_directional_drivers() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    decision = evaluate_gold_analysis_policy(blocked, baseline)

    assert decision.direction == "unavailable"
    assert decision.direction_tilt == "none"
    assert not decision.dominant_drivers
    assert not decision.counter_drivers

    reverse_decision = evaluate_gold_analysis_policy(baseline, blocked)
    assert reverse_decision.direction == "unavailable"
    assert reverse_decision.quality_status == "blocked"


def test_missing_previous_snapshot_fails_closed() -> None:
    current = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    decision = evaluate_gold_analysis_policy(current, None)

    assert decision.direction == "unavailable"
    assert decision.quality_status == "blocked"
    assert decision.previous_snapshot_id == "missing"
    assert decision.conflicts == ("PREVIOUS_FEATURE_SNAPSHOT_MISSING",)


def test_future_previous_snapshot_fails_closed() -> None:
    current = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    future_previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    decision = evaluate_gold_analysis_policy(current, future_previous)

    assert decision.direction == "unavailable"
    assert decision.quality_status == "blocked"
    assert decision.conflicts == ("PREVIOUS_SNAPSHOT_AFTER_CURRENT",)


def test_each_driver_has_deduplicated_current_and_previous_sources() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _with_changes(baseline, real10y={"value": 2.05})
    decision = evaluate_gold_analysis_policy(current, baseline)

    driver = decision.dominant_drivers[0]
    assert driver.source_refs
    assert len({(ref.source, ref.reference, ref.retrieved_at) for ref in driver.source_refs}) == len(driver.source_refs)


def test_same_input_is_exactly_reproducible_100_times() -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _with_changes(previous, real10y={"value": 2.05}, broad_dollar={"value": 120.6})
    expected = evaluate_gold_analysis_policy(current, previous).model_dump(mode="json")

    assert all(evaluate_gold_analysis_policy(current, previous).model_dump(mode="json") == expected for _ in range(100))


def test_nominal_yield_only_change_does_not_change_decision() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    nominal_only = _with_changes(
        baseline,
        us02y={"value": 4.55},
        us10y={"value": 5.20},
        us30y={"value": 5.35},
    )

    nominal_decision = evaluate_gold_analysis_policy(nominal_only, baseline)
    baseline_decision = evaluate_gold_analysis_policy(baseline, baseline)
    assert nominal_decision.model_dump(
        exclude={"current_snapshot_id", "previous_snapshot_id"}
    ) == baseline_decision.model_dump(exclude={"current_snapshot_id", "previous_snapshot_id"})


def test_oil_requires_same_direction_and_reports_divergence_as_conflict() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    divergent = _with_changes(baseline, wti={"value": 79.0}, brent={"value": 79.5})
    decision = evaluate_gold_analysis_policy(divergent, baseline)

    assert "OIL_BENCHMARKS_DIVERGED" in decision.conflicts
    assert all(driver.factor != "oil" for driver in decision.dominant_drivers + decision.counter_drivers)


def test_observe_readiness_is_never_upgraded_to_accepted() -> None:
    baseline = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    observe_current = _with_changes(
        baseline,
        real10y={"value": 2.05},
        etf_flow={"quality_status": "observe", "freshness_status": "stale"},
    )

    assert evaluate_gold_analysis_policy(observe_current, baseline).quality_status == "observe"
