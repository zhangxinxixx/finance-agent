"""Typed, deterministic report context for authoritative Gold daily closes."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from apps.analysis.gold_policy.cme_options_regime import CMEOptionsRegimeSnapshot
from apps.analysis.gold_policy.consistency_schemas import (
    AnalysisStrategyConsistencyDecision,
)
from apps.analysis.gold_policy.daily_close_schemas import (
    AnalysisStateContract,
    DailyCloseLoopInput,
    DailyCloseLoopResult,
    GoldAnalysisDecisionContract,
    GoldPriceAttributionContract,
    StateTransitionDecisionContract,
    StrategyDecisionContract,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
)
from apps.analysis.gold_policy.schemas import (
    AnalysisReadiness,
    FeatureSnapshot,
    FeatureSnapshotContract,
    FeatureSnapshotInput,
    FeatureSnapshotV2,
    FeatureSnapshotV2Input,
    OfficialEvent,
    ReadinessProhibitedOutput,
    SourceReference,
)
from apps.analysis.gold_policy.state_schemas import TransitionAction
from apps.analysis.gold_policy.strategy_schemas import (
    ReleaseConditionCode,
    ReviewTriggerCode,
    StrategyStatus,
)


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")

ArtifactType = Literal[
    "authority_result",
    "analysis_decision",
    "price_attribution",
    "candidate_state",
    "selected_state",
    "transition_decision",
    "candidate_strategy",
    "selected_strategy",
    "consistency_decision",
    "key_level",
    "key_level_decision",
]
UnresolvedItemKind = Literal[
    "missing_required_input",
    "missing_confirmatory_input",
    "prohibited_output",
    "pending_transition",
    "strategy_reason",
    "release_condition",
    "review_trigger",
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldReportInputSnapshotIds(_FrozenContract):
    """Structured lineage for every snapshot consumed by the report projection."""

    current_feature: str = Field(pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$")
    previous_feature: str | None = Field(
        default=None,
        pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$",
    )
    options: str = Field(pattern=r"^(?:strategy_options_regime|cme_options_regime)\.v1:[0-9a-f]{64}$")
    event_risk: str = Field(pattern=r"^strategy_event_risk\.v1:[0-9a-f]{64}$")


class GoldReportArtifactIdentityRef(_FrozenContract):
    """A typed content identity; paths are deliberately outside this contract."""

    artifact_type: ArtifactType
    identity_kind: Literal["id", "hash"]
    identity: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_typed_identity(self) -> "GoldReportArtifactIdentityRef":
        prefixes = {
            "authority_result": "gold_daily_close_loop_result.v1:",
            "analysis_decision": "gold_analysis_decision.v2:",
            "price_attribution": "gold_price_attribution.v2:",
            "candidate_state": "analysis_state.v",
            "selected_state": "analysis_state.v",
            "candidate_strategy": "strategy_decision.v",
            "selected_strategy": "strategy_decision.v",
            "consistency_decision": "analysis_strategy_consistency_decision.v1:",
            "key_level": "key_level_read_model.v1:",
        }
        if self.artifact_type in {"transition_decision", "key_level_decision"}:
            if self.identity_kind != "hash" or not _HEX_64.fullmatch(self.identity):
                raise ValueError("hash artifact refs require a canonical sha256 identity")
            return self
        if self.identity_kind != "id" or not self.identity.startswith(prefixes[self.artifact_type]):
            raise ValueError("artifact ref identity does not match its declared type")
        suffix = self.identity.rsplit(":", 1)[-1]
        if not _HEX_64.fullmatch(suffix):
            raise ValueError("artifact ref ids must end in a canonical sha256 identity")
        return self


class GoldReportUnresolvedItem(_FrozenContract):
    """A deterministic unresolved fact, never a generated narrative."""

    kind: UnresolvedItemKind
    code: str = Field(min_length=1)


class GoldReportContextV1(_FrozenContract):
    """Frozen legacy context used only to verify historical v1 bundles."""

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
    def _validate_legacy_identity_and_bindings(self) -> "GoldReportContextV1":
        if self.analysis_decision.current_snapshot_id != self.current_feature_id:
            raise ValueError("report analysis must bind the current feature")
        if self.price_attribution.current_snapshot_id != self.current_feature_id:
            raise ValueError("report attribution must bind the current feature")
        if self.analysis_decision.previous_snapshot_id != (self.previous_feature_id or "missing"):
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
        if self.selected_strategy is not None and (
            self.selected_strategy.analysis_state_id != self.selected_state.state_id
        ):
            raise ValueError("report selected strategy must bind the selected state")
        digest = _digest_payload(self.model_dump(mode="json", exclude={"payload_hash", "context_id"}))
        if self.payload_hash != digest or self.context_id != f"gold_report_context.v1:{digest}":
            raise ValueError("report context identity does not match canonical payload")
        return self


class GoldReportContextV1_1(_FrozenContract):
    """A report-only projection that keeps every conclusion typed and bound."""

    schema_version: Literal["gold_report_context.v1.1"] = "gold_report_context.v1.1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    trade_date: date
    session: Literal["daily_close"] = "daily_close"
    run_id: str = Field(min_length=1, max_length=128, pattern=_RUN_ID.pattern)
    snapshot_id: str = Field(pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$")
    authority_result_id: str
    current_feature_id: str
    previous_feature_id: str | None
    decision_as_of: datetime
    input_snapshot_ids: GoldReportInputSnapshotIds
    cme_options_snapshot: CMEOptionsRegimeSnapshot | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    artifact_refs: tuple[GoldReportArtifactIdentityRef, ...]
    analysis_decision: GoldAnalysisDecisionContract
    price_attribution: GoldPriceAttributionContract
    candidate_state: AnalysisStateContract | None
    selected_state: AnalysisStateContract | None
    transition_decision: StateTransitionDecisionContract
    transition_action: TransitionAction
    transition_reasons: tuple[str, ...] = Field(min_length=1)
    candidate_strategy: StrategyDecisionContract | None
    selected_strategy: StrategyDecisionContract | None
    strategy_projection_source: Literal["selected", "candidate", "unavailable"]
    strategy_reason_codes: tuple[str, ...]
    strategy_release_conditions: tuple[ReleaseConditionCode, ...]
    strategy_review_triggers: tuple[ReviewTriggerCode, ...]
    strategy_invalidation_level_ids: tuple[str, ...]
    consistency_decision: AnalysisStrategyConsistencyDecision | None
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    readiness_projection: Literal[
        "feature_snapshot_v2_bound",
        "feature_snapshot_v2_runtime_controls_bound",
        "feature_snapshot_v1_conservative",
    ]
    readiness_policy_version: str = Field(min_length=1)
    analysis_readiness: AnalysisReadiness
    strategy_readiness: AnalysisReadiness
    options_readiness: AnalysisReadiness
    event_attribution_readiness: AnalysisReadiness
    missing_required_inputs: tuple[str, ...]
    missing_confirmatory_inputs: tuple[str, ...]
    prohibited_outputs: tuple[ReadinessProhibitedOutput, ...]
    readiness_reason_codes: tuple[str, ...]
    major_events: tuple[OfficialEvent, ...] = Field(
        description=(
            "Formal current FeatureSnapshot official_events projection; the context "
            "does not independently classify events as major."
        )
    )
    unresolved_items: tuple[GoldReportUnresolvedItem, ...]
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    language_generation: Literal["not_invoked"] = "not_invoked"
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_id: str = Field(pattern=r"^gold_report_context\.v1\.1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity_and_bindings(self) -> "GoldReportContextV1_1":
        if self.trade_date != self.decision_as_of.astimezone(UTC).date():
            raise ValueError("report trade_date must match the UTC daily-close decision")
        if self.snapshot_id != self.current_feature_id:
            raise ValueError("report snapshot identity must bind the current feature")
        if self.input_snapshot_ids.current_feature != self.current_feature_id:
            raise ValueError("report input lineage must bind the current feature")
        if self.input_snapshot_ids.previous_feature != self.previous_feature_id:
            raise ValueError("report input lineage must bind the previous feature")
        if self.cme_options_snapshot is not None and (
            self.cme_options_snapshot.snapshot_id != self.input_snapshot_ids.options
            or self.cme_options_snapshot.source_snapshot_id != self.current_feature_id
            or self.cme_options_snapshot.as_of != self.decision_as_of
        ):
            raise ValueError("formal CME options projection must bind report inputs")
        if self.analysis_decision.current_snapshot_id != self.current_feature_id:
            raise ValueError("report analysis must bind the current feature")
        if self.price_attribution.current_snapshot_id != self.current_feature_id:
            raise ValueError("report attribution must bind the current feature")
        expected_previous = self.previous_feature_id or "missing"
        if self.analysis_decision.previous_snapshot_id != expected_previous:
            raise ValueError("report analysis must bind the previous feature")
        if self.price_attribution.previous_snapshot_id != expected_previous:
            raise ValueError("report attribution must bind the previous feature")
        if self.candidate_state is None:
            if self.transition_decision.to_state_id is not None:
                raise ValueError("a missing candidate state requires an unbound transition")
            if self.candidate_strategy is not None or self.consistency_decision is not None:
                raise ValueError("a missing candidate state cannot have downstream artifacts")
        else:
            if self.transition_decision.to_state_id != self.candidate_state.state_id:
                raise ValueError("report transition must bind the candidate state")
            if self.candidate_strategy is None or self.consistency_decision is None:
                raise ValueError("a candidate state requires the complete strategy chain")
            if self.candidate_strategy.analysis_state_id != self.candidate_state.state_id:
                raise ValueError("report candidate strategy must bind the candidate state")
            if self.candidate_strategy.options_snapshot_id != self.input_snapshot_ids.options:
                raise ValueError("report candidate strategy must bind the options snapshot")
            if self.candidate_strategy.event_risk_snapshot_id != self.input_snapshot_ids.event_risk:
                raise ValueError("report candidate strategy must bind the event-risk snapshot")
            if self.consistency_decision.candidate_strategy_id != self.candidate_strategy.decision_id:
                raise ValueError("report consistency decision must bind the candidate strategy")
        if self.selected_strategy is not None and self.selected_state is None:
            raise ValueError("a selected strategy requires a selected state")
        if self.selected_strategy is not None and (
            self.selected_strategy.analysis_state_id != self.selected_state.state_id
        ):
            raise ValueError("report selected strategy must bind the selected state")
        if self.transition_action is not self.transition_decision.action:
            raise ValueError("transition action projection does not match the typed decision")
        if self.transition_reasons != _stable_strings(self.transition_decision.reasons):
            raise ValueError("transition reasons projection does not match the typed decision")
        strategy = self.selected_strategy or self.candidate_strategy
        expected_source = (
            "selected"
            if self.selected_strategy is not None
            else "candidate"
            if self.candidate_strategy is not None
            else "unavailable"
        )
        if self.strategy_projection_source != expected_source:
            raise ValueError("strategy projection source does not match available artifacts")
        expected_strategy = _strategy_projection(strategy)
        if (
            self.strategy_reason_codes,
            self.strategy_release_conditions,
            self.strategy_review_triggers,
            self.strategy_invalidation_level_ids,
        ) != expected_strategy:
            raise ValueError("strategy fact projection does not match the typed decision")
        if self.artifact_refs != _artifact_refs(
            authority_result_id=self.authority_result_id,
            analysis_decision=self.analysis_decision,
            price_attribution=self.price_attribution,
            candidate_state=self.candidate_state,
            selected_state=self.selected_state,
            transition_decision=self.transition_decision,
            candidate_strategy=self.candidate_strategy,
            selected_strategy=self.selected_strategy,
            consistency_decision=self.consistency_decision,
            key_levels=self.key_levels,
            key_level_decisions=self.key_level_decisions,
        ):
            raise ValueError("artifact refs must exactly match typed report artifacts")
        if self.unresolved_items != _unresolved_items(
            missing_required_inputs=self.missing_required_inputs,
            missing_confirmatory_inputs=self.missing_confirmatory_inputs,
            prohibited_outputs=self.prohibited_outputs,
            state=self.selected_state or self.candidate_state,
            strategy=strategy,
        ):
            raise ValueError("unresolved items must be derived only from typed facts")
        _revalidate_nested_contracts(self)
        digest = _digest(self)
        if self.payload_hash != digest or self.context_id != f"gold_report_context.v1.1:{digest}":
            raise ValueError("report context identity does not match canonical payload")
        return self


# The current public context type is v1.1.  The named v1 class remains frozen for
# byte-for-byte verification of already persisted bundles.
GoldReportContextContract = GoldReportContextV1 | GoldReportContextV1_1
GoldReportContext = GoldReportContextV1_1


def build_gold_report_context(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    *,
    run_id: str,
) -> GoldReportContext:
    """Project only canonical typed daily-close artifacts into report context."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsafe path characters")
    loop_input = _revalidate_loop_input(loop_input)
    result = _revalidate_loop_result(result)
    _validate_loop_result_binding(loop_input, result)

    selected_strategy = (
        result.candidate_strategy
        if result.selected_strategy_id == getattr(result.candidate_strategy, "decision_id", None)
        else loop_input.previous_strategy
    )
    selected_state = (
        result.analysis_state
        if result.selected_state_id == getattr(result.analysis_state, "state_id", None)
        else loop_input.previous_state
    )
    strategy = selected_strategy or result.candidate_strategy
    strategy_projection = _strategy_projection(strategy)
    readiness = _readiness_projection(loop_input)
    key_levels = tuple(sorted(loop_input.key_levels, key=lambda item: item.state_id))
    key_level_decisions = tuple(sorted(loop_input.key_level_decisions, key=lambda item: item.decision_hash))
    major_events = _canonical_events(loop_input.current_feature.official_events.events)
    input_snapshot_ids = GoldReportInputSnapshotIds(
        current_feature=loop_input.current_feature.snapshot_id,
        previous_feature=(loop_input.previous_feature.snapshot_id if loop_input.previous_feature is not None else None),
        options=loop_input.options_regime.snapshot_id,
        event_risk=loop_input.event_risk.snapshot_id,
    )
    artifact_refs = _artifact_refs(
        authority_result_id=result.result_id,
        analysis_decision=result.analysis_decision,
        price_attribution=result.price_attribution,
        candidate_state=result.analysis_state,
        selected_state=selected_state,
        transition_decision=result.transition_decision,
        candidate_strategy=result.candidate_strategy,
        selected_strategy=selected_strategy,
        consistency_decision=result.consistency_decision,
        key_levels=key_levels,
        key_level_decisions=key_level_decisions,
    )
    unresolved_items = _unresolved_items(
        missing_required_inputs=readiness[6],
        missing_confirmatory_inputs=readiness[7],
        prohibited_outputs=readiness[8],
        state=selected_state or result.analysis_state,
        strategy=strategy,
    )
    payload = {
        "schema_version": "gold_report_context.v1.1",
        "asset": loop_input.asset,
        "trade_date": result.decision_as_of.astimezone(UTC).date(),
        "session": loop_input.scope,
        "run_id": run_id,
        "snapshot_id": result.current_feature_id,
        "authority_result_id": result.result_id,
        "current_feature_id": result.current_feature_id,
        "previous_feature_id": result.previous_feature_id,
        "decision_as_of": result.decision_as_of,
        "input_snapshot_ids": input_snapshot_ids,
        "artifact_refs": artifact_refs,
        "analysis_decision": result.analysis_decision,
        "price_attribution": result.price_attribution,
        "candidate_state": result.analysis_state,
        "selected_state": selected_state,
        "transition_decision": result.transition_decision,
        "transition_action": result.transition_decision.action,
        "transition_reasons": _stable_strings(result.transition_decision.reasons),
        "candidate_strategy": result.candidate_strategy,
        "selected_strategy": selected_strategy,
        "strategy_projection_source": (
            "selected"
            if selected_strategy is not None
            else "candidate"
            if result.candidate_strategy is not None
            else "unavailable"
        ),
        "strategy_reason_codes": strategy_projection[0],
        "strategy_release_conditions": strategy_projection[1],
        "strategy_review_triggers": strategy_projection[2],
        "strategy_invalidation_level_ids": strategy_projection[3],
        "consistency_decision": result.consistency_decision,
        "key_levels": key_levels,
        "key_level_decisions": key_level_decisions,
        "readiness_projection": readiness[0],
        "readiness_policy_version": readiness[1],
        "analysis_readiness": readiness[2],
        "strategy_readiness": readiness[3],
        "options_readiness": readiness[4],
        "event_attribution_readiness": readiness[5],
        "missing_required_inputs": readiness[6],
        "missing_confirmatory_inputs": readiness[7],
        "prohibited_outputs": readiness[8],
        "readiness_reason_codes": readiness[9],
        "major_events": major_events,
        "unresolved_items": unresolved_items,
        "source_refs": _canonical_refs(result.source_refs),
        "language_generation": "not_invoked",
    }
    if isinstance(loop_input.options_regime, CMEOptionsRegimeSnapshot):
        payload["cme_options_snapshot"] = loop_input.options_regime
    digest = _digest_payload(payload)
    return GoldReportContext(
        **payload,
        payload_hash=digest,
        context_id=f"gold_report_context.v1.1:{digest}",
    )


