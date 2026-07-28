"""Reviewed transition candidates and deterministic AnalysisState materialization."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AcceptedOutputReference, AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.analysis.agents.schemas import AcceptedStateConclusion, AgentBias, AgentOutput
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.repository import (
    advance_canonical_head_scoped,
    append_analysis_state_scoped,
)
from apps.analysis.state.schemas import (
    AnalysisStateDocumentV1,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocument,
    AnalysisTransitionDocumentV11,
    StateChange,
    StateMaterializationAuthority,
    StateScope,
    ANALYSIS_STATE_MACHINE_VERSION,
    TransitionAction,
    VersionedAnalysisStateDocument,
    VersionedAnalysisTransitionDocument,
    parse_analysis_state_document,
)
from database.models.analysis_state import AnalysisState


TRANSITION_CANDIDATE_SCHEMA_VERSION = "analysis_transition_candidate.v2"
_ANALYTICAL_FIELDS = frozenset(
    {
        "market_stage",
        "core_thesis",
        "net_bias",
        "dominant_drivers",
        "key_levels",
        "scenario_states",
        "unresolved_items",
        "invalidation_conditions",
    }
)


class TransitionReviewError(ValueError):
    """Transition candidate contradicts lineage, patch, or available evidence."""


class AnalyticalStatePatch(BaseModel):
    """The complete state surface an untrusted transition model may change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market_stage: str | None = None
    core_thesis: str | None = None
    net_bias: str | None = None
    dominant_drivers: list[dict[str, Any]] | None = None
    key_levels: list[dict[str, Any]] | None = None
    scenario_states: list[dict[str, Any]] | None = None
    unresolved_items: list[dict[str, Any]] | None = None
    invalidation_conditions: list[dict[str, Any]] | None = None

    def explicit_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude_none=True)


class SystemStateMetadataPatch(BaseModel):
    """Trusted metadata derived from the immutable Bundle, never from the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    evidence_cursors: dict[str, Any]
    input_snapshot_ids: dict[str, str]
    source_refs: list[dict[str, Any]]
    state_scope: StateScope
    state_machine_version: str = Field(min_length=1)
    session: str = Field(min_length=1)
    trade_date: date


class StateTransitionConsistencyDecision(BaseModel):
    """Deterministic comparison between reviewed state and accepted conclusion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal[
        "consistent", "partially_consistent", "conflicting", "unverifiable"
    ]
    accepted_output_source: Literal["primary", "corrective_fallback", "none"]
    accepted_output_agent_name: str | None = None
    accepted_output_snapshot_id: str | None = None
    accepted_output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    transition_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matching_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    unverifiable_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_decision(self) -> "StateTransitionConsistencyDecision":
        fields = {
            *self.matching_fields,
            *self.conflicting_fields,
            *self.unverifiable_fields,
        }
        expected = {"net_bias", "market_stage", "core_thesis", "dominant_drivers"}
        if fields != expected:
            raise ValueError("consistency decision must account for all required fields")
        if self.accepted_output_source == "none":
            if any(
                (
                    self.accepted_output_agent_name,
                    self.accepted_output_snapshot_id,
                    self.accepted_output_hash,
                )
            ):
                raise ValueError("accepted output source='none' cannot carry output identity")
        elif not all(
            (
                self.accepted_output_agent_name,
                self.accepted_output_snapshot_id,
                self.accepted_output_hash,
            )
        ):
            raise ValueError("accepted output requires complete immutable identity")
        return self


