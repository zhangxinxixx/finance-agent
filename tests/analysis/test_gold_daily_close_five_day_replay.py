from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_delivery import build_gold_daily_close_delivery
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_runtime import (
    GoldDailyCloseRuntimeControls,
    execute_gold_daily_close_runtime,
)
from apps.analysis.gold_policy.daily_close_store import load_gold_daily_close_head
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.state_transition_policy import ordinary_stage_distance
from tests.analysis.test_gold_daily_close_loop import _confirmed_support_break, _evidence
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "gold_daily_close"
    / "five_day_chain_v1.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _feature_snapshot(name: str):
    path = _FIXTURE.parent / name
    if path.is_file():
        return build_feature_snapshot(json.loads(path.read_text(encoding="utf-8")))
    return _snapshot(name)


def _run_five_day_chain(storage_root: Path):
    fixture = _fixture()
    bootstrap_previous = _feature_snapshot(fixture["bootstrap_previous_fixture"])
    executions = []
    for index, case in enumerate(fixture["days"]):
        current = _feature_snapshot(case["feature_fixture"])
        predecessor = load_gold_daily_close_head(
            storage_root=storage_root,
            before_date=current.as_of.date(),
        )
        if index == 0:
            assert predecessor.status == "missing"
            previous_feature = bootstrap_previous
        else:
            assert predecessor.status == "found"
            previous_feature = predecessor.head.feature_snapshot

        support = _policy_input(
            bias=case["options_bias"],
            feature=current,
            attribution=attribute_gold_price(current, previous_feature),
        )
        evidence = _evidence(
            support.decision_as_of,
            delta_kind=case["delta_kind"],
            categories=tuple(case["categories"]) or None,
            rule_code=case.get("rule_code"),
        )
        key_levels = ()
        key_level_decisions = ()
        key_level_proof = ()
        if case["day"] == "D4":
            broken_level, break_decision = _confirmed_support_break(
                support.decision_as_of
            )
            key_levels = (broken_level,)
            key_level_decisions = (break_decision,)
            key_level_proof = (break_decision,)
        controls = GoldDailyCloseRuntimeControls(
            decision_as_of=support.decision_as_of,
            transition_evidence=evidence,
            options_regime=support.options_regime,
            event_risk=support.event_risk,
            key_levels=key_levels,
            key_level_decisions=key_level_decisions,
            key_level_proof=key_level_proof,
        )
        execution = execute_gold_daily_close_runtime(
            storage_root=storage_root,
            run_id=f"five-day-{case['day'].lower()}",
            current_feature=current,
            controls=controls,
            bootstrap_previous_feature=(bootstrap_previous if index == 0 else None),
        )

        if index > 0:
            assert execution.predecessor_lookup.head == predecessor.head
            assert execution.loop_input.previous_feature == predecessor.head.feature_snapshot
            assert execution.loop_input.previous_policy_input == predecessor.head.strategy_policy_input
            assert execution.loop_input.previous_state == predecessor.head.analysis_state
            assert execution.loop_input.previous_transition == predecessor.head.transition_decision
            assert execution.loop_input.previous_strategy == predecessor.head.strategy_decision
        head = load_gold_daily_close_head(storage_root=storage_root)
        assert head.status == "found"
        assert head.head.feature_snapshot == current
        assert head.head.loop_result.result_id == execution.result.result_id
        assert head.latest_receipt.result_id == execution.result.result_id
        assert execution.result.model_invocations == 0
        assert execution.result.canonical_action.value == case["expected_action"]
        assert execution.result.analysis_decision.quality_status == case["expected_quality"]
        if index > 0:
            assert head.latest_receipt.predecessor_receipt_id == predecessor.head.latest_receipt.receipt_id
        executions.append(execution)
    return executions


