"""Pure assembly of formal XAUUSD key-level lifecycle controls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from apps.analysis.gold_policy.key_level_policy import evaluate_key_level_lifecycle
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelEvent,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
)
from apps.analysis.gold_policy.state_schemas import EvidenceScope


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KeyLevelControlsInput(_FrozenContract):
    """Caller-owned, typed lifecycle inputs for one decision scope and time."""

    schema_version: Literal["key_level_controls_input.v1"] = "key_level_controls_input.v1"
    decision_as_of: datetime
    scope: EvidenceScope
    previous_states: tuple[KeyLevelReadModel, ...] = ()
    ordered_events: tuple[KeyLevelEvent, ...] = ()

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_decision_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("key-level controls decision_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_lifecycle_inputs(self) -> "KeyLevelControlsInput":
        state_level_ids = [state.spec.level_id for state in self.previous_states]
        if len(set(state_level_ids)) != len(state_level_ids):
            raise ValueError("previous key-level states must not contain duplicate levels")
        for state in self.previous_states:
            if state.spec.scope is not self.scope:
                raise ValueError("previous key-level state scope must match controls scope")
            if state.as_of > self.decision_as_of:
                raise ValueError("previous key-level state cannot be after controls decision_as_of")

        previous_key: tuple[datetime, str] | None = None
        for event in self.ordered_events:
            if event.spec.scope is not self.scope or event.evidence.scope is not self.scope:
                raise ValueError("key-level event scope must match controls scope")
            if event.evidence.as_of > self.decision_as_of:
                raise ValueError("key-level event evidence cannot be after controls decision_as_of")
            event_key = (event.evidence.as_of, event.event_id)
            if previous_key is not None and event_key < previous_key:
                raise ValueError("key-level events must be ordered by evidence time and event identity")
            previous_key = event_key
        return self


class KeyLevelControls(_FrozenContract):
    """Stable, proof-carrying controls consumed by the daily-close boundary."""

    schema_version: Literal["key_level_controls.v1"] = "key_level_controls.v1"
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    key_level_proof: tuple[KeyLevelLifecycleDecision, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_proof(self) -> "KeyLevelControls":
        if self.key_level_proof != self.key_level_decisions:
            raise ValueError("key-level proof must exactly match lifecycle decisions")
        level_ids = [state.spec.level_id for state in self.key_levels]
        if len(set(level_ids)) != len(level_ids):
            raise ValueError("key-level controls must not contain duplicate levels")
        if tuple(sorted(level_ids)) != tuple(level_ids):
            raise ValueError("key-level controls levels must use stable identity order")
        return self


class KeyLevelControlsBuilder:
    """Evaluate supplied typed events; never derives a level from prose or scores."""

    def build(self, lifecycle_input: KeyLevelControlsInput) -> KeyLevelControls:
        states = {state.spec.level_id: state for state in lifecycle_input.previous_states}
        decisions: list[KeyLevelLifecycleDecision] = []

        for event in lifecycle_input.ordered_events:
            result = evaluate_key_level_lifecycle(states.get(event.spec.level_id), event)
            decisions.append(result.decision)
            if result.state is None:
                states.pop(event.spec.level_id, None)
            else:
                states[event.spec.level_id] = result.state

        key_levels = tuple(sorted(states.values(), key=lambda state: state.spec.level_id))
        proof = tuple(decisions)
        reason_codes = _stable_reason_codes(proof, has_input=bool(states or lifecycle_input.ordered_events))
        return KeyLevelControls(
            key_levels=key_levels,
            key_level_decisions=proof,
            key_level_proof=proof,
            reason_codes=reason_codes,
        )


def _stable_reason_codes(
    decisions: tuple[KeyLevelLifecycleDecision, ...],
    *,
    has_input: bool,
) -> tuple[str, ...]:
    if not has_input:
        return ("NO_KEY_LEVEL_INPUT",)
    return tuple(dict.fromkeys(reason for decision in decisions for reason in decision.reasons))