class ManualReviewMaterializationAuthority(BaseModel):
    """Permission-gated human authority bound to one persisted candidate review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority_type: Literal["manual_review"] = "manual_review"
    candidate_state_id: str = Field(min_length=1)
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_state_id: str = Field(min_length=1)
    state_scope: StateScope
    expected_head_version: int = Field(ge=0)
    review_artifact_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    materialization_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_authority_hash(self) -> "ManualReviewMaterializationAuthority":
        if self.authority_hash != _manual_review_authority_hash(self):
            raise ValueError("manual review authority_hash does not match authority payload")
        return self

    @classmethod
    def build(
        cls,
        *,
        candidate_state_id: str,
        candidate_content_hash: str,
        previous_state_id: str,
        state_scope: StateScope,
        expected_head_version: int,
        review_artifact_id: str,
        request_id: str,
        actor: str,
        reason: str,
        review: "TransitionReviewResult",
    ) -> "ManualReviewMaterializationAuthority":
        payload = {
            "authority_type": "manual_review",
            "candidate_state_id": candidate_state_id,
            "candidate_content_hash": candidate_content_hash,
            "previous_state_id": previous_state_id,
            "state_scope": state_scope,
            "expected_head_version": expected_head_version,
            "review_artifact_id": review_artifact_id,
            "request_id": request_id,
            "actor": actor,
            "reason": reason,
            "materialization_review_hash": _review_identity_hash(review),
        }
        return cls(authority_hash=_manual_review_authority_hash(payload), **payload)


class TransitionCandidate(BaseModel):
    """The only structure accepted from a coordinator model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_transition_candidate.v2"] = (
        TRANSITION_CANDIDATE_SCHEMA_VERSION
    )
    previous_state_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    changes: list[StateChange] = Field(min_length=1)
    state_patch: AnalyticalStatePatch = Field(default_factory=AnalyticalStatePatch)
    evidence_refs: list[dict[str, Any]] = Field(min_length=1)

    @field_validator("previous_state_id", "summary")
    @classmethod
    def _strip_text(cls, value: str, info: Any) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{info.field_name} must not be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_patch_shape(self) -> "TransitionCandidate":
        targets = [change.target for change in self.changes]
        if len(set(targets)) != len(targets):
            raise ValueError("changes must not repeat a state target")
        unknown_targets = sorted(
            change.target for change in self.changes if change.target not in _ANALYTICAL_FIELDS
        )
        if unknown_targets:
            raise ValueError(f"changes contain non-patchable targets: {unknown_targets}")
        patch = self.state_patch.explicit_payload()
        change_targets = {change.target for change in self.changes}
        unreviewed = sorted(set(patch) - change_targets)
        if unreviewed:
            raise ValueError(f"state_patch fields lack matching changes: {unreviewed}")
        missing = sorted(
            change.target
            for change in self.changes
            if change.action
            not in {TransitionAction.MAINTAIN, TransitionAction.PENDING}
            and change.target not in patch
        )
        if missing:
            raise ValueError(f"state changes lack deterministic patch values: {missing}")
        return self


class TransitionReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted"] = "accepted"
    previous_state_id: str
    previous_state_content_hash: str
    next_state_content_hash: str
    transition_content_hash: str
    transition: VersionedAnalysisTransitionDocument
    next_state: VersionedAnalysisStateDocument
    reviewed_evidence_refs: list[dict[str, Any]]

    @model_validator(mode="after")
    def _validate_review_hashes(self) -> "TransitionReviewResult":
        if self.next_state_content_hash != content_hash(self.next_state):
            raise ValueError("next_state changed after review")
        if self.transition_content_hash != content_hash(self.transition):
            raise ValueError("transition changed after review")
        return self


class StateMaterializationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal[
        "canonical_accepted",
        "manual_review_candidate",
        "retry",
        "fallback",
        "blocked",
    ]
    state_id: str | None = None
    canonical_state_id: str | None = None
    canonical_version: int | None = None
    canonical_advanced: bool = False
    review_evidence: dict[str, Any] = Field(default_factory=dict)


