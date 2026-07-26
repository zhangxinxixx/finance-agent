"""Typed, replay-safe consumer projections for ContextBundle v3.

This module is intentionally pure: it does not select data, invoke agents, or
claim that a consumer used the projection.  It only creates and validates the
explicit hand-off boundary that callers may pass to a domain consumer.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.context_bundle.schemas import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    AnalysisContextBundle,
)
from apps.analysis.evidence_delta.schemas import EvidenceDeltaDecision
from apps.analysis.state.hashing import content_hash


CONSUMER_PROJECTION_SCHEMA_VERSION = "analysis_context_consumer_projection.v1"
ConsumerName = Literal[
    "macro",
    "options",
    "risk",
    "technical",
    "positioning",
    "news",
    "market_odds",
    "fact_review",
    "coordinator",
]

# This is a consumer relevance allowlist, not a claim about any provider or
# source.  In particular, ``news`` means retained material-event evidence; it
# does not grant or emulate a Jin10 integration.
CONSUMER_EVIDENCE_TYPES: dict[str, frozenset[str]] = {
    "macro": frozenset({"macro_metric", "material_event"}),
    "options": frozenset({"options_regime", "key_level_event"}),
    "risk": frozenset({"macro_metric", "key_level_event", "options_regime", "material_event"}),
    "technical": frozenset({"key_level_event"}),
    "positioning": frozenset({"material_event"}),
    "news": frozenset({"material_event"}),
    "market_odds": frozenset({"material_event"}),
    "fact_review": frozenset({"macro_metric", "key_level_event", "options_regime", "material_event"}),
    "coordinator": frozenset({"macro_metric", "key_level_event", "options_regime", "material_event"}),
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ConsumerProjectionIdentity(_StrictFrozenModel):
    bundle_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    run_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    canonical_state_id: str = Field(min_length=1)
    state_scope: Literal["intraday", "daily_close", "weekly_fundamental"]
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("content_hash")
    @classmethod
    def _hash_is_sha256(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        return value


class ConsumerProjection(_StrictFrozenModel):
    """A filtered, independently re-validatable ContextBundle v3 hand-off."""

    schema_version: Literal["analysis_context_consumer_projection.v1"] = CONSUMER_PROJECTION_SCHEMA_VERSION
    consumer: ConsumerName
    projection_hash: str = Field(min_length=64, max_length=64)
    identity_payload: ConsumerProjectionIdentity
    canonical_state: dict[str, Any]
    retained_evidence: list[dict[str, Any]] = Field(default_factory=list)
    retained_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    accepted_facts: list[dict[str, Any]] = Field(default_factory=list)
    decision: EvidenceDeltaDecision
    decision_id: str = Field(min_length=1)
    selection_decisions: list[dict[str, Any]] = Field(default_factory=list)
    selection_trace: dict[str, Any]
    freshness: dict[str, Any] = Field(default_factory=dict)
    deferred_queue: list[dict[str, Any]] = Field(default_factory=list)
    processed_above_frontier: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    freshness_sla_seconds: dict[str, int] = Field(default_factory=dict)
    default_freshness_sla_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_projection(self) -> "ConsumerProjection":
        identity = self.identity_payload
        if self.decision_id != self.decision.decision_id:
            raise ValueError("decision_id does not match decision")
        if (
            self.decision.asset != identity.asset
            or self.decision.state_scope != identity.state_scope
            or self.decision.canonical_state_id != identity.canonical_state_id
        ):
            raise ValueError("decision identity does not match projection identity")
        if (
            self.canonical_state.get("asset") != identity.asset
            or self.canonical_state.get("state_scope") != identity.state_scope
        ):
            raise ValueError("canonical state does not match projection identity")
        allowed = CONSUMER_EVIDENCE_TYPES[self.consumer]
        evidence_keys: set[tuple[str, str]] = set()
        for item in self.retained_evidence:
            key = _evidence_key(item)
            if key in evidence_keys:
                raise ValueError("retained evidence must be unique by source and evidence_id")
            evidence_keys.add(key)
            if _evidence_type(item) not in allowed:
                raise ValueError("retained evidence is not allowed for consumer")
        for fact in self.accepted_facts:
            if fact.get("quality_status") != "accepted":
                raise ValueError("projection may carry accepted facts only")
        ref_keys = {_source_ref_key(item) for item in self.retained_source_refs}
        if len(ref_keys) != len(self.retained_source_refs):
            raise ValueError("retained source refs must be source-aware and unique")
        if {_source_ref_key(item) for item in identity.source_refs} != ref_keys:
            raise ValueError("identity source refs do not match retained source refs")
        expected_hash = compute_consumer_projection_hash(self)
        if self.projection_hash != expected_hash:
            raise ValueError("projection_hash does not match projection content")
        return self


def project_context_bundle(
    bundle: AnalysisContextBundle | Mapping[str, Any], *, consumer: ConsumerName
) -> ConsumerProjection:
    """Build a consumer-specific projection from an authentic v3 bundle.

    Typed input is dumped and model-validated again so a caller cannot bypass
    nested validation with ``model_copy`` or mutated mutable sub-values.
    """

    if consumer not in CONSUMER_EVIDENCE_TYPES:
        raise ValueError(f"unsupported context bundle consumer: {consumer}")
    normalized = _revalidate_bundle(bundle)
    canonical_state = _block_payload(normalized, "canonical_state")
    # A v3 daily-close Bundle may legitimately carry the backward-compatible
    # AnalysisState v1 document, whose payload predates scoped state. The
    # projection boundary makes the enclosing v3 scope explicit for consumers.
    canonical_state.setdefault("state_scope", normalized.state_scope)
    delta_evidence = _block_payload(normalized, "delta_evidence")
    facts = _block_payload(normalized, "facts")
    allowed = CONSUMER_EVIDENCE_TYPES[consumer]
    retained_evidence = [item for item in delta_evidence if _evidence_type(item) in allowed]
    accepted_facts = [item for item in facts if isinstance(item, dict) and item.get("quality_status") == "accepted"]
    retained_source_refs = _source_aware_refs(retained_evidence, accepted_facts)
    identity = {
        "bundle_id": normalized.bundle_id,
        "content_hash": normalized.content_hash,
        "run_id": normalized.run_id,
        "asset": normalized.asset,
        "canonical_state_id": normalized.canonical_state_id,
        "state_scope": normalized.state_scope,
        "source_refs": retained_source_refs,
    }
    payload: dict[str, Any] = {
        "schema_version": CONSUMER_PROJECTION_SCHEMA_VERSION,
        "consumer": consumer,
        "identity_payload": identity,
        "canonical_state": canonical_state,
        "retained_evidence": retained_evidence,
        "retained_source_refs": retained_source_refs,
        "accepted_facts": accepted_facts,
        "decision": normalized.evidence_delta_decision,
        "decision_id": normalized.evidence_delta_decision["decision_id"],
        "selection_decisions": normalized.selection_decisions,
        "selection_trace": normalized.selection_trace,
        "freshness": normalized.freshness,
        "deferred_queue": normalized.deferred_queue,
        "processed_above_frontier": normalized.processed_above_frontier,
        "freshness_sla_seconds": normalized.freshness_sla_seconds,
        "default_freshness_sla_seconds": normalized.default_freshness_sla_seconds,
    }
    payload["projection_hash"] = compute_consumer_projection_hash(payload)
    return ConsumerProjection.model_validate(payload)


# A short alias makes the intended boundary easy to discover for future callers.
build_consumer_projection = project_context_bundle


def validate_consumer_projection(
    projection: ConsumerProjection | Mapping[str, Any], expected_consumer: ConsumerName
) -> ConsumerProjection:
    """Revalidate an untrusted projection and bind it to one named consumer."""

    if expected_consumer not in CONSUMER_EVIDENCE_TYPES:
        raise ValueError(f"unsupported context bundle consumer: {expected_consumer}")
    payload = projection.model_dump(mode="json") if isinstance(projection, BaseModel) else dict(projection)
    validated = ConsumerProjection.model_validate(payload)
    if validated.consumer != expected_consumer:
        raise ValueError("projection consumer does not match expected consumer")
    return validated


def bind_projection_to_agent_output(
    projection: ConsumerProjection | Mapping[str, Any],
    agent_output: Mapping[str, Any] | BaseModel,
    *,
    expected_consumer: ConsumerName | None = None,
) -> Mapping[str, Any] | BaseModel:
    """Attach exact bundle identity to an output without claiming consumption.

    The caller remains responsible for actually using the projection.  This
    helper only makes that caller-owned hand-off auditable in all three output
    lineage locations.
    """

    validated = validate_consumer_projection(projection, expected_consumer or _projection_consumer(projection))
    values = agent_output.model_dump(mode="json") if isinstance(agent_output, BaseModel) else dict(agent_output)
    values = deepcopy(values)
    identity = validated.identity_payload.model_dump(mode="json")
    input_ids = dict(values.get("input_snapshot_ids") or {})
    input_ids["context_bundle_id"] = identity["bundle_id"]
    input_ids["context_bundle_hash"] = identity["content_hash"]
    input_ids["context_bundle_run_id"] = identity["run_id"]
    input_ids["context_bundle_projection_hash"] = validated.projection_hash
    input_ids["canonical_state_id"] = identity["canonical_state_id"]
    input_ids["state_scope"] = identity["state_scope"]
    input_ids["retained_evidence_ids"] = _retained_evidence_identities(validated)
    input_ids["evidence_delta_decision_id"] = validated.decision_id
    values["input_snapshot_ids"] = input_ids
    input_payload = dict(values.get("input_payload") or {})
    input_payload["context_bundle_identity"] = identity
    input_payload["context_bundle_consumer"] = validated.consumer
    values["input_payload"] = input_payload
    refs = list(values.get("source_refs") or [])
    lineage_ref = {"source": "analysis_context_bundle", "identity": identity}
    if lineage_ref not in refs:
        refs.append(lineage_ref)
    values["source_refs"] = refs
    if isinstance(agent_output, BaseModel):
        return type(agent_output).model_validate(values)
    return values


def consumer_projection_payload(
    projection: ConsumerProjection | Mapping[str, Any],
    *,
    expected_consumer: ConsumerName,
) -> dict[str, Any]:
    """Return the bounded typed content a consumer actually receives."""

    return validate_consumer_projection(projection, expected_consumer).model_dump(mode="json")


def consumer_projection_summary(projection: ConsumerProjection) -> dict[str, Any]:
    return {
        "decision_id": projection.decision_id,
        "decision_action": projection.decision.recommended_action.value,
        "state_scope": projection.identity_payload.state_scope,
        "retained_evidence_count": len(projection.retained_evidence),
        "retained_refs": list(projection.retained_source_refs),
        "accepted_fact_count": len(projection.accepted_facts),
        "accepted_fact_refs": [
            {
                "source": item.get("source"),
                "figure_fact_id": item.get("figure_fact_id"),
            }
            for item in projection.accepted_facts
        ],
    }


def consume_projection_for_agent_output(
    projection: ConsumerProjection | Mapping[str, Any],
    agent_output: Mapping[str, Any] | BaseModel,
    *,
    expected_consumer: ConsumerName,
) -> Mapping[str, Any] | BaseModel:
    """Apply one typed projection as bounded analysis context and safety policy."""

    validated = validate_consumer_projection(projection, expected_consumer)
    values = agent_output.model_dump(mode="json") if isinstance(agent_output, BaseModel) else dict(agent_output)
    values = deepcopy(values)
    input_payload = dict(values.get("input_payload") or {})
    input_payload["context_bundle_summary"] = consumer_projection_summary(validated)
    input_payload["context_bundle_projection"] = validated.model_dump(mode="json")
    values["input_payload"] = input_payload

    retained_refs = [dict(item) for item in validated.retained_source_refs]
    evidence_refs = list(values.get("evidence_refs") or [])
    for ref in retained_refs:
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    values["evidence_refs"] = evidence_refs

    if validated.decision.recommended_action.value == "manual_review":
        if values.get("status") == "success":
            values["status"] = "partial"
        values["confidence"] = min(float(values.get("confidence") or 0.0), 0.35)
        risk_points = list(values.get("risk_points") or [])
        reason = "ContextBundle evidence delta requires manual review."
        if reason not in risk_points:
            risk_points.append(reason)
        values["risk_points"] = risk_points
        invalid_conditions = list(values.get("invalid_conditions") or [])
        invalid = "Directional promotion is blocked until the ContextBundle review is resolved."
        if invalid not in invalid_conditions:
            invalid_conditions.append(invalid)
        values["invalid_conditions"] = invalid_conditions

    bound = bind_projection_to_agent_output(
        validated,
        values,
        expected_consumer=expected_consumer,
    )
    if isinstance(agent_output, BaseModel):
        return type(agent_output).model_validate(bound)
    return bound


def compute_consumer_projection_hash(value: ConsumerProjection | Mapping[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("projection_hash", None)
    return content_hash(payload, exclude_keys=frozenset())


def _revalidate_bundle(bundle: AnalysisContextBundle | Mapping[str, Any]) -> AnalysisContextBundle:
    payload = bundle.model_dump(mode="json") if isinstance(bundle, BaseModel) else dict(bundle)
    validated = AnalysisContextBundle.model_validate(payload)
    if validated.schema_version != CONTEXT_BUNDLE_SCHEMA_VERSION:
        raise ValueError("consumer projection requires analysis_context_bundle.v3")
    canonical_state = _block_payload(validated, "canonical_state")
    canonical_scope = canonical_state.get("state_scope")
    if canonical_state.get("asset") != validated.asset or (
        canonical_scope is not None and canonical_scope != validated.state_scope
    ):
        raise ValueError("canonical state identity does not match bundle")
    return validated


def _block_payload(bundle: AnalysisContextBundle, name: str) -> Any:
    block = next((item for item in bundle.blocks if item.name == name), None)
    if block is None:
        raise ValueError(f"bundle is missing {name} block")
    return deepcopy(block.payload)


def _evidence_type(item: Any) -> str:
    if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
        raise ValueError("retained evidence must contain a payload")
    evidence_type = item["payload"].get("evidence_type")
    if not isinstance(evidence_type, str) or not evidence_type:
        raise ValueError("retained evidence payload requires evidence_type")
    return evidence_type


def _evidence_key(item: Any) -> tuple[str, str]:
    if not isinstance(item, dict):
        raise ValueError("retained evidence must be an object")
    source, evidence_id = item.get("source"), item.get("evidence_id")
    if not isinstance(source, str) or not source.strip() or not isinstance(evidence_id, str) or not evidence_id.strip():
        raise ValueError("retained evidence requires source and evidence_id")
    return source, evidence_id


def _source_aware_refs(evidence: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in [*evidence, *facts]:
        source = item.get("source")
        evidence_id = item.get("evidence_id") or item.get("figure_fact_id")
        if (
            not isinstance(source, str)
            or not source.strip()
            or not isinstance(evidence_id, str)
            or not evidence_id.strip()
        ):
            raise ValueError("retained evidence/fact requires source-aware identity")
        ref = dict(item.get("source_ref") or {})
        ref["source"] = source
        ref["evidence_id"] = evidence_id
        refs.append(ref)
    refs.sort(key=lambda item: _source_ref_key(item))
    if len({_source_ref_key(item) for item in refs}) != len(refs):
        raise ValueError("retained source references must be unique by source and evidence_id")
    return refs


def _source_ref_key(item: Any) -> tuple[str, str]:
    if not isinstance(item, dict):
        raise ValueError("source ref must be an object")
    source, evidence_id = item.get("source"), item.get("evidence_id")
    if not isinstance(source, str) or not source.strip() or not isinstance(evidence_id, str) or not evidence_id.strip():
        raise ValueError("source refs require source and evidence_id")
    return source, evidence_id


def _projection_consumer(projection: ConsumerProjection | Mapping[str, Any]) -> ConsumerName:
    consumer = projection.consumer if isinstance(projection, ConsumerProjection) else projection.get("consumer")
    if consumer not in CONSUMER_EVIDENCE_TYPES:
        raise ValueError("projection has unsupported consumer")
    return consumer


def _retained_evidence_identities(projection: ConsumerProjection) -> list[dict[str, str]]:
    """Return source-aware evidence identity; IDs alone are not globally unique."""

    return [
        {"source": source, "evidence_id": evidence_id}
        for source, evidence_id in sorted(_evidence_key(item) for item in projection.retained_evidence)
    ]
