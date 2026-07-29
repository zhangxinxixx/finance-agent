"""Deterministic batch runner for immutable daily-close runtime cases.

This module deliberately only composes the existing daily-close runtime and
store.  Its output is a fixture/replay readiness summary, not an Analysis
Memory canonical-state claim or real-market evidence.
"""

from __future__ import annotations

import re
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.gold_policy.daily_close_runtime import (
    GoldDailyCloseRuntimeControls,
    execute_gold_daily_close_runtime,
)
from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseHeadConflictError,
    load_gold_daily_close_head,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshot


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldDailyCloseBatchCase(_FrozenContract):
    """One explicit, immutable session to execute in an ordered batch."""

    run_id: str = Field(min_length=1, max_length=128)
    current_feature: FeatureSnapshot
    controls: GoldDailyCloseRuntimeControls
    bootstrap_previous_feature: FeatureSnapshot | None = None

    @model_validator(mode="after")
    def _validate_case(self) -> "GoldDailyCloseBatchCase":
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id contains unsafe path characters")
        session_date = self.current_feature.as_of.astimezone(UTC).date()
        if self.controls.decision_as_of.date() != session_date:
            raise ValueError("controls decision_as_of must match the current feature session")
        if self.bootstrap_previous_feature is not None:
            if self.bootstrap_previous_feature.scope != "daily_close":
                raise ValueError("bootstrap previous feature scope must be daily_close")
            if self.bootstrap_previous_feature.as_of >= self.current_feature.as_of:
                raise ValueError("bootstrap previous feature must predate current feature")
        return self


class GoldDailyCloseBatchInput(_FrozenContract):
    schema_version: Literal["gold_daily_close_batch_input.v1"] = "gold_daily_close_batch_input.v1"
    cases: tuple[GoldDailyCloseBatchCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_order(self) -> "GoldDailyCloseBatchInput":
        seen_run_ids: set[str] = set()
        previous_date: date | None = None
        for index, case in enumerate(self.cases):
            if case.run_id in seen_run_ids:
                raise ValueError("batch run_id values must be unique")
            seen_run_ids.add(case.run_id)
            current_date = case.current_feature.as_of.astimezone(UTC).date()
            if previous_date is not None and current_date <= previous_date:
                raise ValueError("batch case dates must be strictly increasing")
            if index and case.bootstrap_previous_feature is not None:
                raise ValueError("bootstrap predecessor is only allowed for the first case")
            previous_date = current_date
        return self


class GoldDailyCloseBatchDaySummary(_FrozenContract):
    session_date: date
    run_id: str
    feature_snapshot_id: str
    result_id: str
    receipt_id: str
    state_id: str | None
    strategy_id: str | None
    selected_feature_snapshot_id: str
    selected_state_id: str
    selected_strategy_id: str
    action: str
    chain_continuity: Literal["continuous"] = "continuous"


class GoldDailyCloseBatchSummary(_FrozenContract):
    schema_version: Literal["gold_daily_close_batch_summary.v1"] = "gold_daily_close_batch_summary.v1"
    days: tuple[GoldDailyCloseBatchDaySummary, ...]
    chain_continuity: Literal["continuous"] = "continuous"
    sample_count: int = Field(ge=1)
    readiness: Literal["insufficient_sample", "ready"]
    evidence_scope: Literal["fixture_or_replay_only"] = "fixture_or_replay_only"
    analysis_memory_production_canonical: Literal[False] = False


def execute_gold_daily_close_batch(
    *, storage_root: Path, batch: GoldDailyCloseBatchInput
) -> GoldDailyCloseBatchSummary:
    """Run ordered cases through the existing runtime and verify each receipt/head.

    All batch-shape validation happens before the first write.  The underlying
    store remains responsible for atomic per-session persistence and same-store
    reruns.
    """

    summaries: list[GoldDailyCloseBatchDaySummary] = []
    previous_receipt_id: str | None = None
    for index, case in enumerate(batch.cases):
        execution = execute_gold_daily_close_runtime(
            storage_root=storage_root,
            run_id=case.run_id,
            current_feature=case.current_feature,
            controls=case.controls,
            bootstrap_previous_feature=case.bootstrap_previous_feature,
        )
        receipt = execution.write_result.receipt_id
        expected_predecessor = (
            previous_receipt_id
            if index
            else (
                execution.predecessor_lookup.latest_receipt.receipt_id
                if execution.predecessor_lookup.latest_receipt is not None
                else None
            )
        )
        result_date = case.current_feature.as_of.astimezone(UTC).date()
        lookup = load_gold_daily_close_head(
            storage_root=storage_root, before_date=result_date + timedelta(days=1)
        )
        if lookup.status != "found" or lookup.head is None or lookup.latest_receipt is None:
            raise DailyCloseHeadConflictError("daily-close batch selected head is unavailable")
        if lookup.latest_receipt.receipt_id != receipt:
            raise DailyCloseHeadConflictError("daily-close batch selected head does not match current receipt")
        if lookup.latest_receipt.predecessor_receipt_id != expected_predecessor:
            raise DailyCloseHeadConflictError("daily-close batch receipt predecessor is discontinuous")
        if index and execution.predecessor_lookup.latest_receipt is None:
            raise DailyCloseHeadConflictError("daily-close batch predecessor receipt is unavailable")
        if index and execution.predecessor_lookup.latest_receipt.receipt_id != previous_receipt_id:
            raise DailyCloseHeadConflictError("daily-close batch runtime predecessor does not match prior case")

        result = execution.result
        head = lookup.head
        summaries.append(
            GoldDailyCloseBatchDaySummary(
                session_date=result_date,
                run_id=case.run_id,
                feature_snapshot_id=case.current_feature.snapshot_id,
                result_id=result.result_id,
                receipt_id=receipt,
                state_id=(result.analysis_state.state_id if result.analysis_state else None),
                strategy_id=(result.candidate_strategy.decision_id if result.candidate_strategy else None),
                selected_feature_snapshot_id=head.feature_snapshot.snapshot_id,
                selected_state_id=head.analysis_state.state_id,
                selected_strategy_id=head.strategy_decision.decision_id,
                action=result.canonical_action.value,
            )
        )
        previous_receipt_id = receipt

    sample_count = len(summaries)
    return GoldDailyCloseBatchSummary(
        days=tuple(summaries),
        sample_count=sample_count,
        readiness="ready" if sample_count >= 20 else "insufficient_sample",
    )