def review_transition_candidate(
    *,
    candidate: TransitionCandidate | dict[str, Any],
    previous_state_id: str,
    previous_state: VersionedAnalysisStateDocument | dict[str, Any],
    available_evidence_refs: list[dict[str, Any]],
    system_metadata: SystemStateMetadataPatch,
) -> TransitionReviewResult:
    """FactReview a candidate and deterministically apply its explicit patch."""

    candidate_payload = (
        candidate.model_dump(mode="json")
        if isinstance(candidate, TransitionCandidate)
        else candidate
    )
    validated = TransitionCandidate.model_validate(candidate_payload)
    previous_payload = (
        previous_state.model_dump(mode="json")
        if isinstance(previous_state, BaseModel)
        else previous_state
    )
    previous = parse_analysis_state_document(previous_payload)
    if validated.previous_state_id != previous_state_id:
        raise TransitionReviewError("candidate previous_state_id does not match canonical state")

    available = {_reference_key(item) for item in available_evidence_refs}
    candidate_refs = [
        *validated.evidence_refs,
        *(ref for change in validated.changes for ref in change.evidence_refs),
    ]
    if any(not change.evidence_refs for change in validated.changes):
        raise TransitionReviewError("every state change requires evidence_refs")
    missing_refs = [ref for ref in candidate_refs if _reference_key(ref) not in available]
    if missing_refs:
        raise TransitionReviewError("transition references evidence outside the reviewed bundle")

    next_payload = previous.model_dump(mode="python")
    next_payload.update(validated.state_patch.explicit_payload())
    next_payload.update(_legacy_system_metadata_payload(system_metadata))
    next_state = parse_analysis_state_document(next_payload)
    if next_state.asset != previous.asset:
        raise TransitionReviewError("materializer cannot change the state asset")
    if _document_scope(next_state) != _document_scope(previous):
        raise TransitionReviewError("materializer cannot change state_scope")
    if next_state.as_of <= previous.as_of:
        raise TransitionReviewError("next state as_of must advance beyond previous state")
    transition: VersionedAnalysisTransitionDocument
    if isinstance(previous, AnalysisStateDocumentV11):
        transition = AnalysisTransitionDocumentV11(
            state_scope=previous.state_scope,
            summary=validated.summary,
            changes=validated.changes,
            evidence_refs=validated.evidence_refs,
        )
    else:
        transition = AnalysisTransitionDocument(
            summary=validated.summary,
            changes=validated.changes,
            evidence_refs=validated.evidence_refs,
        )
    return TransitionReviewResult(
        previous_state_id=previous_state_id,
        previous_state_content_hash=content_hash(previous),
        next_state_content_hash=content_hash(next_state),
        transition_content_hash=content_hash(transition),
        transition=transition,
        next_state=next_state,
        reviewed_evidence_refs=list(validated.evidence_refs),
    )


def review_transition_candidate_scoped(
    *,
    candidate: TransitionCandidate | dict[str, Any],
    previous_state_id: str,
    previous_state: VersionedAnalysisStateDocument | dict[str, Any],
    available_evidence_refs: list[dict[str, Any]],
    state_scope: StateScope,
    state_machine_version: str,
    session: str,
    trade_date: date,
    system_metadata: SystemStateMetadataPatch,
) -> TransitionReviewResult:
    """Review into v1.1, explicitly upgrading a legacy v1 predecessor if needed."""

    validated = TransitionCandidate.model_validate(
        candidate.model_dump(mode="json")
        if isinstance(candidate, TransitionCandidate)
        else candidate
    )
    previous = parse_analysis_state_document(
        previous_state.model_dump(mode="json")
        if isinstance(previous_state, BaseModel)
        else previous_state
    )
    if validated.previous_state_id != previous_state_id:
        raise TransitionReviewError("candidate previous_state_id does not match canonical state")
    _validate_candidate_evidence(
        validated=validated,
        available_evidence_refs=available_evidence_refs,
    )
    if isinstance(previous, AnalysisStateDocumentV11):
        if previous.state_scope != state_scope:
            raise TransitionReviewError("previous state belongs to a different state scope")
        base_payload = previous.model_dump(mode="python")
    else:
        base_payload = _upgrade_v1_state_payload(
            previous,
            state_scope=state_scope,
            state_machine_version=state_machine_version,
            session=session,
            trade_date=trade_date,
        )
    _validate_scoped_system_metadata(
        system_metadata,
        state_scope=state_scope,
        state_machine_version=state_machine_version,
        session=session,
        trade_date=trade_date,
    )
    base_payload.update(validated.state_patch.explicit_payload())
    base_payload.update(system_metadata.model_dump(mode="python"))
    next_state = AnalysisStateDocumentV11.model_validate(base_payload)
    if next_state.state_scope != state_scope:
        raise TransitionReviewError("materializer cannot change state_scope")
    if next_state.as_of <= previous.as_of:
        raise TransitionReviewError("next state as_of must advance beyond previous state")
    transition = AnalysisTransitionDocumentV11(
        state_scope=state_scope,
        summary=validated.summary,
        changes=validated.changes,
        evidence_refs=validated.evidence_refs,
    )
    return TransitionReviewResult(
        previous_state_id=previous_state_id,
        previous_state_content_hash=content_hash(previous),
        next_state_content_hash=content_hash(next_state),
        transition_content_hash=content_hash(transition),
        transition=transition,
        next_state=next_state,
        reviewed_evidence_refs=list(validated.evidence_refs),
    )


