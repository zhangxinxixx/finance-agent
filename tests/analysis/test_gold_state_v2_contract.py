from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.state_schemas import (
    AnalysisStateV2,
    build_analysis_state,
    build_analysis_state_v2,
    migrate_analysis_state_v1_to_v2,
)


AS_OF = datetime(2026, 8, 2, 21, tzinfo=UTC)


def _ref() -> dict[str, object]:
    return {"source": "fixture", "reference": "fixture://state-v2", "retrieved_at": AS_OF}


def _payload(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "direction": "mixed",
        "direction_tilt": "none",
        "market_regime": "direction_decision",
        "trend_maturity": "watching",
        "scope": "daily_close",
        "as_of": AS_OF,
        "confidence": 0.5,
        "quality_status": "accepted",
        "source_refs": [_ref()],
    }
    value.update(updates)
    return value


def test_v2_identity_is_stable_and_rejects_injection() -> None:
    state = build_analysis_state_v2(_payload())
    assert all(build_analysis_state_v2(_payload()).state_id == state.state_id for _ in range(100))
    forged = state.model_dump(mode="python")
    forged["confidence"] = 0.9
    with pytest.raises(ValidationError):
        AnalysisStateV2.model_validate(forged)


def test_mixed_supports_none_or_explicit_tilt_and_blocked_is_fail_closed() -> None:
    assert build_analysis_state_v2(_payload(direction_tilt="bullish")).direction_tilt == "bullish"
    with pytest.raises(ValidationError):
        build_analysis_state_v2(_payload(direction="bullish", direction_tilt="bullish"))
    blocked = build_analysis_state_v2(
        _payload(direction="unavailable", direction_tilt="none", confidence=0.0, quality_status="blocked")
    )
    assert blocked.pending_transition is None


def test_v1_migration_preserves_lineage_and_never_invents_tilt() -> None:
    v1 = build_analysis_state(
        {
            "stage": "direction_decision",
            "directional_bias": "mixed",
            "scope": "daily_close",
            "as_of": AS_OF,
            "confidence": 0.6,
            "quality_status": "accepted",
            "source_refs": [_ref()],
        }
    )
    migrated = migrate_analysis_state_v1_to_v2(v1)
    assert all(migrate_analysis_state_v1_to_v2(v1) == migrated for _ in range(100))
    assert migrated.direction_tilt == "none"
    assert migrated.source_refs == v1.source_refs
    assert migrated.scope == v1.scope and migrated.as_of == v1.as_of and migrated.confidence == v1.confidence
