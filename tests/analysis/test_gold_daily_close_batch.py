from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy import daily_close_batch
from apps.analysis.gold_policy.daily_close_batch import (
    GoldDailyCloseBatchCase,
    GoldDailyCloseBatchInput,
    execute_gold_daily_close_batch,
)
from apps.analysis.gold_policy.daily_close_runtime import GoldDailyCloseRuntimeControls
from apps.analysis.gold_policy.daily_close_runtime import execute_gold_daily_close_runtime
from apps.analysis.gold_policy.daily_close_store import DailyCloseHeadConflictError
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from tests.analysis.test_gold_daily_close_five_day_replay import _fixture, _feature_snapshot
from tests.analysis.test_gold_daily_close_loop import _confirmed_support_break, _evidence
from tests.analysis.test_gold_strategy_policy import _policy_input


def _batch() -> GoldDailyCloseBatchInput:
    fixture = _fixture()
    bootstrap_previous = _feature_snapshot(fixture["bootstrap_previous_fixture"])
    previous = bootstrap_previous
    cases = []
    for index, raw_case in enumerate(fixture["days"]):
        current = _feature_snapshot(raw_case["feature_fixture"])
        support = _policy_input(
            bias=raw_case["options_bias"],
            feature=current,
            attribution=attribute_gold_price(current, previous),
        )
        evidence = _evidence(
            support.decision_as_of,
            delta_kind=raw_case["delta_kind"],
            categories=tuple(raw_case["categories"]) or None,
            rule_code=raw_case.get("rule_code"),
        )
        key_levels = key_level_decisions = key_level_proof = ()
        if raw_case["day"] == "D4":
            broken_level, break_decision = _confirmed_support_break(support.decision_as_of)
            key_levels = (broken_level,)
            key_level_decisions = key_level_proof = (break_decision,)
        cases.append(
            GoldDailyCloseBatchCase(
                run_id=f"batch-{raw_case['day'].lower()}",
                current_feature=current,
                controls=GoldDailyCloseRuntimeControls(
                    decision_as_of=support.decision_as_of,
                    transition_evidence=evidence,
                    options_regime=support.options_regime,
                    event_risk=support.event_risk,
                    key_levels=key_levels,
                    key_level_decisions=key_level_decisions,
                    key_level_proof=key_level_proof,
                ),
                bootstrap_previous_feature=(bootstrap_previous if index == 0 else None),
            )
        )
        previous = current
    return GoldDailyCloseBatchInput(cases=tuple(cases))


def _signature(summary) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(
        (
            item.feature_snapshot_id,
            item.result_id,
            item.receipt_id,
            item.selected_state_id,
            item.selected_strategy_id,
        )
        for item in summary.days
    )