def materialize_reviewed_transition_scoped(
    session: Session,
    *,
    state_scope: StateScope,
    review: TransitionReviewResult,
    quality_gate: QualityGateDecision | dict[str, Any],
    agent_loop: AgentLoopDecision | dict[str, Any],
    task_run_id: str,
    expected_head_version: int,
    transition_consistency: StateTransitionConsistencyDecision | None = None,
    manual_review_authority: ManualReviewMaterializationAuthority | None = None,
    analysis_snapshot_db_id: str | None = None,
    final_analysis_result_id: str | None = None,
) -> StateMaterializationResult:
    """Apply the existing gate/accepted-output authority without inventing another one."""

    review = TransitionReviewResult.model_validate(review.model_dump(mode="json"))
    gate = QualityGateDecision.model_validate(
        quality_gate.model_dump(mode="json")
        if isinstance(quality_gate, QualityGateDecision)
        else quality_gate
    )
    loop = AgentLoopDecision.model_validate(
        agent_loop.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(agent_loop, AgentLoopDecision)
        else agent_loop
    )
    consistency = (
        StateTransitionConsistencyDecision.model_validate(
            transition_consistency.model_dump(mode="json")
        )
        if transition_consistency is not None
        else None
    )
    if consistency is not None and consistency.transition_review_hash != _review_identity_hash(review):
        raise PermissionError("transition consistency does not match reviewed transition")
    manual_authority = (
        ManualReviewMaterializationAuthority.model_validate(
            manual_review_authority.model_dump(mode="json")
        )
        if manual_review_authority is not None
        else None
    )
    if consistency is not None and manual_authority is not None:
        raise PermissionError("materialization accepts exactly one authority type")
    if gate.action is not QualityGateAction.PASS and loop.accepted_output.source != "none":
        raise PermissionError("non-PASS QualityGate action cannot carry accepted_output")
    if gate.action is QualityGateAction.RETRY:
        return _observe_only_result("retry", gate=gate, loop=loop)
    if gate.action is QualityGateAction.FALLBACK:
        return _observe_only_result("fallback", gate=gate, loop=loop)
    if gate.action is QualityGateAction.BLOCK_PUBLISH:
        return _observe_only_result("blocked", gate=gate, loop=loop)
    if not isinstance(review.next_state, AnalysisStateDocumentV11) or not isinstance(
        review.transition, AnalysisTransitionDocumentV11
    ):
        raise TransitionReviewError("scoped materialization requires a v1.1 review")

    if gate.action is QualityGateAction.MANUAL_REVIEW:
        _require_review_lineage(session, review)
        authority = StateMaterializationAuthority(
            quality_gate_action=gate.action.value,
            publish_allowed=False,
        )
        if _document_scope(review.next_state) != state_scope:
            raise TransitionReviewError("review state_scope does not match materialization scope")
        state = append_analysis_state_scoped(
            session,
            state_scope=state_scope,
            document=review.next_state,
            transition=review.transition,
            authority=authority,
            previous_state_id=review.previous_state_id,
            task_run_id=task_run_id,
            analysis_snapshot_db_id=analysis_snapshot_db_id,
            final_analysis_result_id=final_analysis_result_id,
        )
        return StateMaterializationResult(
            disposition="manual_review_candidate",
            state_id=state.id,
            canonical_advanced=False,
            review_evidence=_review_evidence(gate=gate, loop=loop),
        )

    if gate.action is not QualityGateAction.PASS:  # pragma: no cover - enum exhaustiveness
        raise ValueError(f"unsupported QualityGate action: {gate.action}")
    accepted = loop.accepted_output
    if not gate.publish_allowed or not loop.publish_allowed or accepted.source == "none":
        raise PermissionError("QualityGate PASS requires authoritative AgentLoop accepted_output")
    if manual_authority is not None:
        _validate_manual_review_authority(
            session,
            review=review,
            authority=manual_authority,
            state_scope=state_scope,
            expected_head_version=expected_head_version,
        )
    else:
        if consistency is None or consistency.status != "consistent":
            raise PermissionError("canonical materialization requires explicit accepted-conclusion authority")
        if (
            consistency.accepted_output_source != accepted.source
            or consistency.accepted_output_agent_name != accepted.agent_name
            or consistency.accepted_output_snapshot_id != accepted.snapshot_id
        ):
            raise PermissionError("transition consistency accepted output identity does not match AgentLoop")
    _require_review_lineage(session, review)
    authority = StateMaterializationAuthority(
        quality_gate_action=gate.action.value,
        publish_allowed=True,
        accepted_output_source=accepted.source,
        accepted_output_agent_name=accepted.agent_name,
        accepted_output_snapshot_id=accepted.snapshot_id,
    )
    if _document_scope(review.next_state) != state_scope:
        raise TransitionReviewError("review state_scope does not match materialization scope")
    state = append_analysis_state_scoped(
        session,
        state_scope=state_scope,
        document=review.next_state,
        transition=review.transition,
        authority=authority,
        previous_state_id=review.previous_state_id,
        task_run_id=task_run_id,
        analysis_snapshot_db_id=analysis_snapshot_db_id,
        final_analysis_result_id=final_analysis_result_id,
    )
    head = advance_canonical_head_scoped(
        session,
        asset=review.next_state.asset,
        state_scope=state_scope,
        new_state_id=state.id,
        expected_state_id=review.previous_state_id,
        expected_version=expected_head_version,
        authority=authority,
    )
    return StateMaterializationResult(
        disposition="canonical_accepted",
        state_id=state.id,
        canonical_state_id=head.canonical_state_id,
        canonical_version=head.version,
        canonical_advanced=True,
        review_evidence=_review_evidence(gate=gate, loop=loop),
    )


