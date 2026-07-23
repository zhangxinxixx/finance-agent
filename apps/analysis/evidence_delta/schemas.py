"""Strict, provider-independent contracts for deterministic evidence deltas."""

from __future__ import annotations

from collections import Counter
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

from apps.analysis.state.hashing import content_hash
from apps.analysis.state.schemas import StateScope


EVIDENCE_DELTA_SCHEMA_VERSION = "evidence_delta.v1"
EVIDENCE_DELTA_RULESET_VERSION = "evidence_delta.rules.v1"
SHA256_LENGTH = 64


class Materiality(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendedAction(StrEnum):
    NO_OP = "no_op"
    UPDATE_CONTEXT_ONLY = "update_context_only"
    RUN_TRANSITION_ANALYSIS = "run_transition_analysis"
    MANUAL_REVIEW = "manual_review"


class EvaluationOutcome(StrEnum):
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    CONTEXT_UPDATE = "context_update"
    TRANSITION_TRIGGER = "transition_trigger"
    MANUAL_REVIEW = "manual_review"


_MATERIALITY_RANK = {
    Materiality.NONE: 0,
    Materiality.LOW: 1,
    Materiality.MEDIUM: 2,
    Materiality.HIGH: 3,
    Materiality.CRITICAL: 4,
}
_ACTION_RANK = {
    RecommendedAction.NO_OP: 0,
    RecommendedAction.UPDATE_CONTEXT_ONLY: 1,
    RecommendedAction.RUN_TRANSITION_ANALYSIS: 2,
    RecommendedAction.MANUAL_REVIEW: 3,
}


class SourceQuality(StrEnum):
    OFFICIAL = "official"
    EXCHANGE = "exchange"
    PRIMARY = "primary"
    VALIDATED = "validated"
    SUPPLEMENTAL = "supplemental"
    UNVERIFIED = "unverified"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    CONFLICTING = "conflicting"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class _EvidenceBase(_StrictFrozenModel):
    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)
    asset: str = Field(min_length=1, max_length=32)
    observed_at: AwareDatetime
    source_quality: SourceQuality
    source_ref: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "evidence_id", "asset")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        return _required_text(value)


MacroMetric = Literal["dxy", "us02y", "us10y", "real10y", "breakeven10y", "oil"]
AffectedStateField = Literal[
    "dominant_drivers",
    "key_levels",
    "scenario_states",
    "unresolved_items",
    "invalidation_conditions",
]


class MacroMetricEvidence(_EvidenceBase):
    evidence_type: Literal["macro_metric"] = "macro_metric"
    metric: MacroMetric
    current_value: float
    previous_value: float
    unit: Literal["index", "percent", "usd"]

    @model_validator(mode="after")
    def validate_metric_unit(self) -> "MacroMetricEvidence":
        expected = {
            "dxy": "index",
            "us02y": "percent",
            "us10y": "percent",
            "real10y": "percent",
            "breakeven10y": "percent",
            "oil": "usd",
        }[self.metric]
        if self.unit != expected:
            raise ValueError(f"{self.metric} requires unit={expected}")
        return self


class KeyLevelEvidence(_EvidenceBase):
    evidence_type: Literal["key_level_event"] = "key_level_event"
    level_id: str = Field(min_length=1, max_length=128)
    level_role: Literal["support", "resistance", "invalidation", "gamma_zero", "option_wall"]
    level_value: float
    observed_value: float
    event: Literal["approach", "touch", "confirmed_break", "confirmed_reclaim"]
    confirmation_status: ConfirmationStatus

    @field_validator("level_id")
    @classmethod
    def strip_level_id(cls, value: str) -> str:
        return _required_text(value)


class OptionsRegimeEvidence(_EvidenceBase):
    evidence_type: Literal["options_regime"] = "options_regime"
    regime_id: str = Field(min_length=1, max_length=128)
    event: Literal["gamma_zero_migration", "wall_migration", "gamma_sign_flip"]
    previous_value: float | None = None
    current_value: float | None = None
    change_pct: float | None = None
    confirmation_status: ConfirmationStatus

    @field_validator("regime_id")
    @classmethod
    def strip_regime_id(cls, value: str) -> str:
        return _required_text(value)

    @model_validator(mode="after")
    def validate_measurement(self) -> "OptionsRegimeEvidence":
        if self.event == "gamma_sign_flip":
            if self.previous_value is None or self.current_value is None:
                raise ValueError("gamma_sign_flip requires previous_value and current_value")
            if self.previous_value == 0 or self.current_value == 0:
                raise ValueError("gamma_sign_flip values must be non-zero")
        elif self.change_pct is None:
            raise ValueError(f"{self.event} requires change_pct")
        return self


