from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsInput
from apps.analysis.gold_policy.runtime_controls import (
    build_gold_daily_close_runtime_controls,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshot, FeatureSnapshotV2
from tests.analysis.test_gold_key_level_policy import AS_OF, _event, _spec


FIXTURE = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "readiness_v2" / "ready.json"
V1_FIXTURE = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "feature_snapshot_v1_bullish_2025-01-17.json"


def _payload() -> dict:
    return deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["input"])


def _snapshot(payload: dict | None = None) -> FeatureSnapshotV2:
    built = build_feature_snapshot(payload or _payload())
    assert isinstance(built, FeatureSnapshotV2)
    return built


def _v1_snapshot(payload: dict | None = None) -> FeatureSnapshot:
    if payload is None:
        payload = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    built = build_feature_snapshot(payload)
    assert isinstance(built, FeatureSnapshot)
    return built


def test_v2_controls_are_deterministic_and_bind_the_current_feature() -> None:
    current = _snapshot()

    first = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )
    second = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert first == second
    assert first.options_regime.source_snapshot_id == current.snapshot_id
    assert first.transition_evidence.scope.value == "daily_close"
    assert first.transition_evidence.delta_kind.value == "no_op"
    assert first.key_levels == ()
    assert first.reason_codes == ("KEY_LEVEL_CONTROLS_EMPTY_NO_FORMAL_LIFECYCLE_INPUT",)


def test_missing_optional_domains_become_explicit_unavailable_controls() -> None:
    payload = _payload()
    payload["cme_options_regime"].update(
        value=None,
        freshness_status="missing",
        quality_status="blocked",
        alignment_status="unknown",
    )
    payload["official_events"].update(
        freshness_status="missing",
        quality_status="blocked",
        alignment_status="unknown",
    )
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert controls.options_regime.regime.value == "unavailable"
    assert controls.event_risk.risk_status.value == "unavailable"
    assert "OPTIONS_REGIME_UNAVAILABLE" in controls.reason_codes
    assert "EVENT_RISK_UNAVAILABLE" in controls.reason_codes


@pytest.mark.parametrize(
    ("field", "value", "expected_quality"),
    [
        ("freshness_status", "stale", "observe"),
        ("quality_status", "observe", "observe"),
        ("alignment_status", "unknown", "observe"),
        ("alignment_status", "misaligned", "blocked"),
        ("as_of", "2025-01-17T21:00:01Z", "blocked"),
    ],
)
def test_event_risk_requires_a_current_aligned_accepted_event_snapshot(
    field: str,
    value: str,
    expected_quality: str,
) -> None:
    payload = _payload()
    payload["official_events"][field] = value
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert controls.event_risk.risk_status.value == "unavailable"
    assert controls.event_risk.quality_status == expected_quality
    assert controls.event_risk.active_event_ids == ()
    assert "EVENT_RISK_UNAVAILABLE" in controls.reason_codes


def test_future_event_source_reference_cannot_be_silently_dropped() -> None:
    payload = _payload()
    payload["official_events"]["source_refs"][0]["retrieved_at"] = "2025-01-17T21:00:01Z"
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of + timedelta(hours=1),
    )

    assert controls.event_risk.risk_status.value == "unavailable"
    assert controls.event_risk.quality_status == "blocked"
    assert controls.event_risk.active_event_ids == ()


def test_event_risk_preserves_all_eligible_typed_event_references() -> None:
    current = _snapshot()

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    references = {(ref.source, ref.reference) for ref in controls.event_risk.source_refs}
    assert references == {
        ("official_calendar", "calendar://2025-01-17"),
        ("federal_reserve", "official://fomc/2025-01-17"),
        ("formal_market", "market://xauusd/2025-01-17/reaction"),
    }


def test_accepted_empty_event_snapshot_clears_event_risk() -> None:
    payload = _payload()
    payload["official_events"]["events"] = []
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert controls.event_risk.risk_status.value == "clear"
    assert controls.event_risk.quality_status == "accepted"
    assert controls.event_risk.active_event_ids == ()
    assert {(ref.source, ref.reference) for ref in controls.event_risk.source_refs} == {
        ("official_calendar", "calendar://2025-01-17"),
    }


def test_stale_empty_event_snapshot_cannot_clear_event_risk() -> None:
    payload = _payload()
    payload["official_events"].update(
        events=[],
        freshness_status="stale",
        quality_status="accepted",
        alignment_status="unknown",
    )
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert controls.event_risk.risk_status.value == "unavailable"
    assert controls.event_risk.quality_status == "observe"
    assert controls.event_risk.active_event_ids == ()