def materialize_reviewed_transition(
    session: Session,
    *,
    review: TransitionReviewResult,
    quality_gate: QualityGateDecision | dict[str, Any],
    agent_loop: AgentLoopDecision | dict[str, Any],
    task_run_id: str,
    expected_head_version: int,
    transition_consistency: StateTransitionConsistencyDecision | None = None,
    manual_review_authority: ManualReviewMaterializationAuthority | None = None,
    analysis_snapshot_db_id: str | None = None,
    final_analysis_result_id: str | None = None,
) -> StateMaterializationResult:
    """Legacy boundary upgrading v1 review output before scoped persistence."""

    gate = QualityGateDecision.model_validate(
        quality_gate.model_dump(mode="json")
        if isinstance(quality_gate, QualityGateDecision)
        else quality_gate
    )
    scoped_review = (
        review
        if gate.action
        in {QualityGateAction.RETRY, QualityGateAction.FALLBACK, QualityGateAction.BLOCK_PUBLISH}
        else _upgrade_legacy_review(review)
    )
    scoped_consistency = transition_consistency
    scoped_manual_authority = manual_review_authority
    if transition_consistency is not None and scoped_review is not review:
        validated_review = TransitionReviewResult.model_validate(
            review.model_dump(mode="json")
        )
        if transition_consistency.transition_review_hash != _review_identity_hash(
            validated_review
        ):
            raise PermissionError("transition consistency does not match reviewed transition")
        scoped_consistency = transition_consistency.model_copy(
            update={"transition_review_hash": _review_identity_hash(scoped_review)}
        )
    if manual_review_authority is not None and scoped_review is not review:
        validated_review = TransitionReviewResult.model_validate(
            review.model_dump(mode="json")
        )
        _validate_manual_review_authority(
            session,
            review=validated_review,
            authority=manual_review_authority,
            state_scope=_document_scope(validated_review.next_state),
            expected_head_version=expected_head_version,
        )
        manual_payload = manual_review_authority.model_dump(mode="json")
        manual_payload["materialization_review_hash"] = _review_identity_hash(
            scoped_review
        )
        manual_payload["authority_hash"] = _manual_review_authority_hash(manual_payload)
        scoped_manual_authority = ManualReviewMaterializationAuthority.model_validate(
            manual_payload
        )
    return materialize_reviewed_transition_scoped(
        session,
        state_scope=_document_scope(scoped_review.next_state),
        review=scoped_review,
        quality_gate=quality_gate,
        agent_loop=agent_loop,
        task_run_id=task_run_id,
        expected_head_version=expected_head_version,
        transition_consistency=scoped_consistency,
        manual_review_authority=scoped_manual_authority,
        analysis_snapshot_db_id=analysis_snapshot_db_id,
        final_analysis_result_id=final_analysis_result_id,
    )


