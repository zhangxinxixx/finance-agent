"""Typed, deterministic report context for authoritative Gold daily closes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from apps.analysis.gold_policy.daily_close_schemas import (
    AnalysisStateContract,
    DailyCloseLoopInput,
    DailyCloseLoopResult,
    GoldAnalysisDecisionContract,
    GoldPriceAttributionContract,
    StateTransitionDecisionContract,
    StrategyDecisionContract,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
)
from apps.analysis.gold_policy.schemas import SourceReference


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldReportContext(_FrozenContract):
    """A report-only projection that keeps every conclusion typed and bound."""

    schema_version: Literal["gold_report_context.v1"] = "gold_report_context.v1"
    authority_result_id: str
    current_feature_id: str
    previous_feature_id: str | None
    decision_as_of: datetime
    analysis_decision: GoldAnalysisDecisionContract
    price_attribution: GoldPriceAttributionContract
    candidate_state: AnalysisStateContract | None
    selected_state: AnalysisStateContract | None
    transition_decision: StateTransitionDecisionContract
    candidate_strategy: StrategyDecisionContract | None
    selected_strategy: StrategyDecisionContract | None
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    analysis_readiness: Literal["ready", "observe", "blocked"]
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    language_generation: Literal["not_invoked"] = "not_invoked"
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_id: str = Field(pattern=r"^gold_report_context\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity_and_bindings(self) -> "GoldReportContext":
        if self.analysis_decision.current_snapshot_id != self.current_feature_id:
            raise ValueError("report analysis must bind the current feature")
        if self.price_attribution.current_snapshot_id != self.current_feature_id:
            raise ValueError("report attribution must bind the current feature")
        if self.analysis_decision.previous_snapshot_id != (
            self.previous_feature_id or "missing"
        ):
            raise ValueError("report analysis must bind the previous feature")
        if self.candidate_state is None:
            if self.transition_decision.to_state_id is not None:
                raise ValueError("a missing candidate state requires an unbound transition")
            if self.candidate_strategy is not None:
                raise ValueError("a missing candidate state cannot have a candidate strategy")
        else:
            if self.transition_decision.to_state_id != self.candidate_state.state_id:
                raise ValueError("report transition must bind the candidate state")
            if self.candidate_strategy is None:
                raise ValueError("a candidate state requires a candidate strategy")
            if self.candidate_strategy.analysis_state_id != self.candidate_state.state_id:
                raise ValueError("report candidate strategy must bind the candidate state")
        if self.selected_strategy is not None and self.selected_state is None:
            raise ValueError("a selected strategy requires a selected state")
        if self.selected_strategy is not None:
            if self.selected_strategy.analysis_state_id != self.selected_state.state_id:
                raise ValueError("report selected strategy must bind the selected state")
        digest = _digest(self)
        if self.payload_hash != digest or self.context_id != f"gold_report_context.v1:{digest}":
            raise ValueError("report context identity does not match canonical payload")
        return self


def build_gold_report_context(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> GoldReportContext:
    """Project only canonical typed daily-close artifacts into report context."""

    selected = result.candidate_strategy if result.selected_strategy_id == getattr(result.candidate_strategy, "decision_id", None) else loop_input.previous_strategy
    selected_state = result.analysis_state if result.selected_state_id == getattr(result.analysis_state, "state_id", None) else loop_input.previous_state
    payload = {
        "schema_version": "gold_report_context.v1",
        "authority_result_id": result.result_id,
        "current_feature_id": result.current_feature_id,
        "previous_feature_id": result.previous_feature_id,
        "decision_as_of": result.decision_as_of,
        "analysis_decision": result.analysis_decision,
        "price_attribution": result.price_attribution,
        "candidate_state": result.analysis_state,
        "selected_state": selected_state,
        "transition_decision": result.transition_decision,
        "candidate_strategy": result.candidate_strategy,
        "selected_strategy": selected,
        "key_levels": tuple(loop_input.key_levels),
        "key_level_decisions": tuple(loop_input.key_level_decisions),
        "analysis_readiness": loop_input.current_feature.data_quality.analysis_readiness,
        "source_refs": _canonical_refs(result.source_refs),
        "language_generation": "not_invoked",
    }
    digest = _digest_payload(payload)
    return GoldReportContext(
        **payload,
        payload_hash=digest,
        context_id=f"gold_report_context.v1:{digest}",
    )


def _canonical_refs(refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))


def _digest(context: GoldReportContext) -> str:
    return _digest_payload(context.model_dump(mode="json", exclude={"payload_hash", "context_id"}))


def _digest_payload(payload: object) -> str:
    canonical = json.dumps(
        to_jsonable_python(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
