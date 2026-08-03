from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from apps.analysis.gold_policy.daily_close_runtime import (
    GoldDailyCloseRuntimeControls,
    execute_gold_daily_close_runtime,
)
from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseHeadConflictError,
    load_gold_daily_close_head,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from tests.analysis.test_gold_daily_close_store import _bootstrap_pair, _next_pair
from tests.analysis.test_gold_strategy_policy import _snapshot


def _controls(loop_input) -> GoldDailyCloseRuntimeControls:
    return GoldDailyCloseRuntimeControls(
        decision_as_of=loop_input.decision_as_of,
        transition_evidence=loop_input.transition_evidence,
        options_regime=loop_input.options_regime,
        event_risk=loop_input.event_risk,
        key_levels=loop_input.key_levels,
        key_level_decisions=loop_input.key_level_decisions,
        key_level_proof=loop_input.key_level_proof,
    )


def test_runtime_bootstraps_then_reads_the_durable_head_for_next_session(
    tmp_path: Path,
) -> None:
    bootstrap_input, bootstrap_result = _bootstrap_pair()
    first = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="runtime-bootstrap",
        current_feature=bootstrap_input.current_feature,
        controls=_controls(bootstrap_input),
        bootstrap_previous_feature=bootstrap_input.previous_feature,
    )
    head = load_gold_daily_close_head(storage_root=tmp_path).head
    next_input, next_result = _next_pair(head)
    second = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="runtime-next",
        current_feature=next_input.current_feature,
        controls=_controls(next_input),
    )

    assert first.result == bootstrap_result
    assert first.predecessor_lookup.status == "missing"
    assert second.predecessor_lookup.status == "found"
    assert second.loop_input.previous_state == first.result.analysis_state
    assert second.loop_input.previous_strategy == first.result.candidate_strategy
    assert second.result == next_result
    assert second.result.model_invocations == 0


def test_runtime_rejects_caller_previous_feature_that_conflicts_with_head(
    tmp_path: Path,
) -> None:
    bootstrap_input, _ = _bootstrap_pair()
    execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="runtime-bootstrap",
        current_feature=bootstrap_input.current_feature,
        controls=_controls(bootstrap_input),
        bootstrap_previous_feature=bootstrap_input.previous_feature,
    )
    head = load_gold_daily_close_head(storage_root=tmp_path).head
    next_input, _ = _next_pair(head)

    with pytest.raises(DailyCloseHeadConflictError, match="caller previous feature"):
        execute_gold_daily_close_runtime(
            storage_root=tmp_path,
            run_id="runtime-conflict",
            current_feature=next_input.current_feature,
            controls=_controls(next_input),
            bootstrap_previous_feature=_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
        )


def test_runtime_fails_closed_when_predecessor_store_is_invalid(tmp_path: Path) -> None:
    bootstrap_input, _ = _bootstrap_pair()
    broken = tmp_path / "analysis/gold_mainlines/2025-01-20/run-broken/daily_close"
    broken.mkdir(parents=True)

    with pytest.raises(DailyCloseHeadConflictError, match="predecessor lookup failed"):
        execute_gold_daily_close_runtime(
            storage_root=tmp_path,
            run_id="runtime-invalid",
            current_feature=bootstrap_input.current_feature,
            controls=_controls(bootstrap_input),
            bootstrap_previous_feature=bootstrap_input.previous_feature,
        )


def test_runtime_commits_linked_same_session_revision_and_selects_latest(
    tmp_path: Path,
) -> None:
    bootstrap_input, _ = _bootstrap_pair()
    first = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="runtime-revision-1",
        current_feature=bootstrap_input.current_feature,
        controls=_controls(bootstrap_input),
        bootstrap_previous_feature=bootstrap_input.previous_feature,
    )
    payload = bootstrap_input.current_feature.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    revised_as_of = bootstrap_input.current_feature.as_of + timedelta(hours=1)
    payload["as_of"] = revised_as_of.isoformat()
    payload["xauusd_spot"]["value"] += 1.0
    payload["xauusd_spot"]["as_of"] = revised_as_of.isoformat()
    revised = build_feature_snapshot(payload)
    controls = build_gold_daily_close_runtime_controls(
        current_feature=revised,
        previous_feature=bootstrap_input.current_feature,
        previous_transition=first.result.transition_decision,
        decision_as_of=revised_as_of + timedelta(minutes=5),
    )

    second = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="runtime-revision-2",
        current_feature=revised,
        controls=controls,
    )
    lookup = load_gold_daily_close_head(storage_root=tmp_path)

    assert first.write_result.revision_no == 1
    assert second.write_result.revision_no == 2
    assert lookup.status == "found"
    assert lookup.latest_receipt is not None
    assert lookup.latest_receipt.revision_no == 2
    assert lookup.latest_receipt.finalization_status == "finalized"
    assert lookup.latest_receipt.supersedes_receipt_id == first.write_result.receipt_id
    assert lookup.head is not None
    assert lookup.head.feature_snapshot == revised