def _upgrade_legacy_review(review: TransitionReviewResult) -> TransitionReviewResult:
    validated = TransitionReviewResult.model_validate(review.model_dump(mode="json"))
    if isinstance(validated.next_state, AnalysisStateDocumentV11):
        return validated
    next_state = AnalysisStateDocumentV11.model_validate(
        _upgrade_v1_state_payload(
            validated.next_state,
            state_scope="daily_close",
            state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
            session="daily_close",
            trade_date=validated.next_state.as_of.date(),
        )
    )
    transition = AnalysisTransitionDocumentV11(
        state_scope="daily_close",
        summary=validated.transition.summary,
        changes=validated.transition.changes,
        evidence_refs=validated.transition.evidence_refs,
    )
    return TransitionReviewResult(
        previous_state_id=validated.previous_state_id,
        previous_state_content_hash=validated.previous_state_content_hash,
        next_state_content_hash=content_hash(next_state),
        transition_content_hash=content_hash(transition),
        transition=transition,
        next_state=next_state,
        reviewed_evidence_refs=validated.reviewed_evidence_refs,
    )


def _observe_only_result(
    disposition: Literal["retry", "fallback", "blocked"],
    *,
    gate: QualityGateDecision,
    loop: AgentLoopDecision,
) -> StateMaterializationResult:
    return StateMaterializationResult(
        disposition=disposition,
        review_evidence=_review_evidence(gate=gate, loop=loop),
    )


def _review_evidence(
    *, gate: QualityGateDecision, loop: AgentLoopDecision
) -> dict[str, Any]:
    return {
        "quality_gate": gate.model_dump(mode="json"),
        "agent_loop": loop.model_dump(mode="json", exclude_none=True),
    }


def _reference_key(value: dict[str, Any]) -> str:
    if not isinstance(value, dict) or not value:
        raise TransitionReviewError("evidence_refs must contain non-empty objects")
    return content_hash(value, exclude_keys=frozenset())


def evaluate_state_transition_consistency(
    *,
    review: TransitionReviewResult,
    accepted_output_reference: AcceptedOutputReference,
    accepted_output: AgentOutput | None,
) -> StateTransitionConsistencyDecision:
    """Compare only explicit typed fields; never infer semantics from keywords."""

    review = TransitionReviewResult.model_validate(review.model_dump(mode="json"))
    reference = AcceptedOutputReference.model_validate(accepted_output_reference)
    required = ("net_bias", "market_stage", "core_thesis", "dominant_drivers")
    review_hash = _review_identity_hash(review)
    if reference.source == "none" or accepted_output is None:
        return StateTransitionConsistencyDecision(
            status="unverifiable",
            accepted_output_source="none",
            transition_review_hash=review_hash,
            unverifiable_fields=list(required),
        )
    output = AgentOutput.model_validate(accepted_output.model_dump(mode="json"))
    if output.agent_name != reference.agent_name or output.snapshot_id != reference.snapshot_id:
        raise ValueError("accepted output does not match AgentLoop identity")
    conclusion = _accepted_state_conclusion(output)
    accepted_values: dict[str, Any | None] = {
        "net_bias": conclusion.state_bias if conclusion is not None else None,
        "market_stage": conclusion.market_stage if conclusion is not None else None,
        "core_thesis": conclusion.core_thesis if conclusion is not None else None,
        "dominant_drivers": conclusion.dominant_drivers if conclusion is not None else None,
    }
    next_values = {
        "net_bias": review.next_state.net_bias,
        "market_stage": review.next_state.market_stage,
        "core_thesis": review.next_state.core_thesis,
        "dominant_drivers": [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in review.next_state.dominant_drivers
        ],
    }
    unverifiable = [field for field in required if accepted_values[field] is None]
    matching = [
        field
        for field in required
        if accepted_values[field] is not None
        and _normalized_consistency_value(next_values[field])
        == _normalized_consistency_value(accepted_values[field])
    ]
    conflicting = [
        field
        for field in required
        if accepted_values[field] is not None and field not in matching
    ]
    if unverifiable:
        status = "unverifiable"
    elif not conflicting:
        status = "consistent"
    elif any(field in conflicting for field in ("net_bias", "market_stage")):
        status = "conflicting"
    else:
        status = "partially_consistent"
    return StateTransitionConsistencyDecision(
        status=status,
        accepted_output_source=reference.source,
        accepted_output_agent_name=output.agent_name,
        accepted_output_snapshot_id=output.snapshot_id,
        accepted_output_hash=content_hash(
            output.model_dump(mode="json", exclude_computed_fields=True),
            exclude_keys=frozenset(),
        ),
        transition_review_hash=review_hash,
        matching_fields=matching,
        conflicting_fields=conflicting,
        unverifiable_fields=unverifiable,
    )


