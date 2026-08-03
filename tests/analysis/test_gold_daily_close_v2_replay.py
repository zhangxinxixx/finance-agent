from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_runtime import (
    GoldDailyCloseRuntimeControls,
    execute_gold_daily_close_runtime,
)
from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseArtifactPointer,
    DailyCloseHeadConflictError,
    _read_versioned_pointer,
    load_gold_daily_close_head,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.state_schemas import AnalysisState, AnalysisStateV2
from tests.analysis.test_gold_daily_close_loop import _evidence
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot


FIXTURE = Path(__file__).parents[1] / "fixtures" / "gold_daily_close" / "five_day_chain_v2.json"
GOLD_POLICY_FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fixture_path(name: str) -> Path:
    local = FIXTURE.parent / name
    return local if local.is_file() else GOLD_POLICY_FIXTURES / name


def _clamp_reference_times(value: object, cutoff: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_refs", "reaction_source_refs"} and isinstance(child, list):
                for reference in child:
                    reference["retrieved_at"] = cutoff
            else:
                _clamp_reference_times(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            _clamp_reference_times(child, cutoff)


def _v2_feature(name: str, patch: dict | None = None):
    payload = json.loads(_fixture_path(name).read_text(encoding="utf-8"))
    direct = payload.pop("real10y")
    direct["market_role"] = "real_yield_direct"
    payload.update(schema_version="feature_snapshot.v2", real10y_direct=direct)
    for field_name, changes in (patch or {}).items():
        payload[field_name].update(changes)
    _clamp_reference_times(payload, payload["as_of"])
    return build_feature_snapshot(payload)


def _controls(case: dict, current, previous) -> GoldDailyCloseRuntimeControls:
    support = _policy_input(
        bias=case["options_bias"],
        feature=current,
        attribution=attribute_gold_price(current, previous),
    )
    return GoldDailyCloseRuntimeControls(
        decision_as_of=support.decision_as_of,
        transition_evidence=_evidence(
            support.decision_as_of,
            delta_kind=case["delta_kind"],
            categories=tuple(case["categories"]) or None,
        ),
        options_regime=support.options_regime,
        event_risk=support.event_risk,
    )


def _run_chain(storage_root: Path):
    fixture = _fixture()
    bootstrap_previous = _v2_feature(fixture["bootstrap_previous_fixture"])
    executions = []
    for index, case in enumerate(fixture["days"]):
        current = _v2_feature(case["feature_fixture"], case.get("patch"))
        lookup = load_gold_daily_close_head(
            storage_root=storage_root,
            before_date=current.as_of.date(),
        )
        previous = bootstrap_previous if index == 0 else lookup.head.feature_snapshot
        execution = execute_gold_daily_close_runtime(
            storage_root=storage_root,
            run_id=f"five-day-v2-{case['day'].lower()}",
            current_feature=current,
            controls=_controls(case, current, previous),
            bootstrap_previous_feature=(bootstrap_previous if index == 0 else None),
        )
        if index:
            assert lookup.status == "found"
            assert execution.loop_input.previous_feature == lookup.head.feature_snapshot
            assert execution.loop_input.previous_state == lookup.head.analysis_state
            assert execution.loop_input.previous_transition == lookup.head.transition_decision
            assert execution.loop_input.previous_strategy == lookup.head.strategy_decision
            assert execution.loop_input.previous_state.schema_version == "analysis_state.v2"
        head = load_gold_daily_close_head(storage_root=storage_root)
        assert head.status == "found"
        assert head.head.analysis_state.schema_version == "analysis_state.v2"
        assert head.head.transition_decision.policy_version == "analysis_state_transition_policy.v2"
        assert head.head.strategy_policy_input.schema_version == "strategy_policy_input.v2"
        assert head.head.strategy_decision.schema_version == "strategy_decision.v2"
        executions.append(execution)
    return executions


def _signature(executions) -> tuple:
    return tuple(
        (
            execution.result.result_id,
            execution.write_result.receipt_id,
            execution.result.analysis_state.state_id,
            execution.result.transition_decision.decision_hash,
            execution.result.candidate_strategy.decision_id,
            tuple(sorted(path.name for path in execution.write_result.bundle_path.iterdir())),
        )
        for execution in executions
    )


def test_v2_five_day_runtime_replay_reads_only_the_previous_v2_head(
    tmp_path: Path,
) -> None:
    executions = _run_chain(tmp_path)
    expected_artifacts = {
        "analysis_state.v2.json",
        "state_transition_policy_decision.v2.json",
        "strategy_policy_input.v2.json",
        "strategy_decision.v2.json",
        "gold_report_context.v1.json",
        "gold_policy_report_render.v1.json",
    }
    forbidden_artifacts = {
        name.replace(".v2.json", ".v1.json")
        for name in expected_artifacts
        if name.endswith(".v2.json")
    }

    for execution in executions:
        names = {path.name for path in execution.write_result.bundle_path.iterdir()}
        assert expected_artifacts <= names
        assert names.isdisjoint(forbidden_artifacts)
        assert all(
            evaluate_gold_daily_close_loop(execution.loop_input).result_id == execution.result.result_id
            for _ in range(100)
        )
    assert executions[1].result.analysis_state.state_id == executions[0].result.analysis_state.state_id
    assert executions[-1].result.candidate_strategy.status.value == "NO_TRADE"


def test_v2_five_day_runtime_and_store_are_deterministic_across_roots(
    tmp_path: Path,
) -> None:
    first = _signature(_run_chain(tmp_path / "first"))
    second = _signature(_run_chain(tmp_path / "second"))

    assert first == second


def test_runtime_rejects_v2_input_over_a_v1_canonical_head(tmp_path: Path) -> None:
    previous_v1 = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current_v1 = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    v1_case = {"options_bias": "bearish", "delta_kind": "ordinary", "categories": ["macro"]}
    execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="v1-head",
        current_feature=current_v1,
        controls=_controls(v1_case, current_v1, previous_v1),
        bootstrap_previous_feature=previous_v1,
    )
    current_v2 = _v2_feature("feature_snapshot_v1_mixed_2025-01-24.json")

    with pytest.raises(DailyCloseHeadConflictError, match="version does not match"):
        execute_gold_daily_close_runtime(
            storage_root=tmp_path,
            run_id="v2-over-v1",
            current_feature=current_v2,
            controls=_controls(v1_case, current_v2, _v2_feature("feature_snapshot_v1_bearish_2025-01-21.json")),
        )


def test_v2_prebootstrap_blocked_run_persists_without_v1_delivery_artifacts(
    tmp_path: Path,
) -> None:
    previous = _v2_feature("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _v2_feature("feature_snapshot_v1_blocked_2025-01-22.json")
    case = {"options_bias": "bullish", "delta_kind": "ordinary", "categories": ["macro"]}

    execution = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="v2-prebootstrap-blocked",
        current_feature=current,
        controls=_controls(case, current, previous),
        bootstrap_previous_feature=previous,
    )

    assert execution.result.analysis_state is None
    assert execution.result.canonical_action.value == "hold"
    names = {path.name for path in execution.write_result.bundle_path.iterdir()}
    assert "gold_analysis_decision.v2.json" in names
    assert "gold_report_context.v1.json" in names
    assert "gold_policy_report_render.v1.json" in names
    assert {
        "source.md",
        "analysis.md",
        "visual.html",
        "report_structured.json",
        "evidence.json",
        "data_quality.json",
        "report_manifest.json",
        "strategy_card.json",
        "strategy_card.md",
    } <= names
    data_quality = json.loads((execution.write_result.bundle_path / "data_quality.json").read_text(encoding="utf-8"))
    strategy_card = json.loads((execution.write_result.bundle_path / "strategy_card.json").read_text(encoding="utf-8"))
    assert data_quality["report_status"] == "degraded"
    assert strategy_card["status"] == "NO_TRADE"
    assert "final_report.v1.json" not in names
    assert load_gold_daily_close_head(storage_root=tmp_path).status == "missing"


def test_store_reader_never_parses_v2_state_under_a_v1_filename(tmp_path: Path) -> None:
    execution = _run_chain(tmp_path)[0]
    source = execution.write_result.bundle_path / "analysis_state.v2.json"
    wrong_name = tmp_path / "analysis_state.v1.json"
    content = source.read_bytes()
    wrong_name.write_bytes(content)
    pointer = DailyCloseArtifactPointer(
        path=wrong_name.relative_to(tmp_path).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    with pytest.raises(ValidationError):
        _read_versioned_pointer(
            tmp_path,
            pointer,
            {
                "analysis_state.v1.json": AnalysisState,
                "analysis_state.v2.json": AnalysisStateV2,
            },
        )
