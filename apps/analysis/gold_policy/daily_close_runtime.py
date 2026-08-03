"""Typed worker-facing adapter for the deterministic daily-close loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_schemas import DailyCloseLoopInput, DailyCloseLoopResult
from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseBundleWriteResult,
    DailyCloseHeadConflictError,
    DailyCloseHeadLookup,
    load_gold_daily_close_head,
    persist_gold_daily_close_run,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotContract
from apps.analysis.gold_policy.state_schemas import TransitionEvidence
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyEventRiskSnapshot,
    StrategyOptionsRegimeSnapshot,
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldDailyCloseRuntimeControls(_FrozenContract):
    schema_version: Literal["gold_daily_close_runtime_controls.v1"] = "gold_daily_close_runtime_controls.v1"
    decision_as_of: datetime
    transition_evidence: TransitionEvidence
    options_regime: StrategyOptionsRegimeSnapshot
    event_risk: StrategyEventRiskSnapshot
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    key_level_proof: tuple[KeyLevelLifecycleDecision, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @field_validator("decision_as_of")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("runtime decision_as_of must be timezone-aware")
        return value.astimezone(UTC)


class GoldDailyCloseRuntimeExecution(_FrozenContract):
    schema_version: Literal["gold_daily_close_runtime_execution.v1"] = "gold_daily_close_runtime_execution.v1"
    predecessor_lookup: DailyCloseHeadLookup
    loop_input: DailyCloseLoopInput
    result: DailyCloseLoopResult
    write_result: DailyCloseBundleWriteResult


def execute_gold_daily_close_runtime(
    *,
    storage_root: Path,
    run_id: str,
    current_feature: FeatureSnapshotContract,
    controls: GoldDailyCloseRuntimeControls,
    bootstrap_previous_feature: FeatureSnapshotContract | None = None,
) -> GoldDailyCloseRuntimeExecution:
    """Load the durable predecessor, execute the pure loop, and commit its bundle."""

    session_date = current_feature.as_of.astimezone(UTC).date()
    bundle_path = (
        storage_root
        / "analysis"
        / "gold_mainlines"
        / session_date.isoformat()
        / run_id
        / "daily_close"
    )
    predecessor = load_gold_daily_close_head(
        storage_root=storage_root,
        before_date=(session_date if bundle_path.exists() else session_date + timedelta(days=1)),
    )
    if predecessor.status in {"invalid", "ambiguous"}:
        raise DailyCloseHeadConflictError(f"daily-close predecessor lookup failed: {predecessor.reason_code}")
    if (
        predecessor.status == "found"
        and predecessor.head is not None
        and predecessor.head.feature_snapshot.as_of >= current_feature.as_of
    ):
        raise DailyCloseHeadConflictError(
            "current feature must be newer than the durable canonical head"
        )

    payload: dict[str, object] = {
        "decision_as_of": controls.decision_as_of,
        "current_feature": current_feature,
        "transition_evidence": controls.transition_evidence,
        "options_regime": controls.options_regime,
        "event_risk": controls.event_risk,
        "key_levels": controls.key_levels,
        "key_level_decisions": controls.key_level_decisions,
        "key_level_proof": controls.key_level_proof,
    }
    if predecessor.status == "found" and predecessor.head is not None:
        head = predecessor.head
        if head.feature_snapshot.schema_version != current_feature.schema_version:
            raise DailyCloseHeadConflictError("daily-close predecessor version does not match current feature")
        if (
            bootstrap_previous_feature is not None
            and bootstrap_previous_feature.snapshot_id != head.feature_snapshot.snapshot_id
        ):
            raise DailyCloseHeadConflictError("caller previous feature conflicts with the durable canonical head")
        payload.update(
            {
                "previous_feature": head.feature_snapshot,
                "previous_policy_input": head.strategy_policy_input,
                "previous_state": head.analysis_state,
                "previous_transition": head.transition_decision,
                "previous_strategy": head.strategy_decision,
            }
        )
    else:
        payload["previous_feature"] = bootstrap_previous_feature

    loop_input = DailyCloseLoopInput.model_validate(payload)
    result = evaluate_gold_daily_close_loop(loop_input)
    write_result = persist_gold_daily_close_run(
        storage_root=storage_root,
        run_id=run_id,
        loop_input=loop_input,
        result=result,
    )
    return GoldDailyCloseRuntimeExecution(
        predecessor_lookup=predecessor,
        loop_input=loop_input,
        result=result,
        write_result=write_result,
    )
