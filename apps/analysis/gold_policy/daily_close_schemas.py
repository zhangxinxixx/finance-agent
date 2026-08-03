"""Immutable contracts for the deterministic XAUUSD daily-close loop."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.analysis_policy import (
    GoldAnalysisDecision,
    GoldAnalysisDecisionV2,
)
from apps.analysis.gold_policy.attribution_policy import (
    GoldPriceAttribution,
    GoldPriceAttributionV2,
)
from apps.analysis.gold_policy.consistency_schemas import AnalysisStrategyConsistencyDecision
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelAuthorityStatus,
    KeyLevelEventType,
    KeyLevelLifecycle,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
    KeyLevelRole,
    KeyLevelRuleCode,
    KeyLevelSourceInstrument,
    KeyLevelSourceRole,
    KeyLevelTransitionAction,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotContract, SourceReference
from apps.analysis.gold_policy.state_schemas import (
    AnalysisState,
    AnalysisStateV2,
    HardInvalidationRule,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
    TransitionEvidence,
)
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyDecision,
    StrategyDecisionV2,
    StrategyEventRiskSnapshot,
    StrategyOptionsRegimeContract,
    StrategyPolicyInput,
    StrategyPolicyInputV2,
)


GoldAnalysisDecisionContract = Annotated[
    GoldAnalysisDecision | GoldAnalysisDecisionV2,
    Field(discriminator="policy_version"),
]
GoldPriceAttributionContract = Annotated[
    GoldPriceAttribution | GoldPriceAttributionV2,
    Field(discriminator="policy_version"),
]
AnalysisStateContract = Annotated[
    AnalysisState | AnalysisStateV2,
    Field(discriminator="schema_version"),
]
StateTransitionDecisionContract = Annotated[
    StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2,
    Field(discriminator="policy_version"),
]
StrategyPolicyInputContract = Annotated[
    StrategyPolicyInput | StrategyPolicyInputV2,
    Field(discriminator="schema_version"),
]
StrategyDecisionContract = Annotated[
    StrategyDecision | StrategyDecisionV2,
    Field(discriminator="schema_version"),
]


def _contract_version(value: object) -> Literal["v1", "v2"]:
    raw = value if isinstance(value, str) else None
    for field_name in ("schema_version", "policy_version"):
        candidate = getattr(value, field_name, None)
        if isinstance(candidate, str):
            raw = candidate
            break
    if not isinstance(raw, str) or ".v" not in raw:
        raise ValueError("versioned daily-close contract is missing its discriminator")
    version = raw.rsplit(".v", 1)[1].split(":", 1)[0]
    if version not in {"1", "2"}:
        raise ValueError("unsupported daily-close contract version")
    return "v1" if version == "1" else "v2"


class CanonicalCommitAction(StrEnum):
    BOOTSTRAP = "bootstrap"
    ADVANCE = "advance"
    MAINTAIN = "maintain"
    HOLD = "hold"


class DailyCloseLoopReason(StrEnum):
    BOOTSTRAP_SELECTED = "BOOTSTRAP_SELECTED"
    ADVANCING_DECISION_SELECTED = "ADVANCING_DECISION_SELECTED"
    NON_ADVANCING_DECISION_SELECTED = "NON_ADVANCING_DECISION_SELECTED"
    CONSISTENCY_GATE_REJECTED = "CONSISTENCY_GATE_REJECTED"
    NO_CANONICAL_STATE_AVAILABLE = "NO_CANONICAL_STATE_AVAILABLE"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyCloseLoopInput(_FrozenContract):
    schema_version: Literal["gold_daily_close_loop_input.v1"] = "gold_daily_close_loop_input.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal["daily_close"] = "daily_close"
    decision_as_of: datetime
    current_feature: FeatureSnapshotContract
    previous_feature: FeatureSnapshotContract | None = None
    previous_policy_input: StrategyPolicyInputContract | None = None
    previous_state: AnalysisStateContract | None = None
    previous_transition: StateTransitionDecisionContract | None = None
    previous_strategy: StrategyDecisionContract | None = None
    transition_evidence: TransitionEvidence
    options_regime: StrategyOptionsRegimeContract
    event_risk: StrategyEventRiskSnapshot
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    key_level_proof: tuple[KeyLevelLifecycleDecision, ...] = ()

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_decision_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_loop_input(self) -> "DailyCloseLoopInput":
        predecessor = (
            self.previous_policy_input,
            self.previous_state,
            self.previous_transition,
            self.previous_strategy,
        )
        if any(item is None for item in predecessor) and any(item is not None for item in predecessor):
            raise ValueError("previous policy input, state, transition, and strategy must be paired")
        if self.current_feature.scope != self.scope:
            raise ValueError("current feature scope must be daily_close")
        current_session_date = self.current_feature.as_of.astimezone(UTC).date()
        if current_session_date != self.decision_as_of.date():
            raise ValueError("current feature must belong to the decision daily-close session")
        if self.previous_feature is not None:
            if self.previous_feature.scope != self.scope:
                raise ValueError("previous feature scope must be daily_close")
            if self.previous_feature.as_of >= self.current_feature.as_of:
                raise ValueError("previous feature must predate current feature")
        if self.transition_evidence.scope.value != self.scope:
            raise ValueError("transition evidence scope must be daily_close")
        if self.transition_evidence.as_of.astimezone(UTC).date() != self.decision_as_of.date():
            raise ValueError("transition evidence must belong to the decision daily-close session")
        if any(
            timestamp > self.decision_as_of
            for timestamp in (
                self.current_feature.as_of,
                self.transition_evidence.as_of,
                self.options_regime.as_of,
                self.event_risk.as_of,
            )
        ):
            raise ValueError("loop inputs cannot be after decision_as_of")
        if self.options_regime.as_of != self.decision_as_of or self.event_risk.as_of != self.decision_as_of:
            raise ValueError("options and event-risk snapshots must align to decision_as_of")
        if self.options_regime.source_snapshot_id != self.current_feature.snapshot_id:
            raise ValueError("options regime must bind the current feature snapshot")
        if self.previous_state is not None:
            if self.previous_feature is None:
                raise ValueError("a canonical predecessor requires its feature snapshot")
            if self.previous_policy_input.feature_snapshot.snapshot_id != self.previous_feature.snapshot_id:
                raise ValueError("previous feature must bind the previous policy input")
            if self.previous_policy_input.analysis_state.state_id != self.previous_state.state_id:
                raise ValueError("previous policy input must bind previous state")
            if self.previous_policy_input.state_transition.decision_hash != self.previous_transition.decision_hash:
                raise ValueError("previous policy input must bind previous transition")
            if self.previous_strategy.analysis_state_id != self.previous_state.state_id:
                raise ValueError("previous strategy must bind previous state")
            if self.previous_strategy.transition_decision_hash != self.previous_transition.decision_hash:
                raise ValueError("previous strategy must bind previous transition")
            predecessor_versions = {
                _contract_version(self.previous_feature),
                _contract_version(self.previous_policy_input),
                _contract_version(self.previous_state),
                _contract_version(self.previous_transition),
                _contract_version(self.previous_strategy),
            }
            if predecessor_versions != {_contract_version(self.current_feature)}:
                raise ValueError("daily-close predecessor contracts must match the current version")
        elif self.previous_feature is not None and _contract_version(self.previous_feature) != _contract_version(
            self.current_feature
        ):
            raise ValueError("bootstrap previous feature must match the current version")
        for values, name, identity in (
            (self.key_levels, "key_levels", lambda item: item.state_id),
            (
                self.key_level_decisions,
                "key_level_decisions",
                lambda item: item.decision_hash,
            ),
            (self.key_level_proof, "key_level_proof", lambda item: item.decision_hash),
        ):
            if len({identity(item) for item in values}) != len(values):
                raise ValueError(f"{name} must contain unique identities")
        self._validate_price_level_invalidation_proof()
        return self

    def _validate_price_level_invalidation_proof(self) -> None:
        expected_role = {
            HardInvalidationRule.CONFIRMED_SUPPORT_BREAK: KeyLevelRole.SUPPORT,
            HardInvalidationRule.CONFIRMED_RESISTANCE_BREAK: KeyLevelRole.RESISTANCE,
        }.get(self.transition_evidence.rule_code)
        if expected_role is None:
            return
        levels = {level.state_id: level for level in self.key_levels}
        decisions = {decision.decision_hash for decision in self.key_level_decisions}
        if not any(
            decision.action is KeyLevelTransitionAction.BREAK
            and decision.advance
            and decision.to_lifecycle is KeyLevelLifecycle.BROKEN
            and decision.to_state_id in levels
            and decision.decision_hash in decisions
            and levels[decision.to_state_id].lifecycle is KeyLevelLifecycle.BROKEN
            and levels[decision.to_state_id].authority_status is KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
            and levels[decision.to_state_id].quality_status == "accepted"
            and levels[decision.to_state_id].spec == decision.event.spec
            and levels[decision.to_state_id].last_event_id == decision.event.event_id
            and levels[decision.to_state_id].as_of == self.transition_evidence.as_of
            and decision.event.event_type is KeyLevelEventType.BREAK_CONFIRMED
            and decision.event.spec.role is expected_role
            and decision.event.spec.scope is self.transition_evidence.scope
            and decision.event.evidence.source_role is KeyLevelSourceRole.OFFICIAL_MARKET
            and decision.event.evidence.source_instrument is KeyLevelSourceInstrument.XAUUSD_SPOT
            and decision.event.evidence.scope is self.transition_evidence.scope
            and decision.event.evidence.as_of == self.transition_evidence.as_of
            and decision.triggered_rule is KeyLevelRuleCode.BREAK_CANONICAL_WINDOW
            for decision in self.key_level_proof
        ):
            raise ValueError("price-level hard invalidation requires matching canonical XAUUSD break proof")


class DailyCloseLoopResultInput(_FrozenContract):
    schema_version: Literal["gold_daily_close_loop_result.v1"] = "gold_daily_close_loop_result.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal["daily_close"] = "daily_close"
    decision_as_of: datetime
    current_feature_id: str = Field(pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$")
    previous_feature_id: str | None = Field(
        default=None,
        pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$",
    )
    previous_state_id: str | None = Field(
        default=None,
        pattern=r"^analysis_state\.v[12]:[0-9a-f]{64}$",
    )
    previous_strategy_id: str | None = Field(
        default=None,
        pattern=r"^strategy_decision\.v[12]:[0-9a-f]{64}$",
    )
    analysis_decision: GoldAnalysisDecisionContract
    price_attribution: GoldPriceAttributionContract
    transition_decision: StateTransitionDecisionContract
    analysis_state: AnalysisStateContract | None = None
    strategy_policy_input: StrategyPolicyInputContract | None = None
    candidate_strategy: StrategyDecisionContract | None = None
    consistency_decision: AnalysisStrategyConsistencyDecision | None = None
    canonical_action: CanonicalCommitAction
    selected_state_id: str | None = Field(
        default=None,
        pattern=r"^analysis_state\.v[12]:[0-9a-f]{64}$",
    )
    selected_strategy_id: str | None = Field(
        default=None,
        pattern=r"^strategy_decision\.v[12]:[0-9a-f]{64}$",
    )
    reason_codes: tuple[DailyCloseLoopReason, ...] = Field(min_length=1)
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    model_invocations: Literal[0] = 0
    policy_version: Literal["gold_daily_close_loop_policy.v1"] = "gold_daily_close_loop_policy.v1"

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_decision_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("source_refs")
    @classmethod
    def _canonicalize_source_refs(
        cls,
        values: tuple[SourceReference, ...],
    ) -> tuple[SourceReference, ...]:
        return tuple(
            sorted(
                values,
                key=lambda ref: (ref.source, ref.reference, ref.retrieved_at),
            )
        )

    @model_validator(mode="after")
    def _validate_result(self) -> "DailyCloseLoopResultInput":
        if (self.previous_state_id is None) != (self.previous_strategy_id is None):
            raise ValueError("previous canonical state and strategy identities must be paired")
        if self.previous_state_id is not None and self.previous_feature_id is None:
            raise ValueError("a previous canonical head requires its feature identity")
        if self.analysis_decision.current_snapshot_id != self.current_feature_id:
            raise ValueError("analysis decision must bind the current feature")
        if self.price_attribution.current_snapshot_id != self.current_feature_id:
            raise ValueError("price attribution must bind the current feature")
        expected_previous_feature_id = self.previous_feature_id or "missing"
        if self.analysis_decision.previous_snapshot_id != expected_previous_feature_id:
            raise ValueError("analysis decision must bind the previous feature")
        if self.price_attribution.previous_snapshot_id != expected_previous_feature_id:
            raise ValueError("price attribution must bind the previous feature")
        versions = {
            _contract_version(self.current_feature_id),
            _contract_version(self.analysis_decision),
            _contract_version(self.price_attribution),
            _contract_version(self.transition_decision),
        }
        if self.analysis_state is not None:
            versions.update(
                {
                    _contract_version(self.analysis_state),
                    _contract_version(self.strategy_policy_input),
                    _contract_version(self.candidate_strategy),
                }
            )
        if len(versions) != 1:
            raise ValueError("daily-close result contracts must use one version family")
        if self.transition_decision.from_state_id != self.previous_state_id:
            raise ValueError("transition must start from the previous canonical state")
        if self.transition_decision.evidence.as_of > self.decision_as_of:
            raise ValueError("transition evidence cannot be after decision_as_of")
        if len({(ref.source, ref.reference, ref.retrieved_at) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("source_refs must be unique")
        for ref in self.source_refs:
            if ref.retrieved_at.tzinfo is None or ref.retrieved_at.utcoffset() is None:
                raise ValueError("source_refs must use timezone-aware timestamps")
            if ref.retrieved_at.astimezone(UTC) > self.decision_as_of:
                raise ValueError("source_refs cannot be after decision_as_of")
        downstream = (
            self.analysis_state,
            self.strategy_policy_input,
            self.candidate_strategy,
            self.consistency_decision,
        )
        if self.analysis_state is None:
            if any(item is not None for item in downstream[1:]):
                raise ValueError("a missing analysis state cannot have downstream strategy artifacts")
            if self.canonical_action is not CanonicalCommitAction.HOLD:
                raise ValueError("a missing analysis state must hold the canonical head")
            if self.selected_state_id is not None or self.selected_strategy_id is not None:
                raise ValueError("an unbootstrapped hold cannot select canonical identities")
            if self.transition_decision.to_state_id is not None:
                raise ValueError("a missing analysis state requires a transition without a target state")
            if self.previous_state_id is not None:
                raise ValueError("only an unbootstrapped run may omit the analysis state")
            if self.reason_codes != (DailyCloseLoopReason.NO_CANONICAL_STATE_AVAILABLE,):
                raise ValueError("an unbootstrapped hold requires its explicit reason")
            return self
        if any(item is None for item in downstream):
            raise ValueError("an available analysis state requires the complete downstream chain")
        if self.strategy_policy_input.analysis_state.state_id != self.analysis_state.state_id:
            raise ValueError("strategy policy input must bind the result state")
        if self.strategy_policy_input.feature_snapshot.snapshot_id != self.current_feature_id:
            raise ValueError("strategy policy input must bind the current feature")
        if self.strategy_policy_input.price_attribution != self.price_attribution:
            raise ValueError("strategy policy input must bind the result attribution")
        if self.transition_decision.to_state_id != self.analysis_state.state_id:
            raise ValueError("transition must target the result state")
        if self.strategy_policy_input.state_transition.decision_hash != self.transition_decision.decision_hash:
            raise ValueError("strategy policy input must bind the result transition")
        if self.candidate_strategy.analysis_state_id != self.analysis_state.state_id:
            raise ValueError("candidate strategy must bind the result state")
        if self.candidate_strategy.feature_snapshot_id != self.current_feature_id:
            raise ValueError("candidate strategy must bind the current feature")
        if self.candidate_strategy.attribution_snapshot_ids != (
            self.price_attribution.previous_snapshot_id,
            self.price_attribution.current_snapshot_id,
        ):
            raise ValueError("candidate strategy must bind the result attribution")
        if self.candidate_strategy.transition_decision_hash != self.transition_decision.decision_hash:
            raise ValueError("candidate strategy must bind the result transition")
        if self.candidate_strategy.decision_id != self.consistency_decision.candidate_strategy_id:
            raise ValueError("consistency decision must bind the candidate strategy")
        if self.consistency_decision.current_state_id != self.analysis_state.state_id:
            raise ValueError("consistency decision must bind the result state")
        if self.consistency_decision.previous_state_id != self.previous_state_id:
            raise ValueError("consistency decision must bind the previous state")
        if self.consistency_decision.previous_strategy_id != self.previous_strategy_id:
            raise ValueError("consistency decision must bind the previous strategy")
        if self.consistency_decision.transition_decision_hash != self.transition_decision.decision_hash:
            raise ValueError("consistency decision must bind the result transition")
        if self.consistency_decision.consistency_passed:
            if self.selected_state_id != self.analysis_state.state_id:
                raise ValueError("a consistent result must select the result state")
            if self.selected_strategy_id != self.candidate_strategy.decision_id:
                raise ValueError("a consistent result must select the candidate strategy")
            if self.canonical_action is CanonicalCommitAction.HOLD:
                raise ValueError("a consistent result cannot hold the candidate selection")
            expected_action = (
                CanonicalCommitAction.BOOTSTRAP
                if self.previous_state_id is None
                else (
                    CanonicalCommitAction.ADVANCE
                    if self.transition_decision.advance
                    else CanonicalCommitAction.MAINTAIN
                )
            )
            if self.canonical_action is not expected_action:
                raise ValueError("canonical action must match predecessor and transition semantics")
            expected_reason = {
                CanonicalCommitAction.BOOTSTRAP: DailyCloseLoopReason.BOOTSTRAP_SELECTED,
                CanonicalCommitAction.ADVANCE: DailyCloseLoopReason.ADVANCING_DECISION_SELECTED,
                CanonicalCommitAction.MAINTAIN: DailyCloseLoopReason.NON_ADVANCING_DECISION_SELECTED,
            }[expected_action]
            if self.reason_codes != (expected_reason,):
                raise ValueError("selected canonical action requires its matching reason")
        else:
            if self.canonical_action is not CanonicalCommitAction.HOLD:
                raise ValueError("a rejected consistency result must hold")
            if self.selected_state_id != self.previous_state_id:
                raise ValueError("a rejected result must retain the previous state")
            if self.selected_strategy_id != self.previous_strategy_id:
                raise ValueError("a rejected result must retain the previous strategy")
            if self.reason_codes != (DailyCloseLoopReason.CONSISTENCY_GATE_REJECTED,):
                raise ValueError("a rejected result requires its explicit consistency reason")
        return self


class DailyCloseLoopResult(DailyCloseLoopResultInput):
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_id: str = Field(pattern=r"^gold_daily_close_loop_result\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "DailyCloseLoopResult":
        digest = _sha256(canonical_daily_close_result_json(self))
        if self.result_hash != digest or self.result_id != f"gold_daily_close_loop_result.v1:{digest}":
            raise ValueError("daily-close result identity does not match canonical payload")
        return self


def build_daily_close_loop_result(
    payload: Mapping[str, Any] | DailyCloseLoopResultInput,
) -> DailyCloseLoopResult:
    value = (
        payload if isinstance(payload, DailyCloseLoopResultInput) else DailyCloseLoopResultInput.model_validate(payload)
    )
    normalized = value.model_copy(
        update={
            "reason_codes": tuple(dict.fromkeys(value.reason_codes)),
            "source_refs": tuple(
                sorted(
                    value.source_refs,
                    key=lambda ref: (ref.source, ref.reference, ref.retrieved_at),
                )
            ),
        }
    )
    digest = _sha256(canonical_daily_close_result_json(normalized))
    return DailyCloseLoopResult(
        **normalized.model_dump(),
        result_hash=digest,
        result_id=f"gold_daily_close_loop_result.v1:{digest}",
    )


def canonical_daily_close_result_json(
    value: DailyCloseLoopResultInput | DailyCloseLoopResult,
) -> str:
    payload = value.model_dump(mode="json", exclude={"result_hash", "result_id"})
    payload["source_refs"] = sorted(
        payload["source_refs"],
        key=lambda ref: (ref["source"], ref["reference"], ref["retrieved_at"]),
    )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
