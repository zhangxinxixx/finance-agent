"""Fail-closed contracts for the XAUUSD daily-close materialization canary.

This module deliberately does not schedule consumers, rebuild Bundles, or set
``state_delta_primary``.  An orchestrator may perform one fresh-Bundle retry
after a CAS conflict; this contract records its lineage and closes a second
conflict instead of retrying stale work.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AcceptedOutputReference, AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateDecision
from apps.analysis.agents.schemas import AgentOutput
from apps.analysis.context_bundle.projection import ConsumerProjection
from apps.analysis.state import (
    StateTransitionConsistencyDecision,
    TransitionReviewResult,
    evaluate_state_transition_consistency,
    materialize_reviewed_transition_scoped,
)
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.repository import CanonicalHeadConflictError
from apps.runtime.artifact_registry import select_exact_context_bundle_artifact
from database.models.analysis_state import AnalysisState, AnalysisStateHead, CanaryApproval


logger = logging.getLogger(__name__)

CANARY_AUTHORITY_SCHEMA_VERSION = "analysis_state_canary_authority.v2"
CANARY_MATERIALIZATION_REQUEST_SCHEMA_VERSION = "analysis_state_canary_request.v4"
CANARY_MATERIALIZATION_RESULT_SCHEMA_VERSION = "analysis_state_canary_result.v4"
CANARY_ASSET = "XAUUSD"
CANARY_STATE_SCOPE = "daily_close"
CANARY_CONSUMERS = frozenset(
    {
        "macro",
        "options",
        "risk",
        "technical",
        "positioning",
        "news",
        "market_odds",
        "fact_review",
        "coordinator",
    }
)
CANARY_AGENT_CONSUMERS = {
    "macro_liquidity_agent": "macro",
    "cme_options_agent": "options",
    "risk_agent": "risk",
    "technical_agent": "technical",
    "positioning_agent": "positioning",
    "news_agent": "news",
    "market_odds_agent": "market_odds",
    "fact_review_agent": "fact_review",
    "coordinator_agent": "coordinator",
}
CANARY_QUALITY_GATE_AGENT_ORDER = tuple(CANARY_AGENT_CONSUMERS)


class CanaryAuthorityPayload(BaseModel):
    """The exact reviewed consumer inputs authorizing one materialization.

    Hashes alone are not authority: the Materializer receives the fully
    validated projections plus the FactReview output and recomputes this
    immutable digest before it considers a PASS decision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_canary_authority.v2"] = CANARY_AUTHORITY_SCHEMA_VERSION
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    asset: Literal["XAUUSD"]
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    consumer_projections: dict[str, ConsumerProjection]
    agent_outputs: dict[str, AgentOutput]
    agent_output_hashes: dict[str, str]
    quality_gate_input_hashes: list[str]
    fact_review_output: AgentOutput
    fact_review_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_output_reference: AcceptedOutputReference
    accepted_output: AgentOutput | None = None
    accepted_output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    accepted_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    transition_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    transition_consistency: StateTransitionConsistencyDecision
    transition_consistency_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_authority_payload(self) -> "CanaryAuthorityPayload":
        if set(self.consumer_projections) != CANARY_CONSUMERS:
            raise ValueError("authority payload must contain exactly the nine canary consumers")
        for name, projection in self.consumer_projections.items():
            identity = projection.identity_payload
            if projection.consumer != name:
                raise ValueError("authority projection key must match consumer")
            if (
                identity.bundle_id != self.context_bundle_id
                or identity.content_hash != self.context_bundle_hash
                or identity.run_id != self.run_id
                or identity.asset != self.asset
                or identity.state_scope != self.state_scope
                or identity.canonical_state_id != self.canonical_state_id
            ):
                raise ValueError("authority projection does not match Bundle identity")
        if set(self.agent_outputs) != set(CANARY_AGENT_CONSUMERS):
            raise ValueError("authority payload must contain exactly the nine canary AgentOutputs")
        if set(self.agent_output_hashes) != set(CANARY_AGENT_CONSUMERS):
            raise ValueError("agent_output_hashes must contain exactly the nine canary AgentOutputs")
        for agent_name, consumer in CANARY_AGENT_CONSUMERS.items():
            output = self.agent_outputs[agent_name]
            if output.agent_name != agent_name:
                raise ValueError("authority AgentOutput key must match agent_name")
            projection = self.consumer_projections[consumer]
            _validate_output_projection_lineage(
                output=output,
                projection=projection,
                context_bundle_id=self.context_bundle_id,
                context_bundle_hash=self.context_bundle_hash,
                run_id=self.run_id,
                canonical_state_id=self.canonical_state_id,
                state_scope=self.state_scope,
            )
            if self.agent_output_hashes[agent_name] != _stable_hash(output):
                raise ValueError(f"agent_output_hashes does not match {agent_name}")
        expected_gate_hashes = [self.agent_output_hashes[agent_name] for agent_name in CANARY_QUALITY_GATE_AGENT_ORDER]
        if self.quality_gate_input_hashes != expected_gate_hashes:
            raise ValueError("quality_gate_input_hashes must match the exact ordered gate inputs")
        review = self.fact_review_output
        bound_review = self.agent_outputs["fact_review_agent"]
        if review != bound_review:
            raise ValueError("fact_review_output must equal the bound fact_review_agent output")
        if self.fact_review_output_hash != self.agent_output_hashes["fact_review_agent"]:
            raise ValueError("fact_review_output_hash does not match bound FactReview output")
        accepted = self.accepted_output_reference
        if accepted.source == "none":
            if any(
                value is not None
                for value in (
                    self.accepted_output,
                    self.accepted_output_hash,
                    self.accepted_artifact_hash,
                )
            ):
                raise ValueError("unaccepted authority cannot carry an accepted output")
        else:
            if self.accepted_output is None:
                raise ValueError("accepted authority requires the actual immutable AgentOutput")
            if accepted.artifact_ref is None or not _has_artifact_identity(accepted.artifact_ref):
                raise ValueError("accepted authority requires immutable rendered artifact identity")
            if (
                self.accepted_output.agent_name != accepted.agent_name
                or self.accepted_output.snapshot_id != accepted.snapshot_id
            ):
                raise ValueError("accepted AgentOutput does not match accepted output identity")
            actual_accepted_hash = _stable_hash(self.accepted_output)
            if self.accepted_output_hash != actual_accepted_hash:
                raise ValueError("accepted_output_hash does not match accepted AgentOutput")
            if self.accepted_artifact_hash != _stable_hash(accepted.artifact_ref):
                raise ValueError("accepted_artifact_hash does not match accepted artifact identity")
            if (
                accepted.source == "primary"
                and self.accepted_output_hash != self.agent_output_hashes["coordinator_agent"]
            ):
                raise ValueError("accepted primary output must equal the bound coordinator_agent output")
        consistency = self.transition_consistency
        if (
            consistency.accepted_output_source != accepted.source
            or consistency.accepted_output_agent_name != accepted.agent_name
            or consistency.accepted_output_snapshot_id != accepted.snapshot_id
            or consistency.accepted_output_hash != self.accepted_output_hash
            or consistency.transition_review_hash != self.transition_review_hash
        ):
            raise ValueError("transition consistency identity does not match authority payload")
        if self.transition_consistency_hash != _stable_hash(consistency):
            raise ValueError("transition_consistency_hash does not match consistency decision")
        expected_hash = compute_canary_authority_hash(self)
        if self.authority_hash != expected_hash:
            raise ValueError("authority_hash does not match authority payload")
        return self

    @classmethod
    def build(
        cls,
        *,
        context_bundle_id: str,
        context_bundle_hash: str,
        run_id: str,
        canonical_state_id: str,
        consumer_projections: dict[str, ConsumerProjection],
        quality_gate_inputs: list[AgentOutput],
        accepted_output_reference: AcceptedOutputReference,
        accepted_output: AgentOutput | None,
        transition_review: TransitionReviewResult,
    ) -> "CanaryAuthorityPayload":
        consistency = evaluate_state_transition_consistency(
            review=transition_review,
            accepted_output_reference=accepted_output_reference,
            accepted_output=accepted_output,
        )
        if [output.agent_name for output in quality_gate_inputs] != list(CANARY_QUALITY_GATE_AGENT_ORDER):
            raise ValueError("QualityGate inputs must be the exact ordered nine canary AgentOutputs")
        agent_outputs = {
            output.agent_name: AgentOutput.model_validate(output.model_dump(mode="json", exclude_computed_fields=True))
            for output in quality_gate_inputs
        }
        agent_output_hashes = {name: _stable_hash(output) for name, output in agent_outputs.items()}
        accepted_artifact_hash = (
            _stable_hash(accepted_output_reference.artifact_ref)
            if accepted_output_reference.artifact_ref is not None
            else None
        )
        payload = {
            "schema_version": CANARY_AUTHORITY_SCHEMA_VERSION,
            "context_bundle_id": context_bundle_id,
            "context_bundle_hash": context_bundle_hash,
            "run_id": run_id,
            "asset": CANARY_ASSET,
            "state_scope": CANARY_STATE_SCOPE,
            "canonical_state_id": canonical_state_id,
            "consumer_projections": consumer_projections,
            "agent_outputs": agent_outputs,
            "agent_output_hashes": agent_output_hashes,
            "quality_gate_input_hashes": [agent_output_hashes[output.agent_name] for output in quality_gate_inputs],
            "fact_review_output": agent_outputs["fact_review_agent"],
            "fact_review_output_hash": agent_output_hashes["fact_review_agent"],
            "accepted_output_reference": accepted_output_reference,
            "accepted_output": accepted_output,
            "accepted_output_hash": consistency.accepted_output_hash,
            "accepted_artifact_hash": accepted_artifact_hash,
            "transition_review_hash": consistency.transition_review_hash,
            "transition_consistency": consistency,
            "transition_consistency_hash": _stable_hash(consistency),
        }
        return cls(authority_hash=_hash_payload(payload), **payload)