def _shift_feature(template, *, days: int):
    target = template.as_of + timedelta(days=days)
    payload = template.model_dump(
        mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"}
    )

    def replace_as_of(value):
        if isinstance(value, dict):
            return {
                key: (target.isoformat() if key == "as_of" else replace_as_of(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace_as_of(item) for item in value]
        return value

    return build_feature_snapshot(replace_as_of(payload))


def _twenty_case_batch() -> GoldDailyCloseBatchInput:
    template = _batch().cases[0]
    previous = template.bootstrap_previous_feature
    assert previous is not None
    cases = []
    for index in range(20):
        current = _shift_feature(template.current_feature, days=index)
        support = _policy_input(
            feature=current,
            attribution=attribute_gold_price(current, previous),
        )
        cases.append(
            GoldDailyCloseBatchCase(
                run_id=f"twenty-day-{index + 1:02d}",
                current_feature=current,
                controls=GoldDailyCloseRuntimeControls(
                    decision_as_of=support.decision_as_of,
                    transition_evidence=(
                        _evidence(
                            support.decision_as_of,
                            delta_kind="ordinary",
                            categories=("macro",),
                        )
                        if index == 0
                        else _evidence(support.decision_as_of, delta_kind="no_op")
                    ),
                    options_regime=support.options_regime,
                    event_risk=support.event_risk,
                ),
                bootstrap_previous_feature=(previous if index == 0 else None),
            )
        )
        previous = current
    return GoldDailyCloseBatchInput(cases=tuple(cases))


def test_batch_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    batch = _batch()
    left = execute_gold_daily_close_batch(storage_root=tmp_path / "left", batch=batch)
    right = execute_gold_daily_close_batch(storage_root=tmp_path / "right", batch=batch)
    rerun = execute_gold_daily_close_batch(storage_root=tmp_path / "left", batch=batch)

    assert _signature(left) == _signature(right) == _signature(rerun)
    assert left.sample_count == 5
    assert left.readiness == "insufficient_sample"
    assert all(item.chain_continuity == "continuous" for item in left.days)
    assert left.evidence_scope == "fixture_or_replay_only"
    assert left.analysis_memory_production_canonical is False


def test_batch_rejects_invalid_order_run_ids_and_late_bootstrap() -> None:
    batch = _batch()
    first, second = batch.cases[:2]
    with pytest.raises(ValidationError, match="strictly increasing"):
        GoldDailyCloseBatchInput(cases=(second, first))
    with pytest.raises(ValidationError, match="unique"):
        GoldDailyCloseBatchInput(cases=(first, first))
    with pytest.raises(ValidationError, match="unsafe"):
        GoldDailyCloseBatchCase(
            run_id="../unsafe", current_feature=first.current_feature, controls=first.controls
        )


def test_batch_is_ready_at_twenty_strictly_increasing_valid_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = _twenty_case_batch()
    dates = [case.current_feature.as_of.date() for case in batch.cases]
    current_index = 0

    def fake_runtime(**_kwargs):
        nonlocal current_index
        index = current_index
        current_index += 1
        state = SimpleNamespace(state_id=f"state-{index}")
        strategy = SimpleNamespace(decision_id=f"strategy-{index}")
        predecessor = (
            None if index == 0 else SimpleNamespace(receipt_id=f"receipt-{index - 1}")
        )
        return SimpleNamespace(
            write_result=SimpleNamespace(receipt_id=f"receipt-{index}"),
            predecessor_lookup=SimpleNamespace(latest_receipt=predecessor),
            result=SimpleNamespace(
                result_id=f"result-{index}",
                analysis_state=state,
                candidate_strategy=strategy,
                canonical_action=SimpleNamespace(value="maintain"),
            ),
        )

    def fake_head(*, before_date, **_kwargs):
        index = dates.index(before_date - timedelta(days=1))
        return SimpleNamespace(
            status="found",
            latest_receipt=SimpleNamespace(
                receipt_id=f"receipt-{index}",
                predecessor_receipt_id=(None if index == 0 else f"receipt-{index - 1}"),
            ),
            head=SimpleNamespace(
                feature_snapshot=SimpleNamespace(snapshot_id=f"selected-feature-{index}"),
                analysis_state=SimpleNamespace(state_id=f"selected-state-{index}"),
                strategy_decision=SimpleNamespace(decision_id=f"selected-strategy-{index}"),
            ),
        )

    monkeypatch.setattr(daily_close_batch, "execute_gold_daily_close_runtime", fake_runtime)
    monkeypatch.setattr(daily_close_batch, "load_gold_daily_close_head", fake_head)
    summary = execute_gold_daily_close_batch(storage_root=tmp_path, batch=batch)

    assert summary.sample_count == 20
    assert summary.readiness == "ready"
    assert summary.chain_continuity == "continuous"
    assert len({day.run_id for day in summary.days}) == 20
    assert [day.session_date for day in summary.days] == sorted(
        day.session_date for day in summary.days
    )


def test_batch_fails_closed_for_an_incompatible_existing_predecessor(tmp_path: Path) -> None:
    batch = _batch()
    first, second = batch.cases[:2]
    execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id=first.run_id,
        current_feature=first.current_feature,
        controls=first.controls,
        bootstrap_previous_feature=first.bootstrap_previous_feature,
    )

    conflicting_first = second.model_copy(
        update={"bootstrap_previous_feature": first.bootstrap_previous_feature}
    )
    with pytest.raises(
        DailyCloseHeadConflictError, match="caller previous feature conflicts"
    ):
        execute_gold_daily_close_batch(
            storage_root=tmp_path,
            batch=GoldDailyCloseBatchInput(cases=(conflicting_first,)),
        )
    with pytest.raises(ValidationError, match="only allowed for the first"):
        GoldDailyCloseBatchInput(
            cases=(
                first,
                second.model_copy(
                    update={"bootstrap_previous_feature": first.current_feature}
                ),
            )
        )
