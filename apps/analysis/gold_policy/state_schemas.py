"""Immutable, content-addressed contracts for the Gold analysis state machine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.schemas import SourceReference


class AnalysisStage(StrEnum):
    PRESSURE = "pressure"
    RANGE = "range"
    DIRECTION_DECISION = "direction_decision"
    WEAK_REPAIR = "weak_repair"
    REVERSAL_WATCH = "reversal_watch"
    TREND_CONFIRMED = "trend_confirmed"


class TransitionAction(StrEnum):
    STRENGTHEN = "strengthen"
    MAINTAIN = "maintain"
    WEAKEN = "weaken"
    INVALIDATE = "invalidate"
    PENDING = "pending"


class EvidenceScope(StrEnum):
    INTRADAY = "intraday"
    DAILY_CLOSE = "daily_close"
    WEEKLY_FUNDAMENTAL = "weekly_fundamental"


class EvidenceDeltaKind(StrEnum):
    NO_OP = "no_op"
    ORDINARY = "ordinary"
    HARD_INVALIDATION = "hard_invalidation"
    MAJOR_CONFIRMATION = "major_confirmation"


class EvidenceCategory(StrEnum):
    MACRO = "macro"
    PRICE = "price"
    STRUCTURE = "structure"
    OFFICIAL_EVENT = "official_event"


class PendingRule(StrEnum):
    OPPOSITE_BIAS = "opposite_bias"
    NEW_BIAS = "new_bias"
    TREND_ENTRY = "trend_entry"
    TREND_EXIT = "trend_exit"
    CONFLICT = "conflict"


class HardInvalidationRule(StrEnum):
    CONFIRMED_SUPPORT_BREAK = "CONFIRMED_SUPPORT_BREAK"
    CONFIRMED_RESISTANCE_BREAK = "CONFIRMED_RESISTANCE_BREAK"
    MAJOR_MACRO_STATE_INVALIDATED = "MAJOR_MACRO_STATE_INVALIDATED"


class MajorConfirmationRule(StrEnum):
    OFFICIAL_EVENT_REACTION_CONFIRMED = "OFFICIAL_EVENT_REACTION_CONFIRMED"
    MAJOR_MACRO_REACTION_CONFIRMED = "MAJOR_MACRO_REACTION_CONFIRMED"
    PRICE_STRUCTURE_MACRO_CONFIRMED = "PRICE_STRUCTURE_MACRO_CONFIRMED"


DirectionalBias = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
PendingDirection = Literal["bullish", "bearish", "neutral", "mixed"]
StateQuality = Literal["accepted", "observe", "blocked"]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TransitionEvidence(_FrozenContract):
    """A typed, source-backed delta consumed by the transition policy."""

    evidence_id: str = Field(min_length=1)
    scope: EvidenceScope
    delta_kind: EvidenceDeltaKind
    as_of: datetime
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    evidence_categories: tuple[EvidenceCategory, ...] = ()
    predecessor_evidence_id: str | None = Field(default=None, min_length=1)
    rule_code: HardInvalidationRule | MajorConfirmationRule | None = None

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="evidence as_of")

    @model_validator(mode="after")
    def _validate_lineage(self) -> "TransitionEvidence":
        _require_source_refs(self.source_refs, as_of=self.as_of)
        if len(set(self.evidence_categories)) != len(self.evidence_categories):
            raise ValueError("evidence_categories must be unique")
        if self.delta_kind is EvidenceDeltaKind.NO_OP:
            if (
                self.evidence_categories
                or self.rule_code is not None
                or self.predecessor_evidence_id is not None
            ):
                raise ValueError("no_op evidence cannot claim material categories or a rule")
            return self
        if not self.evidence_categories:
            raise ValueError("material evidence requires at least one evidence category")
        if self.delta_kind is EvidenceDeltaKind.ORDINARY and self.rule_code is not None:
            raise ValueError("ordinary evidence cannot claim a hard or major rule")
        if self.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION and not isinstance(
            self.rule_code, HardInvalidationRule
        ):
            raise ValueError("hard_invalidation requires a whitelisted hard rule")
        if self.delta_kind is EvidenceDeltaKind.MAJOR_CONFIRMATION and not isinstance(
            self.rule_code, MajorConfirmationRule
        ):
            raise ValueError("major_confirmation requires a whitelisted major rule")
        if self.delta_kind is EvidenceDeltaKind.MAJOR_CONFIRMATION:
            categories = set(self.evidence_categories)
            if EvidenceCategory.PRICE not in categories or not categories.intersection(
                {
                    EvidenceCategory.MACRO,
                    EvidenceCategory.STRUCTURE,
                    EvidenceCategory.OFFICIAL_EVENT,
                }
            ):
                raise ValueError(
                    "major_confirmation requires price plus macro, structure, or official_event"
                )
            if self.rule_code is MajorConfirmationRule.OFFICIAL_EVENT_REACTION_CONFIRMED and not {
                EvidenceCategory.PRICE,
                EvidenceCategory.OFFICIAL_EVENT,
            }.issubset(categories):
                raise ValueError("official event confirmation requires price and official_event")
            if (
                self.rule_code is MajorConfirmationRule.OFFICIAL_EVENT_REACTION_CONFIRMED
                and self.scope is EvidenceScope.WEEKLY_FUNDAMENTAL
            ):
                raise ValueError("official event reaction cannot directly update a weekly head")
            if self.rule_code is MajorConfirmationRule.MAJOR_MACRO_REACTION_CONFIRMED and not {
                EvidenceCategory.PRICE,
                EvidenceCategory.MACRO,
            }.issubset(categories):
                raise ValueError("major macro confirmation requires price and macro")
            if (
                self.rule_code is MajorConfirmationRule.MAJOR_MACRO_REACTION_CONFIRMED
                and self.scope is EvidenceScope.INTRADAY
            ):
                raise ValueError("major macro reaction cannot be classified at intraday scope")
            if self.rule_code is MajorConfirmationRule.PRICE_STRUCTURE_MACRO_CONFIRMED and not {
                EvidenceCategory.PRICE,
                EvidenceCategory.STRUCTURE,
                EvidenceCategory.MACRO,
            }.issubset(categories):
                raise ValueError("price structure confirmation requires price, structure, and macro")
        if self.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION:
            categories = set(self.evidence_categories)
            if self.rule_code in {
                HardInvalidationRule.CONFIRMED_SUPPORT_BREAK,
                HardInvalidationRule.CONFIRMED_RESISTANCE_BREAK,
            } and EvidenceCategory.PRICE not in categories:
                raise ValueError("price-level invalidation requires price evidence")
            if (
                self.rule_code is HardInvalidationRule.MAJOR_MACRO_STATE_INVALIDATED
                and EvidenceCategory.MACRO not in categories
            ):
                raise ValueError("macro invalidation requires macro evidence")
            if (
                self.rule_code is HardInvalidationRule.MAJOR_MACRO_STATE_INVALIDATED
                and self.scope is EvidenceScope.INTRADAY
            ):
                raise ValueError("macro state invalidation cannot be classified at intraday scope")
        return self


class PendingTransition(_FrozenContract):
    """Typed hysteresis memory stored in an advancing pending state."""

    rule: PendingRule
    direction: PendingDirection
    count: int = Field(ge=1)
    first_seen_at: datetime
    last_seen_at: datetime
    last_evidence_id: str = Field(min_length=1)
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="pending transition timestamp")

    @model_validator(mode="after")
    def _validate_pending(self) -> "PendingTransition":
        if self.first_seen_at > self.last_seen_at:
            raise ValueError("pending first_seen_at cannot be after last_seen_at")
        _require_source_refs(self.source_refs, as_of=self.last_seen_at)
        return self


class AnalysisStateInput(_FrozenContract):
    """Caller-owned state payload before deterministic identity is attached."""

    schema_version: Literal["analysis_state.v1"] = "analysis_state.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    stage: AnalysisStage
    directional_bias: DirectionalBias
    pending_transition: PendingTransition | None = None
    scope: EvidenceScope
    as_of: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    quality_status: StateQuality
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="state as_of")

    @model_validator(mode="after")
    def _validate_state_semantics(self) -> "AnalysisStateInput":
        _require_source_refs(self.source_refs, as_of=self.as_of)
        if (
            self.pending_transition is not None
            and self.pending_transition.last_seen_at > self.as_of
        ):
            raise ValueError("pending transition cannot be after state as_of")
        if self.quality_status == "blocked" and (
            self.directional_bias != "unavailable"
            or self.pending_transition is not None
            or self.confidence != 0.0
        ):
            raise ValueError(
                "blocked state must be unavailable with zero confidence and no pending transition"
            )
        if self.quality_status == "accepted" and self.directional_bias == "unavailable":
            raise ValueError("accepted state cannot have unavailable directional_bias")
        if self.stage is AnalysisStage.TREND_CONFIRMED and self.directional_bias not in {
            "bullish",
            "bearish",
        }:
            raise ValueError("trend_confirmed state requires a directional bias")
        self._validate_pending_semantics()
        return self

    def _validate_pending_semantics(self) -> None:
        pending = self.pending_transition
        if pending is None:
            return
        if not all(ref in self.source_refs for ref in pending.source_refs):
            raise ValueError("pending source_refs must be present in state source_refs")
        if pending.rule is PendingRule.TREND_ENTRY and (
            self.stage is not AnalysisStage.REVERSAL_WATCH
            or self.directional_bias not in {"bullish", "bearish"}
            or pending.direction != self.directional_bias
        ):
            raise ValueError("trend_entry pending requires reversal_watch in the same direction")
        if pending.rule is PendingRule.TREND_EXIT and (
            self.stage is not AnalysisStage.TREND_CONFIRMED
            or self.directional_bias not in {"bullish", "bearish"}
            or pending.direction == self.directional_bias
        ):
            raise ValueError("trend_exit pending requires counter evidence against a trend")
        if pending.rule is PendingRule.OPPOSITE_BIAS and (
            self.stage is AnalysisStage.TREND_CONFIRMED
            or self.directional_bias not in {"bullish", "bearish"}
            or pending.direction not in {"bullish", "bearish"}
            or pending.direction == self.directional_bias
        ):
            raise ValueError("opposite_bias pending requires the opposite directional bias")
        if pending.rule is PendingRule.NEW_BIAS and (
            self.directional_bias != "mixed"
            or pending.direction not in {"bullish", "bearish"}
        ):
            raise ValueError("new_bias pending requires a mixed canonical bias")
        if pending.rule is PendingRule.CONFLICT and pending.direction != "mixed":
            raise ValueError("conflict pending direction must be mixed")


class AnalysisState(AnalysisStateInput):
    """Canonical ``analysis_state.v1`` identified by its complete payload."""

    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_id: str = Field(pattern=r"^analysis_state\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_content_identity(self) -> "AnalysisState":
        digest = _sha256(canonical_analysis_state_json(self))
        if self.payload_hash != digest or self.state_id != f"analysis_state.v1:{digest}":
            raise ValueError("analysis state identity does not match its canonical payload")
        return self


class StateTransitionPolicyDecisionInput(_FrozenContract):
    """Caller-owned transition-decision payload before hashing."""

    from_state_id: str | None = Field(
        default=None, pattern=r"^analysis_state\.v1:[0-9a-f]{64}$"
    )
    to_state_id: str | None = Field(
        default=None, pattern=r"^analysis_state\.v1:[0-9a-f]{64}$"
    )
    from_stage: AnalysisStage | None = None
    to_stage: AnalysisStage | None = None
    action: TransitionAction
    transition_allowed: bool
    advance: bool
    stage_changed: bool
    evidence: TransitionEvidence
    reasons: tuple[str, ...] = Field(min_length=1)
    policy_version: Literal["analysis_state_transition_policy.v1"] = (
        "analysis_state_transition_policy.v1"
    )

    @field_validator("reasons")
    @classmethod
    def _validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("transition reasons must be non-empty")
        if len(set(values)) != len(values):
            raise ValueError("transition reasons must be unique")
        return values

    @model_validator(mode="after")
    def _validate_transition_semantics(self) -> "StateTransitionPolicyDecisionInput":
        if (self.from_state_id is None) != (self.from_stage is None):
            raise ValueError("from state id and stage must both be present or absent")
        if (self.to_state_id is None) != (self.to_stage is None):
            raise ValueError("to state id and stage must both be present or absent")
        same_state = self.from_state_id == self.to_state_id
        if self.advance == same_state:
            raise ValueError("advance must be true exactly when to_state_id differs from from_state_id")
        if self.advance and (not self.transition_allowed or self.to_state_id is None):
            raise ValueError("an advancing decision must be allowed and have a target state")
        if not self.transition_allowed and self.advance:
            raise ValueError("a disallowed transition cannot advance")
        if not self.advance and self.from_stage != self.to_stage:
            raise ValueError("a non-advancing decision cannot change stage")
        if self.stage_changed != (self.from_stage != self.to_stage):
            raise ValueError("stage_changed must match the stage fields")
        if (
            self.action is TransitionAction.PENDING
            and self.from_stage is not None
            and self.stage_changed
        ):
            raise ValueError("pending decisions cannot change an existing stage")
        if self.action is TransitionAction.MAINTAIN and self.from_stage is not None and self.advance:
            raise ValueError("maintain cannot advance an existing state")
        if self.evidence.delta_kind is EvidenceDeltaKind.NO_OP and (
            self.action is not TransitionAction.MAINTAIN or self.advance
        ):
            raise ValueError("no_op evidence requires a non-advancing maintain decision")
        if (
            self.evidence.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION
            and self.transition_allowed
            and self.action is not TransitionAction.INVALIDATE
        ):
            raise ValueError("allowed hard_invalidation evidence requires invalidate action")
        return self


class StateTransitionPolicyDecision(StateTransitionPolicyDecisionInput):
    """Content-addressed output contract for the future transition policy."""

    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_decision_identity(self) -> "StateTransitionPolicyDecision":
        digest = _sha256(canonical_state_transition_decision_json(self))
        if self.decision_hash != digest:
            raise ValueError("transition decision hash does not match its canonical payload")
        return self


def canonical_analysis_state_json(state: AnalysisStateInput | AnalysisState) -> str:
    """Return canonical JSON excluding generated state identity fields."""

    payload = state.model_dump(mode="json", exclude={"payload_hash", "state_id"})
    payload["source_refs"] = _canonical_source_refs(state.source_refs)
    if state.pending_transition is not None:
        payload["pending_transition"]["source_refs"] = _canonical_source_refs(
            state.pending_transition.source_refs
        )
    return _canonical_json(payload)


def build_analysis_state(payload: Mapping[str, Any] | AnalysisStateInput | AnalysisState) -> AnalysisState:
    """Build a deterministic state without I/O, clocks, or input mutation."""

    if isinstance(payload, AnalysisState):
        return payload
    input_state = (
        payload
        if isinstance(payload, AnalysisStateInput)
        else AnalysisStateInput.model_validate(payload)
    )
    pending = input_state.pending_transition
    if pending is not None:
        pending = pending.model_copy(
            update={"source_refs": _normalized_source_refs(pending.source_refs)}
        )
    normalized = input_state.model_copy(
        update={
            "source_refs": _normalized_source_refs(input_state.source_refs),
            "pending_transition": pending,
        }
    )
    canonical = canonical_analysis_state_json(normalized)
    digest = _sha256(canonical)
    return AnalysisState(
        **normalized.model_dump(),
        payload_hash=digest,
        state_id=f"analysis_state.v1:{digest}",
    )


def canonical_state_transition_decision_json(
    decision: StateTransitionPolicyDecisionInput | StateTransitionPolicyDecision,
) -> str:
    """Return canonical JSON excluding the generated transition hash."""

    payload = decision.model_dump(mode="json", exclude={"decision_hash"})
    payload["evidence"]["source_refs"] = _canonical_source_refs(
        decision.evidence.source_refs
    )
    payload["evidence"]["evidence_categories"] = sorted(
        category.value for category in decision.evidence.evidence_categories
    )
    return _canonical_json(payload)


def build_state_transition_policy_decision(
    payload: Mapping[str, Any]
    | StateTransitionPolicyDecisionInput
    | StateTransitionPolicyDecision,
) -> StateTransitionPolicyDecision:
    """Build a deterministic transition decision without implementing policy."""

    if isinstance(payload, StateTransitionPolicyDecision):
        return payload
    input_decision = (
        payload
        if isinstance(payload, StateTransitionPolicyDecisionInput)
        else StateTransitionPolicyDecisionInput.model_validate(payload)
    )
    normalized_evidence = input_decision.evidence.model_copy(
        update={
            "source_refs": _normalized_source_refs(
                input_decision.evidence.source_refs
            ),
            "evidence_categories": tuple(
                sorted(
                    input_decision.evidence.evidence_categories,
                    key=lambda category: category.value,
                )
            ),
        }
    )
    normalized = input_decision.model_copy(update={"evidence": normalized_evidence})
    digest = _sha256(canonical_state_transition_decision_json(normalized))
    return StateTransitionPolicyDecision(
        **normalized.model_dump(),
        decision_hash=digest,
    )


def _require_source_refs(
    source_refs: tuple[SourceReference, ...], *, as_of: datetime
) -> None:
    identities: set[tuple[str, str, datetime]] = set()
    for source_ref in source_refs:
        retrieved_at = _aware_utc(
            source_ref.retrieved_at,
            field_name="source reference retrieved_at",
        )
        if retrieved_at > as_of:
            raise ValueError("source reference retrieved_at cannot be after as_of")
        identity = (source_ref.source, source_ref.reference, retrieved_at)
        if identity in identities:
            raise ValueError("source_refs must be unique")
        identities.add(identity)


def _normalized_source_refs(
    source_refs: tuple[SourceReference, ...],
) -> tuple[SourceReference, ...]:
    return tuple(
        SourceReference(
            source=source_ref.source,
            reference=source_ref.reference,
            retrieved_at=source_ref.retrieved_at.astimezone(UTC),
        )
        for source_ref in sorted(
            source_refs,
            key=lambda ref: (
                ref.source,
                ref.reference,
                ref.retrieved_at.astimezone(UTC),
            ),
        )
    )


def _canonical_source_refs(
    source_refs: tuple[SourceReference, ...],
) -> list[dict[str, Any]]:
    return [
        source_ref.model_dump(mode="json")
        for source_ref in _normalized_source_refs(source_refs)
    ]


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