class MaterialEventEvidence(_EvidenceBase):
    evidence_type: Literal["material_event"] = "material_event"
    event_id: str = Field(min_length=1, max_length=255)
    cluster_key: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    claim: str = Field(min_length=1, max_length=2000)
    materiality_score: float = Field(ge=0.0, le=100.0)
    risk_level: Literal["low", "medium", "high", "critical"]
    recompute_eligible: bool
    confirmation_status: ConfirmationStatus

    @field_validator("event_id", "cluster_key", "event_type", "claim")
    @classmethod
    def strip_event_text(cls, value: str) -> str:
        return _required_text(value)


class FigureFactEvidence(_EvidenceBase):
    evidence_type: Literal["figure_fact"] = "figure_fact"
    figure_fact_id: str = Field(min_length=1, max_length=255)
    figure_id: str = Field(min_length=1, max_length=255)
    report_id: str = Field(min_length=1, max_length=255)
    figure_content_hash: str
    quality_status: Literal["accepted", "needs_review", "blocked"]
    has_direct_evidence: bool

    @field_validator("figure_fact_id", "figure_id", "report_id")
    @classmethod
    def strip_figure_identity(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("figure_content_hash")
    @classmethod
    def validate_figure_hash(cls, value: str) -> str:
        return _sha256(value, "figure_content_hash")

    @model_validator(mode="after")
    def validate_acceptance(self) -> "FigureFactEvidence":
        if self.quality_status == "accepted" and not self.has_direct_evidence:
            raise ValueError("accepted FigureFact requires has_direct_evidence=true")
        if self.quality_status == "accepted" and self.source_quality is not SourceQuality.VALIDATED:
            raise ValueError("accepted FigureFact requires validated source quality")
        return self


DeltaEvidence = Annotated[
    MacroMetricEvidence
    | KeyLevelEvidence
    | OptionsRegimeEvidence
    | MaterialEventEvidence
    | FigureFactEvidence,
    Field(discriminator="evidence_type"),
]
DELTA_EVIDENCE_ADAPTER = TypeAdapter(DeltaEvidence)


class EvidenceIdentity(_StrictFrozenModel):
    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)

    @field_validator("source", "evidence_id")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        return _required_text(value)


class EvaluatedEvidence(_StrictFrozenModel):
    evidence_key: str
    evidence_type: Literal[
        "macro_metric", "key_level_event", "options_regime", "material_event", "figure_fact"
    ]
    semantic_hash: str
    evidence_refs: list[EvidenceIdentity] = Field(min_length=1)
    materiality: Materiality
    outcome: EvaluationOutcome
    recommended_action: RecommendedAction
    affected_state_fields: list[AffectedStateField] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)

    @field_validator("evidence_key")
    @classmethod
    def strip_evidence_key(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("semantic_hash")
    @classmethod
    def validate_semantic_hash(cls, value: str) -> str:
        return _sha256(value, "semantic_hash")

    @field_validator("affected_state_fields", "reasons")
    @classmethod
    def validate_sorted_unique(cls, values: list[str], info: Any) -> list[str]:
        normalized = [_required_text(value) for value in values]
        if normalized != sorted(set(normalized)):
            raise ValueError(f"{info.field_name} must be sorted and unique")
        return normalized

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: list[EvidenceIdentity]) -> list[EvidenceIdentity]:
        keys = [(value.source, value.evidence_id) for value in values]
        if keys != sorted(set(keys)):
            raise ValueError("evidence_refs must be sorted and unique by (source, evidence_id)")
        return values