def test_future_reaction_reference_blocks_even_when_runtime_decision_is_later() -> None:
    payload = _payload()
    payload["official_events"]["events"][0]["reaction_source_refs"][0]["retrieved_at"] = (
        "2025-01-17T21:00:01Z"
    )
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of + timedelta(hours=1),
    )

    assert controls.event_risk.risk_status.value == "unavailable"
    assert controls.event_risk.quality_status == "blocked"
    assert controls.event_risk.active_event_ids == ()
    assert all(ref.reference != "market://xauusd/2025-01-17/reaction" for ref in controls.event_risk.source_refs)


def test_no_eligible_event_reference_uses_current_input_snapshot_passport() -> None:
    payload = _payload()
    for ref in payload["official_events"]["source_refs"]:
        ref["retrieved_at"] = "2025-01-17T22:00:01Z"
    for event in payload["official_events"]["events"]:
        for ref in (*event["source_refs"], *event["reaction_source_refs"]):
            ref["retrieved_at"] = "2025-01-17T22:00:01Z"
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of + timedelta(hours=1),
    )

    assert controls.event_risk.risk_status.value == "unavailable"
    assert controls.event_risk.quality_status == "blocked"
    assert len(controls.event_risk.source_refs) == 1
    fallback_ref = controls.event_risk.source_refs[0]
    assert fallback_ref.source == "input_snapshot"
    assert fallback_ref.reference == current.snapshot_id
    assert fallback_ref.retrieved_at == current.as_of


def test_v1_event_eligibility_retains_decision_as_of_cutoff() -> None:
    payload = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    payload["official_events"].update(
        events=[
            {
                "event_id": "v1-event-after-feature-cutoff",
                "title": "Legacy event",
                "occurred_at": "2025-01-17T21:05:00Z",
                "reaction_status": "unconfirmed",
                "source_refs": [
                    {
                        "source": "legacy_calendar",
                        "reference": "calendar://v1/event-after-feature-cutoff",
                        "retrieved_at": "2025-01-17T21:05:00Z",
                    }
                ],
            }
        ],
        as_of="2025-01-17T21:05:00Z",
        source_refs=[
            {
                "source": "legacy_calendar",
                "reference": "calendar://v1/2025-01-17",
                "retrieved_at": "2025-01-17T21:05:00Z",
            }
        ],
    )
    current = _v1_snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of + timedelta(minutes=10),
    )

    assert controls.event_risk.risk_status.value == "watch"
    assert controls.event_risk.quality_status == "accepted"
    assert controls.event_risk.active_event_ids == ("v1-event-after-feature-cutoff",)


def test_unconfirmed_current_event_remains_a_watch() -> None:
    payload = _payload()
    payload["official_events"]["events"][0]["reaction_status"] = "unconfirmed"
    current = _snapshot(payload)

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
    )

    assert controls.event_risk.risk_status.value == "watch"
    assert controls.event_risk.quality_status == "accepted"
    assert controls.event_risk.active_event_ids == ("FOMC-2025-01-17",)


def test_controls_reject_a_different_decision_session() -> None:
    current = _snapshot()

    with pytest.raises(ValueError, match="share a UTC session date"):
        build_gold_daily_close_runtime_controls(
            current_feature=current,
            previous_feature=None,
            decision_as_of=current.as_of.replace(day=current.as_of.day + 1),
        )


def test_typed_key_level_lifecycle_input_is_bound_into_runtime_controls() -> None:
    payload = json.loads(json.dumps(_payload()).replace("2025-01-17", "2026-07-29"))
    current = _snapshot(payload)
    spec = _spec()
    event = _event(
        "discover",
        spec=spec,
        source_role="jin10_supplemental",
        factors=("level_proposal",),
        as_of=AS_OF,
    )

    controls = build_gold_daily_close_runtime_controls(
        current_feature=current,
        previous_feature=None,
        decision_as_of=current.as_of,
        key_level_controls_input=KeyLevelControlsInput(
            decision_as_of=current.as_of,
            scope="daily_close",
            ordered_events=(event,),
        ),
    )

    assert len(controls.key_levels) == 1
    assert controls.key_level_decisions == controls.key_level_proof
    assert controls.reason_codes == ("PROPOSAL_ONLY_SOURCE",)
