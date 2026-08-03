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


def _v2(snapshot, **changes):
    payload = snapshot.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    direct = payload.pop("real10y")
    direct["market_role"] = "real_yield_direct"
    payload.update(schema_version="feature_snapshot.v2", real10y_direct=direct)
    for field, values in changes.items():
        payload[field].update(values)
    _clamp_source_ref_times(payload, payload["as_of"])
    return build_feature_snapshot(payload)


def _clamp_source_ref_times(value, cutoff: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_refs", "reaction_source_refs"} and isinstance(child, list):
                for reference in child:
                    if isinstance(reference, dict):
                        reference["retrieved_at"] = cutoff
            else:
                _clamp_source_ref_times(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            _clamp_source_ref_times(child, cutoff)


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
    assert "real10y_cross_check" not in decision.model_dump(mode="json")


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


def test_forged_v2_readiness_cannot_bypass_analysis_gate() -> None:
    previous = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(
        _snapshot("feature_snapshot_v1_bearish_2025-01-21.json"),
        us10y={
            "value": None,
            "freshness_status": "missing",
            "quality_status": "blocked",
            "alignment_status": "unknown",
        },
    )
    assert current.data_quality.analysis_readiness == "blocked"
    forged_quality = current.data_quality.model_copy(
        update={"analysis_readiness": "ready", "strategy_readiness": "ready"}
    )
    forged = current.model_copy(update={"data_quality": forged_quality})

    decision = evaluate_gold_analysis_policy(forged, previous)

    assert decision.direction == "unavailable"
    assert decision.quality_status == "blocked"
    assert decision.conflicts == ("FEATURE_SNAPSHOT_DERIVATION_INVALID",)


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


def test_v2_direct_changes_do_not_change_directional_real_yield_driver() -> None:
    baseline = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
    )
    direct_only = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
        real10y_direct={"value": 1.10},
    )

    expected = evaluate_gold_analysis_policy(current, baseline)
    changed = evaluate_gold_analysis_policy(direct_only, baseline)

    assert changed.direction == expected.direction == "bullish"
    assert [driver.model_dump() for driver in changed.dominant_drivers] == [
        driver.model_dump() for driver in expected.dominant_drivers
    ]
    real_driver = next(driver for driver in changed.dominant_drivers if driver.factor == "real_yield")
    expected_refs = {
        (ref.source, ref.reference, ref.retrieved_at)
        for observation in (baseline.real10y_estimated, current.real10y_estimated)
        for ref in observation.source_refs
    }
    assert {(ref.source, ref.reference, ref.retrieved_at) for ref in real_driver.source_refs} == expected_refs


def test_v2_estimated_change_can_change_direction_and_diverged_cross_check_downgrades_quality() -> None:
    baseline = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    estimated_changed = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
    )
    diverged = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
        real10y_direct={"value": 1.00},
    )

    accepted = evaluate_gold_analysis_policy(estimated_changed, baseline)
    guarded = evaluate_gold_analysis_policy(diverged, baseline)

    assert evaluate_gold_analysis_policy(baseline, baseline).direction == "neutral"
    assert accepted.direction == guarded.direction == "bullish"
    assert accepted.quality_status == "accepted"
    assert guarded.quality_status == "observe"
    assert "REAL10Y_BASIS_DIVERGED" in guarded.conflicts
    assert guarded.confidence < accepted.confidence


def test_v2_missing_direct_keeps_valid_estimated_direction_with_cross_check_downgrade() -> None:
    baseline = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    missing_direct = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
        real10y_direct={
            "value": None,
            "freshness_status": "missing",
            "quality_status": "blocked",
            "alignment_status": "unknown",
        },
    )

    decision = evaluate_gold_analysis_policy(missing_direct, baseline)

    assert decision.direction == "bullish"
    assert decision.quality_status == "observe"
    assert "REAL10Y_DIRECT_CROSS_CHECK_UNAVAILABLE" in decision.conflicts
    assert decision.real10y_cross_check is not None
    assert decision.real10y_cross_check.source_refs == missing_direct.real10y_direct.source_refs


def test_v2_current_with_v1_previous_fails_closed_without_falling_back_to_v1() -> None:
    v1_previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    v2_current = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={"value": 4.55},
        broad_dollar={"value": 120.60},
    )

    decision = evaluate_gold_analysis_policy(v2_current, v1_previous)
    reverse = evaluate_gold_analysis_policy(v1_previous, _v2(v1_previous))

    assert decision.policy_version == "gold_analysis_policy.v2"
    assert decision.direction == "unavailable"
    assert decision.quality_status == "blocked"
    assert decision.conflicts == ("FEATURE_SNAPSHOT_SCHEMA_TRANSITION_NO_DELTA",)
    assert not decision.dominant_drivers
    assert not decision.counter_drivers
    assert "REAL10Y_SCHEMA_TRANSITION_NO_DELTA" in reverse.conflicts


def test_v2_cross_check_lineage_is_separate_from_estimated_directional_refs() -> None:
    baseline = _v2(_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"))
    current = _v2(
        _snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        us10y={
            "value": 4.55,
            "source_refs": [{"source": "fred", "reference": "fred://US10Y", "retrieved_at": "2025-01-17T20:00:00Z"}],
        },
        t10yie={
            "source_refs": [{"source": "fred", "reference": "fred://T10YIE", "retrieved_at": "2025-01-17T20:00:00Z"}],
        },
        real10y_direct={
            "source_refs": [{"source": "fred", "reference": "fred://DFII10", "retrieved_at": "2025-01-17T20:00:00Z"}],
        },
    )

    decision = evaluate_gold_analysis_policy(current, baseline)
    real_driver = next(driver for driver in decision.dominant_drivers if driver.factor == "real_yield")

    assert decision.real10y_cross_check is not None
    assert {ref.reference for ref in decision.real10y_cross_check.source_refs} == {"fred://DFII10"}
    assert "real10y_cross_check" in decision.model_dump(mode="json")
    assert "fred://DFII10" not in {ref.reference for ref in real_driver.source_refs}
    assert {"fred://US10Y", "fred://T10YIE"} <= {ref.reference for ref in real_driver.source_refs}