class EvidenceDeltaDecision(_StrictFrozenModel):
    schema_version: Literal["evidence_delta.v1"] = EVIDENCE_DELTA_SCHEMA_VERSION
    decision_id: str
    content_hash: str
    ruleset_version: Literal["evidence_delta.rules.v1"] = EVIDENCE_DELTA_RULESET_VERSION
    asset: str = Field(min_length=1, max_length=32)
    state_scope: StateScope
    canonical_state_id: str = Field(min_length=1, max_length=255)
    has_relevant_delta: bool
    materiality: Materiality
    recommended_action: RecommendedAction
    affected_state_fields: list[AffectedStateField] = Field(default_factory=list)
    trigger_reasons: list[str] = Field(min_length=1)
    evaluated_items: list[EvaluatedEvidence] = Field(default_factory=list)
    semantic_hashes: dict[str, str] = Field(default_factory=dict)

    @field_validator("decision_id", "asset", "canonical_state_id")
    @classmethod
    def strip_decision_identity(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return _sha256(value, "content_hash")

    @field_validator("affected_state_fields", "trigger_reasons")
    @classmethod
    def validate_sorted_unique(cls, values: list[str], info: Any) -> list[str]:
        normalized = [_required_text(value) for value in values]
        if normalized != sorted(set(normalized)):
            raise ValueError(f"{info.field_name} must be sorted and unique")
        return normalized

    @field_validator("semantic_hashes")
    @classmethod
    def validate_semantic_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        return {
            _required_text(key): _sha256(value, f"semantic_hashes[{key}]")
            for key, value in sorted(values.items())
        }

    @model_validator(mode="after")
    def validate_decision(self) -> "EvidenceDeltaDecision":
        expected_hash = compute_decision_content_hash(self)
        if self.content_hash != expected_hash:
            raise ValueError("content_hash does not match decision content")
        if self.decision_id != f"evidence_delta_{expected_hash[:24]}":
            raise ValueError("decision_id does not match content_hash")
        relevant = self.recommended_action is not RecommendedAction.NO_OP
        if self.has_relevant_delta != relevant:
            raise ValueError("has_relevant_delta contradicts recommended_action")
        item_keys = [(item.evidence_key, item.semantic_hash) for item in self.evaluated_items]
        if item_keys != sorted(item_keys) or len(item_keys) != len(set(item_keys)):
            raise ValueError("evaluated_items must be sorted and unique by evidence_key/hash")
        if not self.evaluated_items:
            if self.recommended_action is not RecommendedAction.NO_OP:
                raise ValueError("empty evaluation must be no_op")
            if self.materiality is not Materiality.NONE or self.affected_state_fields:
                raise ValueError("empty evaluation must have no materiality or affected fields")
            if self.trigger_reasons != ["no_evidence"] or self.semantic_hashes:
                raise ValueError("empty evaluation trace is invalid")
            return self
        expected_action = max(
            (item.recommended_action for item in self.evaluated_items),
            key=lambda candidate: _ACTION_RANK[candidate],
        )
        expected_materiality = max(
            (item.materiality for item in self.evaluated_items),
            key=lambda candidate: _MATERIALITY_RANK[candidate],
        )
        if self.recommended_action is not expected_action or self.materiality is not expected_materiality:
            raise ValueError("decision action/materiality does not match evaluated items")
        expected_affected = sorted(
            {
                field
                for item in self.evaluated_items
                if item.recommended_action is not RecommendedAction.NO_OP
                for field in item.affected_state_fields
            }
        )
        if self.affected_state_fields != expected_affected:
            raise ValueError("affected_state_fields do not match evaluated items")
        expected_reasons = sorted(
            {
                reason
                for item in self.evaluated_items
                if item.recommended_action is expected_action
                for reason in item.reasons
            }
        )
        if self.trigger_reasons != expected_reasons:
            raise ValueError("trigger_reasons do not match evaluated items")
        identity_counts = Counter(item.evidence_key for item in self.evaluated_items)
        hashes_by_key = {
            item.evidence_key: item.semantic_hash
            for item in self.evaluated_items
            if identity_counts[item.evidence_key] == 1
            and "authoritative_evidence_key:conflicting_payload" not in item.reasons
        }
        if self.semantic_hashes != hashes_by_key:
            raise ValueError("semantic_hashes must contain only unambiguous evaluated identities")
        return self

    @classmethod
    def build(cls, **values: Any) -> "EvidenceDeltaDecision":
        payload = {
            "schema_version": EVIDENCE_DELTA_SCHEMA_VERSION,
            "ruleset_version": EVIDENCE_DELTA_RULESET_VERSION,
            **values,
        }
        resolved_hash = compute_decision_content_hash(payload)
        return cls.model_validate(
            {
                **payload,
                "decision_id": f"evidence_delta_{resolved_hash[:24]}",
                "content_hash": resolved_hash,
            }
        )


def compute_decision_content_hash(value: EvidenceDeltaDecision | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("decision_id", None)
    payload.pop("content_hash", None)
    return content_hash(payload, exclude_keys=frozenset())


def _required_text(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


def _sha256(value: str, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != SHA256_LENGTH or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized
