from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput
from apps.analysis.gold_policy.daily_close_store import persist_gold_daily_close_run
from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.strategy import gold_baseline_adapter
from apps.analysis.strategy.gold_baseline_adapter import resolve_verified_gold_baseline
from tests.analysis.test_gold_daily_close_loop import _evidence
from tests.analysis.test_gold_daily_close_store import _persist_bootstrap
from tests.analysis.test_gold_key_level_policy import _event as _level_event
from tests.analysis.test_gold_key_level_policy import _spec as _level_spec
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


def test_verified_directional_head_projects_short_authority(tmp_path: Path) -> None:
    loop_input, result, write, head = _persist_bootstrap(tmp_path)

    projection = resolve_verified_gold_baseline(
        storage_root=tmp_path,
        now=loop_input.decision_as_of + timedelta(seconds=1),
    )

    assert projection["status"] == "accepted"
    assert projection["authority_ready"] is True
    assert projection["lineage_verified"] is True
    assert projection["direction"] == "short"
    assert projection["strategy_status"] == "SHORT_WATCH"
    assert projection["quality_status"] == "accepted"
    assert projection["strategy_id"] == head.strategy_decision.decision_id
    assert projection["receipt_id"] == write.receipt_id
    assert write.bundle_path.relative_to(tmp_path).as_posix() in projection["artifact_refs"]
    assert any(item["name"] == "gold_daily_close_receipt" for item in projection["source_refs"])


def test_prebootstrap_hold_cannot_project_directional_authority(tmp_path: Path) -> None:
    blocked = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    support = _policy_input(
        feature=blocked,
        attribution=attribute_gold_price(blocked, previous),
    )
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=blocked,
        previous_feature=previous,
        transition_evidence=_evidence(support.decision_as_of),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )
    result = evaluate_gold_daily_close_loop(loop_input)
    persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-prebootstrap-hold",
        loop_input=loop_input,
        result=result,
    )

    projection = resolve_verified_gold_baseline(
        storage_root=tmp_path,
        now=loop_input.decision_as_of + timedelta(seconds=1),
    )

    assert result.canonical_action.value == "hold"
    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "gold_daily_close_prebootstrap_hold"
    assert projection["authority_ready"] is False
    assert projection["direction"] == "none"
    assert projection["gold_head_held"] is True


def test_retained_hold_keeps_the_predecessor_effective_strategy_identity(tmp_path: Path) -> None:
    _, _, _, previous_head = _persist_bootstrap(tmp_path)
    current = _snapshot("feature_snapshot_v1_mixed_2025-01-24.json")
    support = _policy_input(
        feature=current,
        attribution=attribute_gold_price(current, previous_head.feature_snapshot),
    )
    spec = _level_spec(
        effective_from=support.decision_as_of - timedelta(days=1),
        expires_at=support.decision_as_of + timedelta(days=30),
    )
    unmatched = evaluate_key_level_lifecycle(
        None,
        _level_event(
            "discover",
            spec=spec,
            source_role="jin10_supplemental",
            factors=("level_proposal",),
            as_of=support.decision_as_of,
        ),
    ).decision
    loop_input = DailyCloseLoopInput(
        decision_as_of=support.decision_as_of,
        current_feature=current,
        previous_feature=previous_head.feature_snapshot,
        previous_policy_input=previous_head.strategy_policy_input,
        previous_state=previous_head.analysis_state,
        previous_transition=previous_head.transition_decision,
        previous_strategy=previous_head.strategy_decision,
        transition_evidence=_evidence(support.decision_as_of, delta_kind="no_op"),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
        key_level_decisions=(unmatched,),
    )
    result = evaluate_gold_daily_close_loop(loop_input)
    write = persist_gold_daily_close_run(
        storage_root=tmp_path,
        run_id="run-rejected-hold",
        loop_input=loop_input,
        result=result,
    )

    projection = resolve_verified_gold_baseline(
        storage_root=tmp_path,
        now=loop_input.decision_as_of + timedelta(seconds=1),
    )

    assert result.canonical_action.value == "hold"
    assert projection["status"] == "held"
    assert projection["gold_head_held"] is True
    assert projection["authority_ready"] is True
    assert projection["strategy_id"] == previous_head.strategy_decision.decision_id
    assert projection["receipt_id"] == write.receipt_id


def test_invalid_or_future_authority_fails_closed(tmp_path: Path, monkeypatch) -> None:
    loop_input, _, _, _ = _persist_bootstrap(tmp_path)
    future = resolve_verified_gold_baseline(
        storage_root=tmp_path,
        now=loop_input.decision_as_of - timedelta(seconds=1),
    )
    monkeypatch.setattr(
        gold_baseline_adapter,
        "verify_gold_daily_close_bundle",
        lambda **_: SimpleNamespace(status="invalid"),
    )
    invalid = resolve_verified_gold_baseline(
        storage_root=tmp_path,
        now=loop_input.decision_as_of + timedelta(seconds=1),
    )

    assert future["status"] == "invalid"
    assert future["reason_code"] == "gold_daily_close_authority_future"
    assert future["authority_ready"] is False
    assert invalid["status"] == "invalid"
    assert invalid["reason_code"] == "gold_daily_close_authority_lineage_invalid"
    assert invalid["authority_ready"] is False
