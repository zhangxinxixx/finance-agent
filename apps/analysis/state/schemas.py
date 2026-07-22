"""Stable contracts for persistent analysis state and state transitions."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


ANALYSIS_STATE_V1_SCHEMA_VERSION = "1.0"
ANALYSIS_STATE_SCHEMA_VERSION = "1.1"
ANALYSIS_STATE_MACHINE_VERSION = "analysis_state.v1.1"
AnalysisStateSchemaVersion = Literal["1.0", "1.1"]
StateScope = Literal["intraday", "daily_close", "weekly_fundamental"]
QualityGateActionValue = Literal["pass", "retry", "fallback", "manual_review", "block_publish"]
AcceptedOutputSource = Literal["primary", "corrective_fallback", "none"]


class TransitionAction(StrEnum):
    """The only state-change operations accepted by the transition contract."""

    STRENGTHEN = "strengthen"
    MAINTAIN = "maintain"
    WEAKEN = "weaken"
    INVALIDATE = "invalidate"
    PENDING = "pending"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DominantDriver(_StrictFrozenModel):
    """One ranked driver using the existing direction vocabulary."""

    driver_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    rank: int | None = Field(default=None, ge=1)
    score: float | None = None
    direction: Literal["tailwind", "headwind", "neutral", "mixed", "unknown"]
    coverage_status: Literal["covered", "partial", "missing", "unknown"] = "unknown"


class KeyLevel(_StrictFrozenModel):
    """One explicit level without inventing a second level taxonomy."""

    value: float | str
    role: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128)
    meaning: str | None = Field(default=None, min_length=1, max_length=500)


class ScenarioState(_StrictFrozenModel):
    """One existing scenario/condition and its current status."""

    scenario_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=500)
    status: Literal["active", "pending", "confirmed", "invalidated"]


class AnalysisStateDocumentV1(_StrictFrozenModel):
    """Frozen legacy payload. Parsing it must never add v1.1 fields."""

    schema_version: Literal["1.0"] = ANALYSIS_STATE_V1_SCHEMA_VERSION
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


class AnalysisStateDocumentV11(_StrictFrozenModel):
    """Scoped provider-independent state written by the v1.1 core."""

    schema_version: Literal["1.1"] = ANALYSIS_STATE_SCHEMA_VERSION
    state_scope: StateScope
    state_machine_version: str = Field(min_length=1, max_length=64)
    session: str = Field(min_length=1, max_length=64)
    trade_date: date
    asset: str = Field(min_length=1, max_length=32)
    as_of: AwareDatetime
    market_stage: str = Field(min_length=1, max_length=64)
    core_thesis: str = Field(min_length=1)
    net_bias: str = Field(min_length=1, max_length=32)
    dominant_drivers: list[DominantDriver] = Field(default_factory=list)
    key_levels: list[KeyLevel] = Field(default_factory=list)
    scenario_states: list[ScenarioState] = Field(default_factory=list)
    unresolved_items: list[dict[str, Any]] = Field(default_factory=list)
    invalidation_conditions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_cursors: dict[str, Any] = Field(default_factory=dict)
    input_snapshot_ids: dict[str, str] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator(
        "state_machine_version", "session", "asset", "market_stage", "core_thesis", "net_bias"
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

# The old name remains a compatibility constructor. New scoped code names V11 explicitly.
AnalysisStateDocument = AnalysisStateDocumentV1
VersionedAnalysisStateDocument = Annotated[
    AnalysisStateDocumentV1 | AnalysisStateDocumentV11,
    Field(discriminator="schema_version"),
]
_STATE_DOCUMENT_ADAPTER = TypeAdapter(VersionedAnalysisStateDocument)


class StateChange(_StrictFrozenModel):
    """One reviewable change from the previous state to the next state."""

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


class AnalysisTransitionDocumentV1(_StrictFrozenModel):
    schema_version: Literal["1.0"] = ANALYSIS_STATE_V1_SCHEMA_VERSION
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


class AnalysisTransitionDocumentV11(_StrictFrozenModel):
    schema_version: Literal["1.1"] = ANALYSIS_STATE_SCHEMA_VERSION
    state_scope: StateScope
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


AnalysisTransitionDocument = AnalysisTransitionDocumentV1
VersionedAnalysisTransitionDocument = Annotated[
    AnalysisTransitionDocumentV1 | AnalysisTransitionDocumentV11,
    Field(discriminator="schema_version"),
]
_TRANSITION_DOCUMENT_ADAPTER = TypeAdapter(VersionedAnalysisTransitionDocument)


def parse_analysis_state_document(value: Any) -> VersionedAnalysisStateDocument:
    """Parse by declared version without upgrading or reserializing v1 payloads."""

    return _STATE_DOCUMENT_ADAPTER.validate_python(value)


def parse_analysis_transition_document(value: Any) -> VersionedAnalysisTransitionDocument:
    """Parse a transition without rewriting its declared contract version."""

    return _TRANSITION_DOCUMENT_ADAPTER.validate_python(value)


class StateMaterializationAuthority(_StrictFrozenModel):
    """Quality-gate and AgentLoop authority attached to one immutable state."""

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