def _accepted_state_conclusion(output: AgentOutput) -> AcceptedStateConclusion | None:
    conclusion = output.accepted_state_conclusion
    if conclusion is None:
        return None
    if output.bias is AgentBias.UNAVAILABLE or conclusion.direction is not output.bias:
        raise ValueError("typed accepted conclusion direction contradicts AgentOutput.bias")
    return conclusion


def _normalized_consistency_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _legacy_system_metadata_payload(metadata: SystemStateMetadataPatch) -> dict[str, Any]:
    return {
        "as_of": metadata.as_of,
        "evidence_cursors": metadata.evidence_cursors,
        "input_snapshot_ids": metadata.input_snapshot_ids,
        "source_refs": metadata.source_refs,
    }


def _review_identity_hash(review: TransitionReviewResult) -> str:
    return content_hash(
        review.model_dump(mode="json", exclude_computed_fields=True),
        exclude_keys=frozenset(),
    )


def _manual_review_authority_hash(
    value: ManualReviewMaterializationAuthority | dict[str, Any],
) -> str:
    payload = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else dict(value)
    )
    payload.pop("authority_hash", None)
    return content_hash(payload, exclude_keys=frozenset())


def _validate_manual_review_authority(
    session: Session,
    *,
    review: TransitionReviewResult,
    authority: ManualReviewMaterializationAuthority,
    state_scope: StateScope,
    expected_head_version: int,
) -> None:
    if authority.materialization_review_hash != _review_identity_hash(review):
        raise PermissionError("manual review authority does not match reviewed transition")
    if (
        authority.previous_state_id != review.previous_state_id
        or authority.state_scope != state_scope
        or authority.expected_head_version != expected_head_version
    ):
        raise PermissionError("manual review authority does not match materialization identity")
    candidate = session.get(AnalysisState, authority.candidate_state_id)
    if candidate is None:
        raise PermissionError("manual review authority candidate does not exist")
    if (
        candidate.content_hash != authority.candidate_content_hash
        or candidate.previous_state_id != review.previous_state_id
        or candidate.state_scope != state_scope
        or candidate.publish_allowed
        or candidate.quality_gate_action != "manual_review"
    ):
        raise PermissionError("manual review authority candidate binding is invalid")
    if review.next_state_content_hash != candidate.content_hash:
        candidate_document = parse_analysis_state_document(candidate.payload)
        if not (
            isinstance(candidate_document, AnalysisStateDocumentV1)
            and isinstance(review.next_state, AnalysisStateDocumentV11)
        ):
            raise PermissionError("manual review authority next state does not match candidate")
        upgraded_candidate = AnalysisStateDocumentV11.model_validate(
            _upgrade_v1_state_payload(
                candidate_document,
                state_scope=review.next_state.state_scope,
                state_machine_version=review.next_state.state_machine_version,
                session=review.next_state.session,
                trade_date=review.next_state.trade_date,
            )
        )
        if content_hash(upgraded_candidate) != review.next_state_content_hash:
            raise PermissionError("manual review authority candidate upgrade is invalid")
    expected_ref = {
        "artifact_type": "analysis_state_review",
        "candidate_state_id": authority.candidate_state_id,
        "review_artifact_id": authority.review_artifact_id,
        "actor": authority.actor,
        "reason": authority.reason,
        "request_id": authority.request_id,
        "state_scope": authority.state_scope,
    }
    if expected_ref not in review.reviewed_evidence_refs:
        raise PermissionError("manual review authority evidence is absent from review")


def _validate_scoped_system_metadata(
    metadata: SystemStateMetadataPatch,
    *,
    state_scope: StateScope,
    state_machine_version: str,
    session: str,
    trade_date: date,
) -> None:
    expected = (state_scope, state_machine_version, session, trade_date)
    actual = (
        metadata.state_scope,
        metadata.state_machine_version,
        metadata.session,
        metadata.trade_date,
    )
    if actual != expected:
        raise TransitionReviewError("system metadata does not match scoped runtime identity")


