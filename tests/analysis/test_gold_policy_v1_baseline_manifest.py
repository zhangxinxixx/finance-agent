from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import TransitionEvidence
from apps.analysis.gold_policy.strategy_schemas import (
    build_strategy_event_risk,
    build_strategy_options_regime,
)


_ROOT = Path(__file__).parents[2]
_MANIFEST = _ROOT / "tests/fixtures/gold_policy/v1_baseline_manifest.json"
_FIXTURE_PATHS = (
    "tests/fixtures/evaluation/replay/five_day_boundary_cases.json",
    "tests/fixtures/gold_consistency/v1_gate_cases.json",
    "tests/fixtures/gold_policy/feature_snapshot_v1_bearish_2025-01-21.json",
    "tests/fixtures/gold_policy/feature_snapshot_v1_blocked_2025-01-22.json",
    "tests/fixtures/gold_policy/feature_snapshot_v1_bullish_2025-01-17.json",
    "tests/fixtures/gold_policy/feature_snapshot_v1_event_flat_2025-01-29.json",
    "tests/fixtures/gold_policy/feature_snapshot_v1_mixed_2025-01-24.json",
    "tests/fixtures/gold_daily_close/feature_snapshot_v1_blocked_2025-01-30.json",
    "tests/fixtures/gold_daily_close/feature_snapshot_v1_ordinary_2025-01-28.json",
    "tests/fixtures/gold_daily_close/five_day_chain_v1.json",
    "tests/fixtures/gold_key_levels/v1_lifecycle_sequences.json",
    "tests/fixtures/gold_state/v1_transition_cases.json",
    "tests/fixtures/gold_strategy/v1_decision_cases.json",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_model(model: Any) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot(relative_path: str):
    return build_feature_snapshot(
        json.loads((_ROOT / relative_path).read_text(encoding="utf-8"))
    )


def _source_ref(name: str, as_of) -> SourceReference:
    return SourceReference(
        source=name,
        reference=f"fixture://gold-policy-v1-baseline/{name}/{as_of.isoformat()}",
        retrieved_at=as_of,
    )


def _representative_outputs() -> dict[str, str]:
    previous = _snapshot(
        "tests/fixtures/gold_policy/feature_snapshot_v1_bullish_2025-01-17.json"
    )
    current = _snapshot(
        "tests/fixtures/gold_policy/feature_snapshot_v1_bearish_2025-01-21.json"
    )
    decision_as_of = current.as_of + timedelta(minutes=5)
    source_refs = (_source_ref("runtime-controls", decision_as_of),)
    evidence = TransitionEvidence.model_validate(
        {
            "evidence_id": "evidence:gold-policy-v1-baseline:ordinary",
            "scope": "daily_close",
            "delta_kind": "ordinary",
            "as_of": decision_as_of,
            "evidence_categories": ("macro",),
            "source_refs": source_refs,
        }
    )
    options_regime = build_strategy_options_regime(
        {
            "source_snapshot_id": current.snapshot_id,
            "as_of": decision_as_of,
            "regime": "normal",
            "directional_bias": "bearish",
            "freshness_status": "fresh",
            "quality_status": "accepted",
            "alignment_status": "aligned",
            "source_refs": source_refs,
        }
    )
    event_risk = build_strategy_event_risk(
        {
            "as_of": decision_as_of,
            "risk_status": "clear",
            "quality_status": "accepted",
            "source_refs": source_refs,
        }
    )
    result = evaluate_gold_daily_close_loop(
        DailyCloseLoopInput(
            decision_as_of=decision_as_of,
            current_feature=current,
            previous_feature=previous,
            transition_evidence=evidence,
            options_regime=options_regime,
            event_risk=event_risk,
        )
    )

    assert result.analysis_state is not None
    assert result.candidate_strategy is not None
    assert result.consistency_decision is not None
    return {
        "analysis_decision_sha256": _sha256_model(result.analysis_decision),
        "feature_snapshot_id": current.snapshot_id,
        "price_attribution_sha256": _sha256_model(
            attribute_gold_price(current, previous)
        ),
        "state_id": result.analysis_state.state_id,
        "strategy_decision_id": result.candidate_strategy.decision_id,
        "consistency_decision_id": result.consistency_decision.decision_id,
        "transition_decision_hash": result.transition_decision.decision_hash,
        "daily_close_result_id": result.result_id,
        "daily_close_result_hash": result.result_hash,
    }


def _expected_fixture_hashes() -> dict[str, str]:
    return {path: _sha256_file(_ROOT / path) for path in _FIXTURE_PATHS}


def test_gold_policy_v1_baseline_manifest_freezes_version_scoped_contract() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == "gold_policy_v1_baseline_manifest.v1"
    assert manifest["feature_snapshot_schema_version"] == "feature_snapshot.v1"
    assert manifest["policy_versions"] == {
        "analysis": "gold_analysis_policy.v1",
        "attribution": "gold_price_attribution.v1",
        "consistency": "analysis_strategy_consistency_policy.v1",
        "daily_close_loop": "gold_daily_close_loop_policy.v1",
        "key_level_lifecycle": "key_level_lifecycle_policy.v1",
        "state": "analysis_state.v1",
        "state_transition": "analysis_state_transition_policy.v1",
        "strategy": "gold_strategy_policy.v1",
    }
    assert manifest["reviewed_update_reason"].strip()
    assert manifest["upgrade_policy"] == {
        "v2_requires_new_manifest": True,
        "v1_manifest_is_immutable": True,
    }
    assert manifest["fixture_sha256"] == _expected_fixture_hashes()

    first = _representative_outputs()
    second = _representative_outputs()
    assert second == first
    assert manifest["representative_outputs"] == first