class CanaryActivation(BaseModel):
    """Explicit, auditable authority for one XAUUSD/daily-close canary run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    approval_id: str = Field(min_length=1)
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_source: Literal["persistent_approval"] = "persistent_approval"
    activation_identity: str = Field(min_length=1)


class CanaryMaterializationRequest(BaseModel):
    """Scoped hand-off after FactReview and before the single CAS attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_canary_request.v4"] = CANARY_MATERIALIZATION_REQUEST_SCHEMA_VERSION
    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    approval_id: str = Field(min_length=1)
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_source: Literal["persistent_approval"] = "persistent_approval"
    activation_identity: str = Field(min_length=1)
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumer_projection_hashes: dict[str, str]
    fact_review_snapshot_id: str = Field(min_length=1)
    quality_gate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_loop_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    review: TransitionReviewResult

    @field_validator(
        "run_id",
        "canonical_state_id",
        "approval_id",
        "activation_identity",
        "context_bundle_id",
        "fact_review_snapshot_id",
    )
    @classmethod
    def strip_required_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("canary request identity must not be blank")
        return normalized

    @field_validator("consumer_projection_hashes")
    @classmethod
    def validate_consumer_projection_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != CANARY_CONSUMERS:
            raise ValueError("consumer_projection_hashes must contain exactly the nine canary consumers")
        normalized: dict[str, str] = {}
        for consumer, projection_hash in value.items():
            digest = str(projection_hash).strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"consumer projection hash is invalid: {consumer}")
            normalized[consumer] = digest
        return normalized

    @model_validator(mode="after")
    def validate_review_lineage(self) -> "CanaryMaterializationRequest":
        if self.review.previous_state_id != self.canonical_state_id:
            raise ValueError("review previous_state_id must match canary canonical_state_id")
        if self.review.next_state.asset != self.asset:
            raise ValueError("review asset must match canary asset")
        if getattr(self.review.next_state, "state_scope", None) != self.state_scope:
            raise ValueError("review state_scope must match canary state_scope")
        if self.activation_identity != self.approval_id:
            raise ValueError("persistent approval activation identity must match approval_id")
        return self