def build_gold_report_context_v1_1(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    *,
    run_id: str,
) -> GoldReportContextV1_1:
    """Explicit-version entrypoint for the current v1.1 projection."""

    return build_gold_report_context(loop_input, result, run_id=run_id)


def build_gold_report_context_v1(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> GoldReportContextV1:
    """Rebuild the frozen legacy context for historical bundle verification only."""

    selected = (
        result.candidate_strategy
        if result.selected_strategy_id == getattr(result.candidate_strategy, "decision_id", None)
        else loop_input.previous_strategy
    )
    selected_state = (
        result.analysis_state
        if result.selected_state_id == getattr(result.analysis_state, "state_id", None)
        else loop_input.previous_state
    )
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
    return GoldReportContextV1(
        **payload,
        payload_hash=digest,
        context_id=f"gold_report_context.v1:{digest}",
    )


def _revalidate_loop_input(value: DailyCloseLoopInput) -> DailyCloseLoopInput:
    if not isinstance(value, DailyCloseLoopInput):
        raise TypeError("loop_input must be a DailyCloseLoopInput")
    rebuilt = DailyCloseLoopInput.model_validate(value.model_dump(mode="python"))
    current = _rebuild_feature(rebuilt.current_feature)
    previous = _rebuild_feature(rebuilt.previous_feature) if rebuilt.previous_feature is not None else None
    if current != value.current_feature or previous != value.previous_feature:
        raise ValueError("report input feature identity or derived fields are invalid")
    return rebuilt


def _revalidate_loop_result(value: DailyCloseLoopResult) -> DailyCloseLoopResult:
    if not isinstance(value, DailyCloseLoopResult):
        raise TypeError("result must be a DailyCloseLoopResult")
    return DailyCloseLoopResult.model_validate(value.model_dump(mode="python"))


def _rebuild_feature(feature: FeatureSnapshotContract) -> FeatureSnapshotContract:
    excluded = {"data_quality", "payload_hash", "snapshot_id"}
    if isinstance(feature, FeatureSnapshotV2):
        excluded.update(
            {
                "real10y_estimated",
                "real10y_basis_bp",
                "real10y_alignment",
                "real10y_reason_codes",
                "real10y_quality",
            }
        )
        source = FeatureSnapshotV2Input.model_validate(feature.model_dump(mode="python", exclude=excluded))
    elif isinstance(feature, FeatureSnapshot):
        source = FeatureSnapshotInput.model_validate(feature.model_dump(mode="python", exclude=excluded))
    else:
        raise TypeError("unsupported FeatureSnapshot contract")
    rebuilt = build_feature_snapshot(source)
    if rebuilt != feature:
        raise ValueError("feature snapshot identity or derived fields are invalid")
    return rebuilt


def _validate_loop_result_binding(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> None:
    expected_previous = loop_input.previous_feature.snapshot_id if loop_input.previous_feature is not None else None
    if (
        result.asset != loop_input.asset
        or result.scope != loop_input.scope
        or result.decision_as_of != loop_input.decision_as_of
        or result.current_feature_id != loop_input.current_feature.snapshot_id
        or result.previous_feature_id != expected_previous
    ):
        raise ValueError("daily-close result does not bind the supplied loop input")
    if result.strategy_policy_input is not None and (
        result.strategy_policy_input.feature_snapshot != loop_input.current_feature
        or result.strategy_policy_input.options_regime != loop_input.options_regime
        or result.strategy_policy_input.event_risk != loop_input.event_risk
        or result.strategy_policy_input.key_levels != loop_input.key_levels
        or result.strategy_policy_input.key_level_decisions != loop_input.key_level_decisions
    ):
        raise ValueError("strategy policy input does not bind the supplied loop input")


def _readiness_projection(
    loop_input: DailyCloseLoopInput,
) -> tuple[
    Literal[
        "feature_snapshot_v2_bound",
        "feature_snapshot_v2_runtime_controls_bound",
        "feature_snapshot_v1_conservative",
    ],
    str,
    AnalysisReadiness,
    AnalysisReadiness,
    AnalysisReadiness,
    AnalysisReadiness,
    tuple[str, ...],
    tuple[str, ...],
    tuple[ReadinessProhibitedOutput, ...],
    tuple[str, ...],
]:
    feature = loop_input.current_feature
    if isinstance(feature, FeatureSnapshotV2):
        quality = feature.data_quality
        if isinstance(loop_input.options_regime, CMEOptionsRegimeSnapshot):
            options_snapshot = loop_input.options_regime
            if options_snapshot.quality_status == "blocked" or options_snapshot.regime.value == "unavailable":
                options: AnalysisReadiness = "blocked"
            elif (
                options_snapshot.quality_status != "accepted"
                or options_snapshot.freshness_status != "fresh"
                or options_snapshot.alignment_status != "aligned"
                or options_snapshot.directional_bias not in {"bullish", "bearish"}
            ):
                options = "observe"
            else:
                options = "ready"
            strategy: AnalysisReadiness = quality.strategy_readiness
            if options != "ready" and strategy == "ready":
                strategy = "observe"
            prohibited = set(quality.prohibited_outputs)
            reasons = list(quality.reason_codes)
            reasons.extend(options_snapshot.reason_codes)
            if options != "ready":
                prohibited.update(("OPTIONS_CONFIRMATION", "TRIGGERED_STRATEGY"))
                reasons.append("FORMAL_OPTIONS_DIRECTIONAL_CONFIRMATION_NOT_READY")
            return (
                "feature_snapshot_v2_runtime_controls_bound",
                "gold_report_context.v1.1:runtime_controls_overlay.v1",
                quality.analysis_readiness,
                strategy,
                options,
                quality.event_attribution_readiness,
                quality.missing_required_inputs,
                quality.missing_confirmatory_inputs,
                tuple(sorted(prohibited)),
                _stable_strings(reasons),
            )
        return (
            "feature_snapshot_v2_bound",
            quality.readiness_policy_version,
            quality.analysis_readiness,
            quality.strategy_readiness,
            quality.options_readiness,
            quality.event_attribution_readiness,
            quality.missing_required_inputs,
            quality.missing_confirmatory_inputs,
            quality.prohibited_outputs,
            quality.reason_codes,
        )

    analysis = feature.data_quality.analysis_readiness
    strategy: AnalysisReadiness = "blocked" if analysis == "blocked" else "observe"
    options: AnalysisReadiness = (
        "blocked"
        if loop_input.options_regime.quality_status == "blocked"
        or loop_input.options_regime.regime.value == "unavailable"
        else "observe"
    )
    events: AnalysisReadiness = (
        "blocked"
        if feature.official_events.quality_status == "blocked"
        or loop_input.event_risk.quality_status == "blocked"
        or loop_input.event_risk.risk_status.value == "unavailable"
        else "observe"
    )
    prohibited: list[ReadinessProhibitedOutput] = []
    if analysis == "blocked":
        prohibited.extend(("DIRECTIONAL_ANALYSIS", "DIRECTIONAL_STRATEGY"))
    if strategy != "ready":
        prohibited.append("TRIGGERED_STRATEGY")
    if options != "ready":
        prohibited.append("OPTIONS_CONFIRMATION")
    if events != "ready":
        prohibited.append("CONFIRMED_EVENT_ATTRIBUTION")
    reasons = [
        "LEGACY_FEATURE_SNAPSHOT_V1_CONSERVATIVE_PROJECTION",
        f"LEGACY_ANALYSIS_READINESS_BOUND:{analysis.upper()}",
        ("LEGACY_STRATEGY_INPUT_BLOCKED" if strategy == "blocked" else "LEGACY_STRATEGY_READINESS_CAPPED_AT_OBSERVE"),
        ("LEGACY_OPTIONS_INPUT_BLOCKED" if options == "blocked" else "LEGACY_OPTIONS_READINESS_CAPPED_AT_OBSERVE"),
        (
            "LEGACY_EVENT_INPUT_BLOCKED"
            if events == "blocked"
            else "LEGACY_EVENT_ATTRIBUTION_READINESS_CAPPED_AT_OBSERVE"
        ),
        "LEGACY_MISSING_INPUT_CLASSIFICATION_UNAVAILABLE",
    ]
    return (
        "feature_snapshot_v1_conservative",
        "gold_report_context.v1.1:legacy_feature_snapshot_v1_conservative",
        analysis,
        strategy,
        options,
        events,
        (),
        (),
        tuple(sorted(set(prohibited))),
        _stable_strings(reasons),
    )


def _strategy_projection(
    strategy: StrategyDecisionContract | None,
) -> tuple[
    tuple[str, ...],
    tuple[ReleaseConditionCode, ...],
    tuple[ReviewTriggerCode, ...],
    tuple[str, ...],
]:
    if strategy is None:
        return (), (), (), ()
    return (
        _stable_strings(strategy.reason_codes),
        tuple(sorted(set(strategy.release_conditions), key=lambda item: item.value)),
        tuple(sorted(set(strategy.review_triggers), key=lambda item: item.value)),
        _stable_strings(strategy.invalidation_level_ids),
    )


def _artifact_refs(
    *,
    authority_result_id: str,
    analysis_decision: GoldAnalysisDecisionContract,
    price_attribution: GoldPriceAttributionContract,
    candidate_state: AnalysisStateContract | None,
    selected_state: AnalysisStateContract | None,
    transition_decision: StateTransitionDecisionContract,
    candidate_strategy: StrategyDecisionContract | None,
    selected_strategy: StrategyDecisionContract | None,
    consistency_decision: AnalysisStrategyConsistencyDecision | None,
    key_levels: tuple[KeyLevelReadModel, ...],
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...],
) -> tuple[GoldReportArtifactIdentityRef, ...]:
    raw: list[tuple[ArtifactType, Literal["id", "hash"], str]] = [
        ("authority_result", "id", authority_result_id),
        ("transition_decision", "hash", transition_decision.decision_hash),
    ]
    analysis_id = getattr(analysis_decision, "decision_id", None)
    if analysis_id is not None:
        raw.append(("analysis_decision", "id", analysis_id))
    attribution_id = getattr(price_attribution, "attribution_id", None)
    if attribution_id is not None:
        raw.append(("price_attribution", "id", attribution_id))
    for artifact_type, artifact in (
        ("candidate_state", candidate_state),
        ("selected_state", selected_state),
    ):
        if artifact is not None:
            raw.append((artifact_type, "id", artifact.state_id))
    for artifact_type, artifact in (
        ("candidate_strategy", candidate_strategy),
        ("selected_strategy", selected_strategy),
    ):
        if artifact is not None:
            raw.append((artifact_type, "id", artifact.decision_id))
    if consistency_decision is not None:
        raw.append(("consistency_decision", "id", consistency_decision.decision_id))
    raw.extend(("key_level", "id", item.state_id) for item in key_levels)
    raw.extend(("key_level_decision", "hash", item.decision_hash) for item in key_level_decisions)
    unique = {(artifact_type, identity_kind, identity) for artifact_type, identity_kind, identity in raw}
    return tuple(
        GoldReportArtifactIdentityRef(
            artifact_type=artifact_type,
            identity_kind=identity_kind,
            identity=identity,
        )
        for artifact_type, identity_kind, identity in sorted(unique)
    )


def _canonical_events(events: tuple[OfficialEvent, ...]) -> tuple[OfficialEvent, ...]:
    unique: dict[str, OfficialEvent] = {}
    for event in events:
        existing = unique.get(event.event_id)
        if existing is not None and existing != event:
            raise ValueError("official event ids must not bind conflicting payloads")
        unique[event.event_id] = event
    return tuple(
        sorted(
            unique.values(),
            key=lambda event: (event.occurred_at, event.event_id),
        )
    )


def _unresolved_items(
    *,
    missing_required_inputs: tuple[str, ...],
    missing_confirmatory_inputs: tuple[str, ...],
    prohibited_outputs: tuple[ReadinessProhibitedOutput, ...],
    state: AnalysisStateContract | None,
    strategy: StrategyDecisionContract | None,
) -> tuple[GoldReportUnresolvedItem, ...]:
    facts: set[tuple[UnresolvedItemKind, str]] = set()
    facts.update(("missing_required_input", item) for item in missing_required_inputs)
    facts.update(("missing_confirmatory_input", item) for item in missing_confirmatory_inputs)
    facts.update(("prohibited_output", item) for item in prohibited_outputs)
    pending = getattr(state, "pending_transition", None)
    if pending is not None:
        facts.add(
            (
                "pending_transition",
                f"{pending.rule.value}:{pending.direction}:{pending.count}",
            )
        )
    if strategy is not None:
        if strategy.status in {
            StrategyStatus.NO_TRADE,
            StrategyStatus.OBSERVE,
            StrategyStatus.INVALIDATED,
        }:
            facts.update(("strategy_reason", item) for item in strategy.reason_codes)
        facts.update(("release_condition", item.value) for item in strategy.release_conditions)
        facts.update(("review_trigger", item.value) for item in strategy.review_triggers)
    return tuple(GoldReportUnresolvedItem(kind=kind, code=code) for kind, code in sorted(facts))


def _canonical_refs(refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs}
    return tuple(unique[key] for key in sorted(unique))


def _stable_strings(values: tuple[object, ...] | list[object]) -> tuple[str, ...]:
    return tuple(sorted({str(getattr(value, "value", value)) for value in values}))


def _revalidate_nested_contracts(context: GoldReportContext) -> None:
    values = (
        context.analysis_decision,
        context.price_attribution,
        context.candidate_state,
        context.selected_state,
        context.transition_decision,
        context.candidate_strategy,
        context.selected_strategy,
        context.consistency_decision,
        *context.key_levels,
        *context.key_level_decisions,
        *context.major_events,
    )
    for value in values:
        if value is None:
            continue
        rebuilt = type(value).model_validate(value.model_dump(mode="python"))
        if rebuilt != value:
            raise ValueError("nested report artifact failed identity revalidation")


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