def _replay_signature(executions) -> tuple[object, ...]:
    signature = []
    for execution in executions:
        manifest = json.loads(
            (execution.write_result.bundle_path / ".bundle-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        receipt = json.loads(
            (execution.write_result.bundle_path / "canonical_receipt.v1.json").read_text(
                encoding="utf-8"
            )
        )
        effective = receipt["effective_head"]
        signature.append(
            (
                execution.result.result_id,
                execution.write_result.receipt_id,
                effective["feature_snapshot_id"],
                effective["state_id"],
                effective["transition_decision_hash"],
                effective["strategy_id"],
                effective["consistency_decision_id"],
                tuple(
                    sorted(
                        (item["path"], item["sha256"])
                        for item in manifest["items"]
                    )
                ),
            )
        )
    return tuple(signature)


def test_five_day_runtime_chain_preserves_state_and_enforces_risk_gates(
    tmp_path: Path,
) -> None:
    executions = _run_five_day_chain(tmp_path)
    d1, d2, d3, d4, d5 = (execution.result for execution in executions)

    assert d1.canonical_action.value == "bootstrap"
    assert d2.analysis_state.state_id == d1.analysis_state.state_id
    assert d2.transition_decision.advance is False
    assert ordinary_stage_distance(d2.analysis_state.stage, d3.analysis_state.stage) <= 1
    assert d3.transition_decision.evidence.delta_kind.value == "ordinary"
    assert d4.transition_decision.action.value == "invalidate"
    assert d4.transition_decision.advance is True
    assert d4.candidate_strategy.status.value == "INVALIDATED"
    assert d4.consistency_decision.consistency_passed is True
    assert d5.analysis_state.state_id == d4.analysis_state.state_id
    assert d5.transition_decision.advance is False
    assert d5.candidate_strategy.status.value == "NO_TRADE"
    assert d5.candidate_strategy.no_trade_reason_code.value == "DATA_QUALITY_BLOCKED"
    assert d5.selected_state_id == d4.analysis_state.state_id
    assert d5.selected_strategy_id == d5.candidate_strategy.decision_id
    final_head = load_gold_daily_close_head(storage_root=tmp_path).head
    assert final_head.analysis_state.state_id == d4.analysis_state.state_id
    assert final_head.strategy_decision == d5.candidate_strategy
    delivery = build_gold_daily_close_delivery(executions[-1].loop_input, d5)
    assert delivery.strategy_diff.selected_status == "NO_TRADE"
    assert delivery.final_report.selected_strategy_status == "NO_TRADE"
    assert all(
        evaluate_gold_daily_close_loop(execution.loop_input).result_id
        == execution.result.result_id
        for execution in executions
        for _ in range(100)
    )


def test_five_day_runtime_and_store_identities_match_across_independent_roots(
    tmp_path: Path,
) -> None:
    expected = None
    for replay in range(2):
        executions = _run_five_day_chain(tmp_path / f"replay-{replay:03d}")
        signature = _replay_signature(executions)
        if expected is None:
            expected = signature
        assert signature == expected


def test_five_day_runtime_replay_is_idempotent_in_the_same_store(
    tmp_path: Path,
) -> None:
    executions = _run_five_day_chain(tmp_path)

    for index, original in enumerate(executions):
        loop_input = original.loop_input
        replay = execute_gold_daily_close_runtime(
            storage_root=tmp_path,
            run_id=f"five-day-d{index + 1}",
            current_feature=loop_input.current_feature,
            controls=GoldDailyCloseRuntimeControls(
                decision_as_of=loop_input.decision_as_of,
                transition_evidence=loop_input.transition_evidence,
                options_regime=loop_input.options_regime,
                event_risk=loop_input.event_risk,
                key_levels=loop_input.key_levels,
                key_level_decisions=loop_input.key_level_decisions,
                key_level_proof=loop_input.key_level_proof,
            ),
            bootstrap_previous_feature=(loop_input.previous_feature if index == 0 else None),
        )

        assert replay.result.result_id == original.result.result_id
        assert replay.write_result.receipt_id == original.write_result.receipt_id
        assert replay.write_result.artifact_results == ()
