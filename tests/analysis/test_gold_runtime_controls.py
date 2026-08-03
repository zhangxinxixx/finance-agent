from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.runtime_controls import (
    build_gold_daily_close_runtime_controls,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotV2


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "gold_policy"
    / "readiness_v2"
    / "ready.json"
)


def _payload() -> dict:
    return deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["input"])


def _snapshot(payload: dict | None = None) -> FeatureSnapshotV2:
    built = build_feature_snapshot(payload or _payload())
    assert isinstance(built, FeatureSnapshotV2)
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


def test_controls_reject_a_different_decision_session() -> None:
    current = _snapshot()

    with pytest.raises(ValueError, match="share a UTC session date"):
        build_gold_daily_close_runtime_controls(
            current_feature=current,
            previous_feature=None,
            decision_as_of=current.as_of.replace(day=current.as_of.day + 1),
        )