def _validate_candidate_evidence(
    *,
    validated: TransitionCandidate,
    available_evidence_refs: list[dict[str, Any]],
) -> None:
    available = {_reference_key(item) for item in available_evidence_refs}
    candidate_refs = [
        *validated.evidence_refs,
        *(ref for change in validated.changes for ref in change.evidence_refs),
    ]
    if any(not change.evidence_refs for change in validated.changes):
        raise TransitionReviewError("every state change requires evidence_refs")
    if any(_reference_key(ref) not in available for ref in candidate_refs):
        raise TransitionReviewError("transition references evidence outside the reviewed bundle")


def _upgrade_v1_state_payload(
    previous: AnalysisStateDocumentV1,
    *,
    state_scope: StateScope,
    state_machine_version: str,
    session: str,
    trade_date: date,
) -> dict[str, Any]:
    """Map v1 state fields to canonical v1.1 shapes without mutating the v1 object."""

    drivers = []
    for index, row in enumerate(previous.dominant_drivers, start=1):
        driver_id = str(row.get("mainline_id") or row.get("name") or row.get("theme") or "").strip()
        if not driver_id:
            raise TransitionReviewError(f"legacy dominant driver {index} has no identity")
        direction = str(row.get("direction") or "unknown").lower()
        if direction not in {"tailwind", "headwind", "neutral", "mixed"}:
            direction = "unknown"
        coverage = str(row.get("coverage_status") or "unknown").lower()
        if coverage not in {"covered", "partial", "missing"}:
            coverage = "unknown"
        drivers.append(
            {
                "driver_id": driver_id,
                "label": str(row.get("theme") or row.get("name") or driver_id),
                "rank": row.get("rank") or index,
                "score": row.get("score"),
                "direction": direction,
                "coverage_status": coverage,
            }
        )
    levels = []
    for index, row in enumerate(previous.key_levels, start=1):
        value = row.get("value", row.get("price", row.get("level")))
        if value is None:
            raise TransitionReviewError(f"legacy key level {index} has no value")
        levels.append(
            {
                "value": value,
                "role": str(row.get("role") or row.get("type") or "legacy_reference"),
                "source": str(row.get("source") or "legacy_v1"),
                "meaning": row.get("meaning"),
            }
        )
    scenarios = []
    for index, row in enumerate(previous.scenario_states, start=1):
        scenario_id = str(row.get("name") or row.get("type") or f"legacy-{index}")
        condition = str(row.get("condition") or row.get("name") or row.get("type") or "").strip()
        if not condition:
            raise TransitionReviewError(f"legacy scenario {index} has no condition")
        status = str(row.get("status") or "pending").lower()
        if status not in {"active", "pending", "confirmed", "invalidated"}:
            status = "pending"
        scenarios.append(
            {"scenario_id": scenario_id, "condition": condition, "status": status}
        )
    return {
        "schema_version": "1.1",
        "state_scope": state_scope,
        "state_machine_version": state_machine_version,
        "session": session,
        "trade_date": trade_date,
        "asset": previous.asset,
        "as_of": previous.as_of,
        "market_stage": previous.market_stage,
        "core_thesis": previous.core_thesis,
        "net_bias": previous.net_bias,
        "dominant_drivers": drivers,
        "key_levels": levels,
        "scenario_states": scenarios,
        "unresolved_items": previous.unresolved_items,
        "invalidation_conditions": previous.invalidation_conditions,
        "evidence_cursors": previous.evidence_cursors,
        "input_snapshot_ids": previous.input_snapshot_ids,
        "source_refs": previous.source_refs,
    }


def _require_review_lineage(session: Session, review: TransitionReviewResult) -> None:
    previous = session.get(AnalysisState, review.previous_state_id)
    if previous is None:
        raise TransitionReviewError("review previous state does not exist")
    if previous.content_hash != review.previous_state_content_hash:
        raise TransitionReviewError("review previous state content does not match persisted state")
    if previous.state_scope != _document_scope(review.next_state):
        raise TransitionReviewError("review previous state belongs to a different state scope")


def _document_scope(document: VersionedAnalysisStateDocument) -> StateScope:
    return getattr(document, "state_scope", "daily_close")
