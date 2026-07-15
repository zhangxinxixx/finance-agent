"""Reviewed transition candidates and deterministic AnalysisState materialization."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.repository import advance_canonical_head, append_analysis_state
from apps.analysis.state.schemas import (
    AnalysisStateDocument,
    AnalysisTransitionDocument,
    StateChange,
    StateMaterializationAuthority,
    TransitionAction,
)
from database.models.analysis_state import AnalysisState


TRANSITION_CANDIDATE_SCHEMA_VERSION = "analysis_transition_candidate.v1"
_PATCHABLE_FIELDS = frozenset(
    {
        "as_of",
        "market_stage",
        "core_thesis",
        "net_bias",
        "dominant_drivers",
        "key_levels",
        "scenario_states",
        "unresolved_items",
        "invalidation_conditions",
        "evidence_cursors",
        "input_snapshot_ids",
        "source_refs",
    }
)


class TransitionReviewError(ValueError):
    """Transition candidate contradicts lineage, patch, or available evidence."""


class TransitionCandidate(BaseModel):
    """The only structure accepted from a coordinator model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_transition_candidate.v1"] = (
        TRANSITION_CANDIDATE_SCHEMA_VERSION
    )
    previous_state_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    changes: list[StateChange] = Field(min_length=1)
    state_patch: dict[str, Any] = Field(default_factory=dict)
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
            change.target for change in self.changes if change.target not in _PATCHABLE_FIELDS
        )
        if unknown_targets:
            raise ValueError(f"changes contain non-patchable targets: {unknown_targets}")
        unknown = sorted(set(self.state_patch) - _PATCHABLE_FIELDS)
        if unknown:
            raise ValueError(f"state_patch contains non-patchable fields: {unknown}")
        change_targets = {change.target for change in self.changes}
        unreviewed = sorted(set(self.state_patch) - change_targets)
        if unreviewed:
            raise ValueError(f"state_patch fields lack matching changes: {unreviewed}")
        missing = sorted(
            change.target
            for change in self.changes
            if change.action
            not in {TransitionAction.MAINTAIN, TransitionAction.PENDING}
            and change.target not in self.state_patch
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
    transition: AnalysisTransitionDocument
    next_state: AnalysisStateDocument
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
    previous_state: AnalysisStateDocument | dict[str, Any],
    available_evidence_refs: list[dict[str, Any]],
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
        if isinstance(previous_state, AnalysisStateDocument)
        else previous_state
    )
    previous = AnalysisStateDocument.model_validate(previous_payload)
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
    next_payload.update(validated.state_patch)
    next_state = AnalysisStateDocument.model_validate(next_payload)
    if next_state.asset != previous.asset:
        raise TransitionReviewError("materializer cannot change the state asset")
    if next_state.as_of <= previous.as_of:
        raise TransitionReviewError("next state as_of must advance beyond previous state")
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


def materialize_reviewed_transition(
    session: Session,
    *,
    review: TransitionReviewResult,
    quality_gate: QualityGateDecision | dict[str, Any],
    agent_loop: AgentLoopDecision | dict[str, Any],
    task_run_id: str,
    expected_head_version: int,
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
    if gate.action is not QualityGateAction.PASS and loop.accepted_output.source != "none":
        raise PermissionError("non-PASS QualityGate action cannot carry accepted_output")
    if gate.action is QualityGateAction.RETRY:
        return _observe_only_result("retry", gate=gate, loop=loop)
    if gate.action is QualityGateAction.FALLBACK:
        return _observe_only_result("fallback", gate=gate, loop=loop)
    if gate.action is QualityGateAction.BLOCK_PUBLISH:
        return _observe_only_result("blocked", gate=gate, loop=loop)

    if gate.action is QualityGateAction.MANUAL_REVIEW:
        _require_review_lineage(session, review)
        authority = StateMaterializationAuthority(
            quality_gate_action=gate.action.value,
            publish_allowed=False,
        )
        state = append_analysis_state(
            session,
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
    _require_review_lineage(session, review)
    authority = StateMaterializationAuthority(
        quality_gate_action=gate.action.value,
        publish_allowed=True,
        accepted_output_source=accepted.source,
        accepted_output_agent_name=accepted.agent_name,
        accepted_output_snapshot_id=accepted.snapshot_id,
    )
    state = append_analysis_state(
        session,
        document=review.next_state,
        transition=review.transition,
        authority=authority,
        previous_state_id=review.previous_state_id,
        task_run_id=task_run_id,
        analysis_snapshot_db_id=analysis_snapshot_db_id,
        final_analysis_result_id=final_analysis_result_id,
    )
    head = advance_canonical_head(
        session,
        asset=review.next_state.asset,
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


def _require_review_lineage(session: Session, review: TransitionReviewResult) -> None:
    previous = session.get(AnalysisState, review.previous_state_id)
    if previous is None:
        raise TransitionReviewError("review previous state does not exist")
    if previous.content_hash != review.previous_state_content_hash:
        raise TransitionReviewError("review previous state content does not match persisted state")
