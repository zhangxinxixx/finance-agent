"""Stable contracts for persistent analysis state and state transitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


ANALYSIS_STATE_SCHEMA_VERSION = "1.0"
AnalysisStateSchemaVersion = Literal["1.0"]
QualityGateActionValue = Literal["pass", "retry", "fallback", "manual_review", "block_publish"]
AcceptedOutputSource = Literal["primary", "corrective_fallback", "none"]


class TransitionAction(StrEnum):
    """The only state-change operations accepted by the transition contract."""

    STRENGTHEN = "strengthen"
    MAINTAIN = "maintain"
    WEAKEN = "weaken"
    INVALIDATE = "invalidate"
    PENDING = "pending"


class AnalysisStateDocument(BaseModel):
    """Provider-independent snapshot of the currently asserted analysis state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: AnalysisStateSchemaVersion = ANALYSIS_STATE_SCHEMA_VERSION
    asset: str = Field(min_length=1, max_length=32)
    as_of: AwareDatetime
    market_stage: str = Field(min_length=1, max_length=64)
    core_thesis: str = Field(min_length=1)
    net_bias: str = Field(min_length=1, max_length=32)
    dominant_drivers: list[dict[str, Any]] = Field(default_factory=list)
    key_levels: list[dict[str, Any]] = Field(default_factory=list)
    scenario_states: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_items: list[dict[str, Any]] = Field(default_factory=list)
    invalidation_conditions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_cursors: dict[str, Any] = Field(default_factory=dict)
    input_snapshot_ids: dict[str, str] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("asset", "market_stage", "core_thesis", "net_bias")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class StateChange(BaseModel):
    """One reviewable change from the previous state to the next state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str = Field(min_length=1, max_length=128)
    action: TransitionAction
    reason: str = Field(min_length=1)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("target", "reason")
    @classmethod
    def strip_change_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class AnalysisTransitionDocument(BaseModel):
    """Append-only explanation of how one analysis state follows another."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: AnalysisStateSchemaVersion = ANALYSIS_STATE_SCHEMA_VERSION
    summary: str = Field(min_length=1)
    changes: list[StateChange] = Field(min_length=1)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class StateMaterializationAuthority(BaseModel):
    """Quality-gate and AgentLoop authority attached to one immutable state.

    ``PASS`` by itself is insufficient. A canonical candidate must also be the
    authoritative ``accepted_output`` selected by AgentLoop.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality_gate_action: QualityGateActionValue
    publish_allowed: bool
    accepted_output_source: AcceptedOutputSource = "none"
    accepted_output_agent_name: str | None = None
    accepted_output_snapshot_id: str | None = None

    @field_validator("accepted_output_agent_name", "accepted_output_snapshot_id")
    @classmethod
    def strip_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("accepted_output identity must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_acceptance_authority(self) -> "StateMaterializationAuthority":
        accepted = self.accepted_output_source != "none"
        canonical_allowed = self.quality_gate_action == "pass" and accepted
        if self.publish_allowed != canonical_allowed:
            raise ValueError(
                "publish_allowed requires quality_gate_action='pass' and an authoritative accepted_output"
            )
        if accepted and (not self.accepted_output_agent_name or not self.accepted_output_snapshot_id):
            raise ValueError("accepted_output requires agent_name and snapshot_id")
        if not accepted and (
            self.accepted_output_agent_name is not None or self.accepted_output_snapshot_id is not None
        ):
            raise ValueError("accepted_output source='none' cannot carry identity")
        return self