class CanaryMaterializationResult(BaseModel):
    """Audit result that never replaces or invalidates legacy output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_canary_result.v4"] = CANARY_MATERIALIZATION_RESULT_SCHEMA_VERSION
    status: Literal[
        "canonical_advanced",
        "candidate_recorded",
        "observe_only",
        "recompute_required",
        "failed",
    ]
    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    approval_id: str = Field(min_length=1)
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_source: Literal["persistent_approval"]
    activation_identity: str = Field(min_length=1)
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    legacy_output_preserved: Literal[True] = True
    canonical_advanced: bool = False
    candidate_state_id: str | None = None
    canonical_state_id: str | None = None
    canonical_version: int | None = None
    recompute_required: bool = False
    latest_canonical_state_id: str | None = None
    latest_head_version: int | None = None
    materialization_disposition: str | None = None
    reason: str | None = None
    recompute_attempt_count: int = Field(default=0, ge=0, le=1)
    superseded_context_bundle_id: str | None = None
    superseded_context_bundle_hash: str | None = None
    superseded_canonical_state_id: str | None = None
    recompute_trace: dict[str, Any] | None = None
    authority_hash: str | None = None
    consumer_projection_hashes: dict[str, str] = Field(default_factory=dict)
    fact_review_snapshot_id: str | None = None
    quality_gate_hash: str | None = None
    agent_loop_hash: str | None = None
    attempt_audit_path: str | None = None
    attempt_audit_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_status_flags(self) -> "CanaryMaterializationResult":
        if self.canonical_advanced != (self.status == "canonical_advanced"):
            raise ValueError("canonical_advanced must match result status")
        if self.recompute_required != (self.status == "recompute_required"):
            raise ValueError("recompute_required must match result status")
        supersession = (
            self.superseded_context_bundle_id,
            self.superseded_context_bundle_hash,
            self.superseded_canonical_state_id,
        )
        if self.recompute_attempt_count == 0 and any(supersession):
            raise ValueError("supersession lineage requires a recompute attempt")
        if self.recompute_attempt_count == 1 and not all(supersession):
            raise ValueError("recompute attempt requires complete supersession lineage")
        if self.recompute_trace is not None and self.recompute_attempt_count != 1:
            raise ValueError("recompute trace requires a recompute attempt")
        if self.status in {"canonical_advanced", "candidate_recorded"}:
            if self.authority_hash is None or set(self.consumer_projection_hashes) != CANARY_CONSUMERS:
                raise ValueError("authoritative materialization result requires complete authority lineage")
            if not all((self.fact_review_snapshot_id, self.quality_gate_hash, self.agent_loop_hash)):
                raise ValueError("authoritative materialization result requires FactReview/Gate lineage")
        return self


def resolve_canary_activation(
    *,
    snapshot_asset: Any,
    snapshot_trade_date: Any,
    run_id: Any,
    shadow_input: dict[str, Any] | None,
    approval: CanaryApproval | None,
) -> CanaryActivation:
    """Bind one server-validated persistent approval to exact runtime lineage."""

    if not isinstance(shadow_input, dict):
        raise ValueError("canary activation requires state_shadow_input")
    control_keys = {"canary_trade_dates", "canary_run_ids", "canary_manual_request", "canary_enabled"}
    forbidden = sorted(key for key in control_keys if key in shadow_input)
    if forbidden:
        raise ValueError("caller-owned canary activation controls are forbidden: " + ", ".join(forbidden))
    if approval is None:
        raise ValueError("persistent canary approval is required")

    asset = _required_text(snapshot_asset, field="snapshot_asset")
    trade_date = _date_value(snapshot_trade_date, field="snapshot_trade_date")
    normalized_run_id = _required_text(run_id, field="run_id")
    if asset != CANARY_ASSET:
        raise ValueError("canary activation is limited to asset=XAUUSD")
    if _required_text(shadow_input.get("asset"), field="asset") != asset:
        raise ValueError("canary asset must match analysis snapshot asset")
    if _date_value(shadow_input.get("trade_date"), field="trade_date") != trade_date:
        raise ValueError("canary trade_date must match analysis snapshot trade_date")
    if shadow_input.get("state_scope") != CANARY_STATE_SCOPE:
        raise ValueError("canary activation is limited to state_scope=daily_close")
    if approval.asset != asset or approval.state_scope != CANARY_STATE_SCOPE:
        raise ValueError("persistent canary approval scope does not match analysis request")
    if approval.trade_date is not None and approval.trade_date != trade_date:
        raise ValueError("persistent canary approval trade_date does not match analysis request")
    if approval.run_id is not None and approval.run_id != normalized_run_id:
        raise ValueError("persistent canary approval run_id does not match analysis request")
    if approval.status != "active":
        raise ValueError("persistent canary approval is not active")
    canonical_state_id = _required_text(shadow_input.get("canonical_state_id"), field="canonical_state_id")
    expected_head_version = shadow_input.get("expected_head_version")
    if (
        isinstance(expected_head_version, bool)
        or not isinstance(expected_head_version, int)
        or expected_head_version < 0
    ):
        raise ValueError("canary expected_head_version must be a non-negative integer")

    return CanaryActivation(
        asset=asset,
        trade_date=trade_date,
        run_id=normalized_run_id,
        state_scope=CANARY_STATE_SCOPE,
        canonical_state_id=canonical_state_id,
        expected_head_version=expected_head_version,
        approval_id=approval.approval_id,
        approval_hash=approval.approval_hash,
        activation_identity=approval.approval_id,
    )


def materialize_canary_request(
    session: Session,
    *,
    request: CanaryMaterializationRequest | dict[str, Any],
    quality_gate: QualityGateDecision | dict[str, Any],
    agent_loop: AgentLoopDecision | dict[str, Any],
    task_run_id: str,
    analysis_snapshot_db_id: str | None = None,
    authority_payload: CanaryAuthorityPayload | dict[str, Any] | None = None,
) -> CanaryMaterializationResult:
    """Apply one scoped CAS attempt; stale state yields an auditable retry request."""

    validated = CanaryMaterializationRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, BaseModel) else request
    )
    if _required_text(task_run_id, field="task_run_id") != validated.run_id:
        raise ValueError("canary materialization task_run_id must match request run_id")
    audit = _audit_fields(validated)
    try:
        authority = _validate_authority_payload(validated, authority_payload)
    except ValueError as exc:
        return CanaryMaterializationResult(
            status="failed", **audit, reason=f"authority_binding_invalid:{str(exc)[:160]}"
        )
    gate = QualityGateDecision.model_validate(
        quality_gate.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(quality_gate, QualityGateDecision)
        else quality_gate
    )
    loop = AgentLoopDecision.model_validate(
        agent_loop.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(agent_loop, AgentLoopDecision)
        else agent_loop
    )
    if validated.quality_gate_hash != compute_canary_quality_gate_hash(gate, authority_hash=authority.authority_hash):
        return CanaryMaterializationResult(
            status="failed",
            **audit,
            reason="canary quality_gate_hash does not match supplied authority-bound QualityGate",
        )
    if validated.agent_loop_hash != compute_canary_agent_loop_hash(loop, authority_hash=authority.authority_hash):
        return CanaryMaterializationResult(
            status="failed", **audit, reason="canary agent_loop_hash does not match supplied authority-bound AgentLoop"
        )
    if authority.transition_consistency.status != "consistent":
        return CanaryMaterializationResult(
            status="observe_only",
            **audit,
            materialization_disposition="manual_review_required",
            reason=(f"transition_consistency:{authority.transition_consistency.status}"),
        )
    try:
        # Repository append and head CAS are one outer savepoint: a stale CAS
        # rolls back both the new state and its transition before returning.
        with session.begin_nested():
            result = materialize_reviewed_transition_scoped(
                session,
                state_scope=validated.state_scope,
                review=validated.review,
                quality_gate=gate,
                agent_loop=loop,
                task_run_id=validated.run_id,
                expected_head_version=validated.expected_head_version,
                transition_consistency=authority.transition_consistency,
                analysis_snapshot_db_id=analysis_snapshot_db_id,
            )
    except CanonicalHeadConflictError:
        session.expire_all()
        latest = _get_latest_head(session)
        return CanaryMaterializationResult(
            status="recompute_required",
            **audit,
            recompute_required=True,
            latest_canonical_state_id=latest.canonical_state_id if latest else None,
            latest_head_version=latest.version if latest else None,
            reason="canonical_head_compare_and_swap_conflict",
        )
    except Exception as exc:
        logger.exception("Canary AnalysisState materialization failed")
        return CanaryMaterializationResult(
            status="failed",
            **audit,
            reason=f"{type(exc).__name__}:canary_materialization_failed",
        )

    if result.canonical_advanced:
        return CanaryMaterializationResult(
            status="canonical_advanced",
            **audit,
            canonical_advanced=True,
            candidate_state_id=result.state_id,
            canonical_state_id=result.canonical_state_id,
            canonical_version=result.canonical_version,
            materialization_disposition=result.disposition,
        )
    if result.disposition == "manual_review_candidate":
        return CanaryMaterializationResult(
            status="candidate_recorded",
            **audit,
            candidate_state_id=result.state_id,
            materialization_disposition=result.disposition,
        )
    return CanaryMaterializationResult(status="observe_only", **audit, materialization_disposition=result.disposition)


def mark_canary_recompute_result(
    result: CanaryMaterializationResult | dict[str, Any],
    *,
    superseded: CanaryMaterializationResult | dict[str, Any],
    trace: dict[str, Any] | None = None,
) -> CanaryMaterializationResult:
    """Attach one-hop lineage and fail closed if that fresh attempt also conflicts."""

    validated = CanaryMaterializationResult.model_validate(result)
    previous = CanaryMaterializationResult.model_validate(superseded)
    if previous.status != "recompute_required" or previous.recompute_attempt_count != 0:
        raise ValueError("recompute requires an initial recompute_required result")
    payload = {
        **validated.model_dump(mode="json"),
        "recompute_attempt_count": 1,
        "superseded_context_bundle_id": previous.context_bundle_id,
        "superseded_context_bundle_hash": previous.context_bundle_hash,
        "superseded_canonical_state_id": previous.requested_canonical_state_id,
        "recompute_trace": trace,
    }
    if validated.status == "recompute_required":
        payload.update(
            status="failed",
            recompute_required=False,
            reason="canonical_head_compare_and_swap_conflict_after_recompute",
        )
    return CanaryMaterializationResult.model_validate(payload)


def failed_canary_materialization_result(
    request: CanaryMaterializationRequest | dict[str, Any], *, reason: str
) -> CanaryMaterializationResult:
    """Build a fail-closed result without attempting any write."""

    validated = CanaryMaterializationRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, BaseModel) else request
    )
    return CanaryMaterializationResult(status="failed", **_audit_fields(validated), reason=str(reason)[:200])


def prepare_canary_recompute_shadow_input(
    session: Session,
    *,
    conflict_result: CanaryMaterializationResult | dict[str, Any],
    shadow_input: dict[str, Any],
    created_at: datetime,
    current_run_id: str,
    storage_root: str,
) -> dict[str, Any]:
    """Rebase one bounded retry input on the latest exact scoped head.

    This function only prepares input. The Runner must execute a complete new
    Composite attempt so the fresh Bundle is consumed by all nine consumers
    and receives fresh FactReview/QualityGate authority.
    """

    conflict = CanaryMaterializationResult.model_validate(conflict_result)
    if conflict.status != "recompute_required" or conflict.recompute_attempt_count != 0:
        raise ValueError("canary recompute requires an initial recompute_required result")
    if not isinstance(shadow_input.get("evidence"), list):
        raise ValueError("fresh canary recompute requires explicit evidence")
    session.expire_all()
    latest = _get_latest_head(session)
    if latest is None:
        raise ValueError("latest scoped canonical head is unavailable")
    if (
        latest.canonical_state_id != conflict.latest_canonical_state_id
        or latest.version != conflict.latest_head_version
    ):
        raise CanonicalHeadConflictError("scoped canonical head changed before recompute preparation")
    latest_state = session.get(AnalysisState, latest.canonical_state_id)
    if latest_state is None:
        raise ValueError("latest scoped canonical state is unavailable")
    if latest_state.asset != CANARY_ASSET or latest_state.state_scope != CANARY_STATE_SCOPE:
        raise ValueError("latest canonical state does not match canary scope")
    payload = dict(latest_state.payload or {})
    if _date_value(payload.get("trade_date"), field="latest_state.trade_date") != conflict.trade_date:
        raise ValueError("latest canonical trade_date changed; stale run cannot recompute")
    base_state_id = str(latest_state.previous_state_id or "").strip()
    if not base_state_id:
        raise ValueError("latest scoped canonical state has no predecessor Bundle lineage")
    identity = latest_state.input_snapshot_ids
    if not isinstance(identity, dict):
        raise ValueError("latest scoped canonical state Bundle identity is unavailable")
    identity_keys = {
        "bundle_id": "context_bundle_id",
        "content_hash": "context_bundle_hash",
        "run_id": "context_bundle_run_id",
        "canonical_state_id": "canonical_state_id",
    }
    required_identity = {
        field: str(identity.get(snapshot_key) or "").strip() for field, snapshot_key in identity_keys.items()
    }
    if any(not value for value in required_identity.values()):
        raise ValueError("latest scoped canonical state Bundle identity is incomplete")
    payload_identity = payload.get("input_snapshot_ids")
    if not isinstance(payload_identity, dict) or any(
        str(payload_identity.get(identity_keys[field]) or "").strip() != value
        for field, value in required_identity.items()
    ):
        raise ValueError("latest scoped canonical state payload Bundle identity conflicts")
    if required_identity["canonical_state_id"] != base_state_id:
        raise ValueError("latest scoped canonical state predecessor Bundle lineage conflicts")
    continuity_descriptor = select_exact_context_bundle_artifact(
        session,
        bundle_id=required_identity["bundle_id"],
        content_hash=required_identity["content_hash"],
        run_id=required_identity["run_id"],
        asset=CANARY_ASSET,
        state_scope=CANARY_STATE_SCOPE,
        base_canonical_state_id=base_state_id,
        current_run_id=current_run_id,
        storage_root=storage_root,
    )
    if continuity_descriptor is None:
        raise ValueError("latest scoped canonical state ContextBundle artifact is unavailable")

    refreshed = dict(shadow_input)
    for key in (
        "context_bundle_artifact",
        "previous_context_bundle_artifact",
        "previous_bundle_path",
        "previous_semantic_hashes",
        "deferred_queue",
        "processed_above_frontier",
        "freshness_sla_seconds",
        "default_freshness_sla_seconds",
        "evidence_cursors",
    ):
        refreshed.pop(key, None)
    refreshed.update(
        {
            "asset": CANARY_ASSET,
            "state_scope": CANARY_STATE_SCOPE,
            "canonical_state_id": latest_state.id,
            "canonical_state": payload,
            "expected_head_version": latest.version,
            "previous_context_bundle_artifact": continuity_descriptor,
            "previous_context_bundle_base_canonical_state_id": base_state_id,
            "assembled_at": created_at,
        }
    )
    return refreshed


def build_canary_recompute_registry_descriptor(
    descriptor: dict[str, Any],
    *,
    conflict_result: CanaryMaterializationResult | dict[str, Any],
) -> dict[str, Any]:
    """Attach the one-hop predecessor authority to a fresh Bundle descriptor."""

    conflict = CanaryMaterializationResult.model_validate(conflict_result)
    if conflict.status != "recompute_required" or conflict.recompute_attempt_count != 0:
        raise ValueError("canary recompute descriptor requires an initial conflict")
    metadata = descriptor.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("fresh Bundle registry descriptor is incomplete")
    if metadata.get("canonical_state_id") != conflict.latest_canonical_state_id:
        raise ValueError("fresh Bundle canonical state does not match latest scoped head")
    return {
        **descriptor,
        "metadata": {
            **metadata,
            "artifact_role": "canary_recompute",
            "canary_recompute_attempt": 1,
            "supersedes_bundle_id": conflict.context_bundle_id,
            "supersedes_bundle_hash": conflict.context_bundle_hash,
            "supersedes_canonical_state_id": conflict.requested_canonical_state_id,
        },
    }


def _audit_fields(request: CanaryMaterializationRequest) -> dict[str, Any]:
    return {
        "asset": request.asset,
        "trade_date": request.trade_date,
        "run_id": request.run_id,
        "state_scope": request.state_scope,
        "approval_id": request.approval_id,
        "approval_hash": request.approval_hash,
        "activation_source": request.activation_source,
        "activation_identity": request.activation_identity,
        "context_bundle_id": request.context_bundle_id,
        "context_bundle_hash": request.context_bundle_hash,
        "requested_canonical_state_id": request.canonical_state_id,
        "expected_head_version": request.expected_head_version,
        "authority_hash": request.authority_hash,
        "consumer_projection_hashes": dict(request.consumer_projection_hashes),
        "fact_review_snapshot_id": request.fact_review_snapshot_id,
        "quality_gate_hash": request.quality_gate_hash,
        "agent_loop_hash": request.agent_loop_hash,
    }


def _get_latest_head(session: Session) -> AnalysisStateHead | None:
    return session.scalar(
        select(AnalysisStateHead).where(
            AnalysisStateHead.asset == CANARY_ASSET,
            AnalysisStateHead.state_scope == CANARY_STATE_SCOPE,
        )
    )


def compute_canary_quality_gate_hash(
    value: QualityGateDecision | dict[str, Any],
    *,
    authority_hash: str | None = None,
) -> str:
    """Return the stable QualityGate digest required in a canary request."""

    gate = QualityGateDecision.model_validate(
        value.model_dump(mode="json", exclude_computed_fields=True) if isinstance(value, QualityGateDecision) else value
    )
    return _hash_payload(
        {"quality_gate": gate.model_dump(mode="json", exclude_computed_fields=True), "authority_hash": authority_hash}
    )


def compute_canary_agent_loop_hash(
    value: AgentLoopDecision | dict[str, Any],
    *,
    authority_hash: str | None = None,
) -> str:
    """Return the stable AgentLoop digest required in a canary request."""

    loop = AgentLoopDecision.model_validate(
        value.model_dump(mode="json", exclude_computed_fields=True) if isinstance(value, AgentLoopDecision) else value
    )
    return _hash_payload(
        {"agent_loop": loop.model_dump(mode="json", exclude_computed_fields=True), "authority_hash": authority_hash}
    )


def _stable_hash(value: BaseModel) -> str:
    return content_hash(value.model_dump(mode="json", exclude_computed_fields=True), exclude_keys=frozenset())


def _has_artifact_identity(value: BaseModel) -> bool:
    payload = value.model_dump(mode="json", exclude_none=True)
    return any(
        item
        for item in (
            payload.get("analysis_snapshot"),
            payload.get("final_report_paths"),
            payload.get("strategy_card_paths"),
        )
    )


def _validate_output_projection_lineage(
    *,
    output: AgentOutput,
    projection: ConsumerProjection,
    context_bundle_id: str,
    context_bundle_hash: str,
    run_id: str,
    canonical_state_id: str,
    state_scope: str,
) -> None:
    expected_input_ids = {
        "context_bundle_id": context_bundle_id,
        "context_bundle_hash": context_bundle_hash,
        "context_bundle_run_id": run_id,
        "context_bundle_projection_hash": projection.projection_hash,
        "canonical_state_id": canonical_state_id,
        "state_scope": state_scope,
        "retained_evidence_ids": [
            {"source": item["source"], "evidence_id": item["evidence_id"]}
            for item in sorted(
                projection.retained_evidence,
                key=lambda item: (item["source"], item["evidence_id"]),
            )
        ],
        "evidence_delta_decision_id": projection.decision_id,
    }
    if any(output.input_snapshot_ids.get(key) != value for key, value in expected_input_ids.items()):
        raise ValueError(f"{output.agent_name} output does not match authority Bundle/projection")
    payload = output.input_payload or {}
    if payload.get("context_bundle_consumer") != projection.consumer or payload.get(
        "context_bundle_projection"
    ) != projection.model_dump(mode="json"):
        raise ValueError(f"{output.agent_name} output did not consume its exact authority projection")


def compute_canary_authority_hash(
    value: CanaryAuthorityPayload | dict[str, Any],
) -> str:
    """Stable digest over the exact FactReview output and nine projections."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("authority_hash", None)
    return _hash_payload(payload)


