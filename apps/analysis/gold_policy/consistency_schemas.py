"""Immutable contracts for the Analysis-Strategy consistency gate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.key_level_schemas import KeyLevelLifecycleDecision
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import AnalysisState, StateTransitionPolicyDecision
from apps.analysis.gold_policy.strategy_schemas import StrategyDecision, StrategyPolicyInput


class ConsistencyStatus(StrEnum):
    CONSISTENT = "consistent"
    BLOCKED = "blocked"
    UNVERIFIABLE = "unverifiable"


class StrategyChangeKind(StrEnum):
    BOOTSTRAP = "bootstrap"
    UNCHANGED = "unchanged"
    STABLE_REFRESH = "stable_refresh"
    STATE_ADVANCE = "state_advance"
    RISK_GATE_APPLIED = "risk_gate_applied"
    RISK_GATE_RELEASED = "risk_gate_released"
    READINESS_CHANGED = "readiness_changed"
    INVALIDATED = "invalidated"
    REJECTED = "rejected"


class ConsistencyReasonCode(StrEnum):
    BOOTSTRAP_ACCEPTED = "BOOTSTRAP_ACCEPTED"
    EXACT_DECISION_MAINTAINED = "EXACT_DECISION_MAINTAINED"
    STABLE_STRATEGY_REFRESHED = "STABLE_STRATEGY_REFRESHED"
    CANONICAL_STATE_ADVANCED = "CANONICAL_STATE_ADVANCED"
    RISK_GATE_APPLIED = "RISK_GATE_APPLIED"
    RISK_GATE_RELEASED = "RISK_GATE_RELEASED"
    TYPED_SUPPORT_CHANGED = "TYPED_SUPPORT_CHANGED"
    FORMAL_INVALIDATION_CONFIRMED = "FORMAL_INVALIDATION_CONFIRMED"
    CURRENT_STATE_TRANSITION_MISMATCH = "CURRENT_STATE_TRANSITION_MISMATCH"
    CURRENT_STRATEGY_STATE_MISMATCH = "CURRENT_STRATEGY_STATE_MISMATCH"
    CURRENT_STRATEGY_TRANSITION_MISMATCH = "CURRENT_STRATEGY_TRANSITION_MISMATCH"
    CURRENT_POLICY_OUTPUT_MISMATCH = "CURRENT_POLICY_OUTPUT_MISMATCH"
    CURRENT_INPUT_INCONSISTENT = "CURRENT_INPUT_INCONSISTENT"
    IDENTITY_REVALIDATION_FAILED = "IDENTITY_REVALIDATION_FAILED"
    PREVIOUS_LINEAGE_MISSING = "PREVIOUS_LINEAGE_MISSING"
    PREVIOUS_POLICY_INPUT_MISMATCH = "PREVIOUS_POLICY_INPUT_MISMATCH"
    PREVIOUS_POLICY_OUTPUT_MISMATCH = "PREVIOUS_POLICY_OUTPUT_MISMATCH"
    PREVIOUS_STATE_TRANSITION_MISMATCH = "PREVIOUS_STATE_TRANSITION_MISMATCH"
    PREVIOUS_STRATEGY_STATE_MISMATCH = "PREVIOUS_STRATEGY_STATE_MISMATCH"
    PREVIOUS_STRATEGY_TRANSITION_MISMATCH = "PREVIOUS_STRATEGY_TRANSITION_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    TIME_ORDER_INVALID = "TIME_ORDER_INVALID"
    NON_IDEMPOTENT_REPLAY = "NON_IDEMPOTENT_REPLAY"
    STATE_DIRECTION_STRATEGY_CONFLICT = "STATE_DIRECTION_STRATEGY_CONFLICT"
    DIRECT_DIRECTION_FLIP = "DIRECT_DIRECTION_FLIP"
    UNSUPPORTED_READINESS_CHANGE = "UNSUPPORTED_READINESS_CHANGE"
    UNSUPPORTED_INVALIDATION = "UNSUPPORTED_INVALIDATION"
    UNSUPPORTED_STRATEGY_CHURN = "UNSUPPORTED_STRATEGY_CHURN"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisStrategyConsistencyInput(_FrozenContract):
    schema_version: Literal["analysis_strategy_consistency_input.v1"] = "analysis_strategy_consistency_input.v1"
    previous_policy_input: StrategyPolicyInput | None = None
    previous_state: AnalysisState | None = None
    previous_transition: StateTransitionPolicyDecision | None = None
    previous_strategy: StrategyDecision | None = None
    current_policy_input: StrategyPolicyInput
    candidate_strategy: StrategyDecision
    key_level_proof: tuple[KeyLevelLifecycleDecision, ...] = ()

    @model_validator(mode="after")
    def _validate_unique_proof(self) -> "AnalysisStrategyConsistencyInput":
        if len({item.decision_hash for item in self.key_level_proof}) != len(self.key_level_proof):
            raise ValueError("key_level_proof decisions must be unique")
        return self


class AnalysisStrategyConsistencyDecisionInput(_FrozenContract):
    schema_version: Literal["analysis_strategy_consistency_decision.v1"] = "analysis_strategy_consistency_decision.v1"
    previous_state_id: str | None = Field(default=None, pattern=r"^analysis_state\.v1:[0-9a-f]{64}$")
    previous_policy_input_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    previous_transition_decision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_state_id: str = Field(pattern=r"^analysis_state\.v1:[0-9a-f]{64}$")
    previous_strategy_id: str | None = Field(default=None, pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$")
    candidate_strategy_id: str = Field(pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$")
    transition_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ConsistencyStatus
    change_kind: StrategyChangeKind
    consistency_passed: bool
    selected_strategy_decision_id: str | None = Field(
        default=None,
        pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$",
    )
    reason_codes: tuple[ConsistencyReasonCode, ...] = Field(min_length=1)
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    policy_version: Literal["analysis_strategy_consistency_policy.v1"] = "analysis_strategy_consistency_policy.v1"

    @field_validator("reason_codes")
    @classmethod
    def _unique_reasons(cls, values: tuple[ConsistencyReasonCode, ...]) -> tuple[ConsistencyReasonCode, ...]:
        if len(set(values)) != len(values):
            raise ValueError("consistency reason codes must be unique")
        return values

    @model_validator(mode="after")
    def _validate_semantics(self) -> "AnalysisStrategyConsistencyDecisionInput":
        previous_presence = (
            self.previous_state_id is not None,
            self.previous_policy_input_hash is not None,
            self.previous_transition_decision_hash is not None,
            self.previous_strategy_id is not None,
        )
        if self.status is ConsistencyStatus.CONSISTENT and len(set(previous_presence)) != 1:
            raise ValueError("previous policy input, state, transition, and strategy identities must be paired")
        if self.status is ConsistencyStatus.CONSISTENT:
            has_predecessor = all(previous_presence)
            if (self.change_kind is StrategyChangeKind.BOOTSTRAP) == has_predecessor:
                raise ValueError("bootstrap requires no predecessor; every other consistent change requires one")
            if (
                not self.consistency_passed
                or self.selected_strategy_decision_id != self.candidate_strategy_id
                or self.change_kind is StrategyChangeKind.REJECTED
            ):
                raise ValueError("consistent result must select the candidate decision")
        elif (
            self.consistency_passed
            or self.selected_strategy_decision_id is not None
            or self.change_kind is not StrategyChangeKind.REJECTED
        ):
            raise ValueError("blocked or unverifiable result cannot select a strategy")
        if len({(ref.source, ref.reference, ref.retrieved_at) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("source_refs must be unique")
        return self


class AnalysisStrategyConsistencyDecision(AnalysisStrategyConsistencyDecisionInput):
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^analysis_strategy_consistency_decision\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "AnalysisStrategyConsistencyDecision":
        digest = _sha256(canonical_consistency_decision_json(self))
        if self.decision_hash != digest or self.decision_id != f"analysis_strategy_consistency_decision.v1:{digest}":
            raise ValueError("consistency decision identity does not match canonical payload")
        return self


def build_analysis_strategy_consistency_decision(
    payload: Mapping[str, Any] | AnalysisStrategyConsistencyDecisionInput,
) -> AnalysisStrategyConsistencyDecision:
    value = (
        payload
        if isinstance(payload, AnalysisStrategyConsistencyDecisionInput)
        else AnalysisStrategyConsistencyDecisionInput.model_validate(payload)
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
    digest = _sha256(canonical_consistency_decision_json(normalized))
    return AnalysisStrategyConsistencyDecision(
        **normalized.model_dump(),
        decision_hash=digest,
        decision_id=f"analysis_strategy_consistency_decision.v1:{digest}",
    )


def canonical_consistency_decision_json(
    value: AnalysisStrategyConsistencyDecisionInput | AnalysisStrategyConsistencyDecision,
) -> str:
    payload = value.model_dump(mode="json", exclude={"decision_hash", "decision_id"})
    payload["source_refs"] = [
        ref.model_dump(mode="json")
        for ref in sorted(
            value.source_refs,
            key=lambda ref: (ref.source, ref.reference, ref.retrieved_at),
        )
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
