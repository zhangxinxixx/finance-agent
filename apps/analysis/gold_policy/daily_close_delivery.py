"""Deterministic delivery sidecars derived only from the formal daily-close loop."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.analysis.gold_policy.daily_close_schemas import (
    CanonicalCommitAction,
    DailyCloseLoopInput,
    DailyCloseLoopResult,
)
from apps.analysis.gold_policy.schemas import SourceReference


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldDailyCloseStrategyDiff(_FrozenContract):
    schema_version: Literal["gold_daily_close_strategy_diff.v1"] = "gold_daily_close_strategy_diff.v1"
    previous_strategy_id: str | None
    candidate_strategy_id: str | None
    selected_strategy_id: str | None
    previous_status: str | None
    candidate_status: str | None
    selected_status: str | None
    changed_fields: tuple[str, ...]
    candidate_selected: bool
    canonical_action: CanonicalCommitAction


class GoldDailyCloseFinalReport(_FrozenContract):
    schema_version: Literal["gold_daily_close_final_report.v1"] = "gold_daily_close_final_report.v1"
    authority_result_id: str
    candidate_direction: str
    direction: str
    direction_tilt: str
    price_move: str
    attribution_status: str
    selected_state_id: str | None
    selected_stage: str | None
    candidate_transition_action: str
    transition_action: str
    selected_strategy_id: str | None
    selected_strategy_status: str | None
    no_trade_reason_code: str | None
    release_conditions: tuple[str, ...]
    review_triggers: tuple[str, ...]
    source_refs: tuple[SourceReference, ...]
    language_generation: Literal["not_invoked"] = "not_invoked"


class GoldDailyCloseContextBundle(_FrozenContract):
    schema_version: Literal["gold_daily_close_context_bundle.v1"] = "gold_daily_close_context_bundle.v1"
    result_id: str
    current_feature_id: str
    previous_feature_id: str | None
    previous_state_id: str | None
    selected_state_id: str | None
    previous_strategy_id: str | None
    selected_strategy_id: str | None
    transition_decision_hash: str
    consistency_decision_id: str | None
    source_refs: tuple[SourceReference, ...]


class GoldDailyCloseTokenTrace(_FrozenContract):
    schema_version: Literal["gold_daily_close_token_trace.v1"] = "gold_daily_close_token_trace.v1"
    result_id: str
    trace_scope: Literal["formal_daily_close_policy"] = "formal_daily_close_policy"
    model_invocations: Literal[0] = 0
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0
    model_call_skipped: Literal[True] = True
    skip_reason: Literal["deterministic_policy", "no_material_change"]


class GoldDailyCloseDeliveryArtifacts(_FrozenContract):
    strategy_diff: GoldDailyCloseStrategyDiff
    final_report: GoldDailyCloseFinalReport
    context_bundle: GoldDailyCloseContextBundle
    token_trace: GoldDailyCloseTokenTrace


def build_gold_daily_close_delivery(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> GoldDailyCloseDeliveryArtifacts:
    previous = loop_input.previous_strategy
    candidate = result.candidate_strategy
    candidate_selected = result.canonical_action is not CanonicalCommitAction.HOLD
    selected = candidate if candidate_selected else previous
    selected_state = result.analysis_state if candidate_selected else loop_input.previous_state
    changed_fields = tuple(
        field
        for field in (
            "status",
            "direction",
            "stage",
            "reason_codes",
            "no_trade_reason_code",
            "trigger_level_ids",
            "invalidation_level_ids",
        )
        if previous is not None and candidate is not None and getattr(previous, field) != getattr(candidate, field)
    )
    strategy_diff = GoldDailyCloseStrategyDiff(
        previous_strategy_id=(previous.decision_id if previous else None),
        candidate_strategy_id=(candidate.decision_id if candidate else None),
        selected_strategy_id=result.selected_strategy_id,
        previous_status=(previous.status.value if previous else None),
        candidate_status=(candidate.status.value if candidate else None),
        selected_status=(selected.status.value if selected else None),
        changed_fields=changed_fields,
        candidate_selected=candidate_selected,
        canonical_action=result.canonical_action,
    )
    final_report = GoldDailyCloseFinalReport(
        authority_result_id=result.result_id,
        candidate_direction=result.analysis_decision.direction,
        direction=(selected_state.directional_bias if selected_state else "unavailable"),
        direction_tilt=(
            selected_state.directional_bias
            if selected_state is not None
            and selected_state.directional_bias in {"bullish", "bearish"}
            else "none"
        ),
        price_move=result.price_attribution.price_move,
        attribution_status=result.price_attribution.attribution_status,
        selected_state_id=result.selected_state_id,
        selected_stage=(selected_state.stage.value if selected_state else None),
        candidate_transition_action=result.transition_decision.action.value,
        transition_action=(
            "hold"
            if result.canonical_action is CanonicalCommitAction.HOLD
            else result.transition_decision.action.value
        ),
        selected_strategy_id=result.selected_strategy_id,
        selected_strategy_status=(selected.status.value if selected else None),
        no_trade_reason_code=(
            selected.no_trade_reason_code.value
            if selected is not None and selected.no_trade_reason_code is not None
            else None
        ),
        release_conditions=(tuple(item.value for item in selected.release_conditions) if selected else ()),
        review_triggers=(tuple(item.value for item in selected.review_triggers) if selected else ()),
        source_refs=result.source_refs,
    )
    context = GoldDailyCloseContextBundle(
        result_id=result.result_id,
        current_feature_id=result.current_feature_id,
        previous_feature_id=result.previous_feature_id,
        previous_state_id=result.previous_state_id,
        selected_state_id=result.selected_state_id,
        previous_strategy_id=result.previous_strategy_id,
        selected_strategy_id=result.selected_strategy_id,
        transition_decision_hash=result.transition_decision.decision_hash,
        consistency_decision_id=(result.consistency_decision.decision_id if result.consistency_decision else None),
        source_refs=result.source_refs,
    )
    return GoldDailyCloseDeliveryArtifacts(
        strategy_diff=strategy_diff,
        final_report=final_report,
        context_bundle=context,
        token_trace=GoldDailyCloseTokenTrace(
            result_id=result.result_id,
            skip_reason=(
                "no_material_change"
                if loop_input.transition_evidence.delta_kind.value == "no_op"
                else "deterministic_policy"
            ),
        ),
    )