def _hash_payload(value: dict[str, Any]) -> str:
    return content_hash(value, exclude_keys=frozenset())


def _validate_authority_payload(
    request: CanaryMaterializationRequest,
    payload: CanaryAuthorityPayload | dict[str, Any] | None,
) -> CanaryAuthorityPayload:
    if payload is None:
        raise ValueError("authority payload is required")
    authority = CanaryAuthorityPayload.model_validate(
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    )
    if request.authority_hash != authority.authority_hash:
        raise ValueError("request authority_hash does not match authority payload")
    if (
        authority.context_bundle_id != request.context_bundle_id
        or authority.context_bundle_hash != request.context_bundle_hash
        or authority.run_id != request.run_id
        or authority.canonical_state_id != request.canonical_state_id
    ):
        raise ValueError("authority payload does not match request Bundle lineage")
    hashes = {name: projection.projection_hash for name, projection in authority.consumer_projections.items()}
    if hashes != request.consumer_projection_hashes:
        raise ValueError("request projection hashes do not match authority payload")
    if authority.fact_review_output.snapshot_id != request.fact_review_snapshot_id:
        raise ValueError("request FactReview snapshot does not match authority payload")
    recomputed_consistency = evaluate_state_transition_consistency(
        review=request.review,
        accepted_output_reference=authority.accepted_output_reference,
        accepted_output=authority.accepted_output,
    )
    if recomputed_consistency != authority.transition_consistency:
        raise ValueError("authority transition consistency does not match accepted output/review")
    if authority.transition_review_hash != recomputed_consistency.transition_review_hash:
        raise ValueError("request transition review does not match authority payload")
    return authority


def _date_value(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc
    raise ValueError(f"{field} must be an ISO date")


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized
