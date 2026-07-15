"""Pure read projections and explicit candidate-review materialization."""

from __future__ import annotations

import math
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AgentLoopDecision, AcceptedOutputReference
from apps.analysis.agents.quality_gate_evaluator import (
    QualityGateAction,
    QualityGateDecision,
    QualityGateFinding,
)
from apps.analysis.state import AnalysisStateDocument, TransitionReviewResult, materialize_reviewed_transition
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.repository import (
    CanonicalHeadConflictError,
    StateLineageError,
    get_state_history,
)
from apps.analysis.state.schemas import AnalysisTransitionDocument
from apps.api.schemas.analysis_memory import (
    AnalysisStateLineage,
    AnalysisStateView,
    AnalysisTransitionView,
    CandidateReviewRequest,
    CandidateReviewResponse,
    CandidateStatePage,
    CanonicalStateResponse,
    ContextBlockMetadata,
    ContextBundleMetadata,
    ContextBundleMetadataPage,
    PaginationMeta,
    ReviewArtifactView,
)
from apps.api.services._storage import _PROJECT_ROOT
from apps.output.context_bundle import ContextBundleLoadError, load_context_bundle
from apps.output.analysis_state_review import review_artifact_id, write_analysis_state_review
from database.models.analysis_state import AnalysisState, AnalysisTransition
from database.queries.analysis_state_observability import (
    get_head,
    get_candidate_acceptance_lineage,
    get_state,
    get_transition,
    get_transition_to_state,
    list_candidate_states_page,
)


class AnalysisMemoryNotFoundError(LookupError):
    pass


class AnalysisMemoryConflictError(RuntimeError):
    pass


class AnalysisMemoryReviewError(ValueError):
    pass


_ASSET_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def get_latest_canonical(
    db: Session,
    *,
    asset: str,
    max_depth: int = 20,
) -> CanonicalStateResponse:
    normalized_asset = _asset(asset)
    head = get_head(db, normalized_asset)
    if head is None:
        raise AnalysisMemoryNotFoundError("canonical state not found")
    canonical = get_state(db, head.canonical_state_id)
    if canonical is None or not _is_accepted(canonical):
        raise AnalysisMemoryConflictError("canonical head does not reference an accepted state")
    try:
        history = get_state_history(db, canonical.id, max_depth=max_depth)
    except StateLineageError as exc:
        raise AnalysisMemoryConflictError("canonical state lineage is invalid") from exc
    return CanonicalStateResponse(
        asset=normalized_asset,
        head_version=head.version,
        state=_state_view(db, canonical, state_kind="accepted_canonical"),
        canonical_chain=[
            _state_view(db, row, state_kind="accepted_canonical")
            for row in history
            if _is_accepted(row)
        ],
    )


def get_state_response(db: Session, *, state_id: str) -> AnalysisStateView:
    state = get_state(db, _required(state_id, "state_id"))
    if state is None:
        raise AnalysisMemoryNotFoundError("analysis state not found")
    head = get_head(db, state.asset)
    is_canonical = head is not None and head.canonical_state_id == state.id
    if is_canonical and not _is_accepted(state):
        raise AnalysisMemoryConflictError("canonical head does not reference an accepted state")
    return _state_view(
        db,
        state,
        state_kind="accepted_canonical" if _is_accepted(state) else _candidate_kind(state),
    )


def list_candidates(
    db: Session,
    *,
    asset: str,
    page: int,
    page_size: int,
) -> CandidateStatePage:
    normalized_asset = _asset(asset)
    rows, total = list_candidate_states_page(
        db,
        asset=normalized_asset,
        page=page,
        page_size=page_size,
    )
    return CandidateStatePage(
        asset=normalized_asset,
        data=[_state_view(db, row, state_kind=_candidate_kind(row)) for row in rows],
        pagination=_pagination(page=page, page_size=page_size, total=total),
    )


def get_transition_response(db: Session, *, transition_id: str) -> AnalysisTransitionView:
    row = get_transition(db, _required(transition_id, "transition_id"))
    if row is None:
        raise AnalysisMemoryNotFoundError("analysis transition not found")
    return _transition_view(row)


def list_context_bundle_metadata(
    *,
    asset: str,
    page: int,
    page_size: int,
    storage_root: Path | None = None,
) -> ContextBundleMetadataPage:
    normalized_asset = _asset(asset)
    rows = _context_bundle_rows(asset=normalized_asset, storage_root=storage_root)
    start = (page - 1) * page_size
    return ContextBundleMetadataPage(
        asset=normalized_asset,
        data=rows[start : start + page_size],
        pagination=_pagination(page=page, page_size=page_size, total=len(rows)),
    )


def get_context_bundle_metadata(
    *,
    bundle_id: str,
    storage_root: Path | None = None,
) -> ContextBundleMetadata:
    normalized_id = _required(bundle_id, "bundle_id")
    try:
        normalized_id = str(UUID(normalized_id))
    except ValueError as exc:
        raise AnalysisMemoryReviewError("bundle_id must be a UUID") from exc
    root = (storage_root or (_PROJECT_ROOT / "storage")).resolve()
    base = root / "outputs" / "context_bundles"
    if not base.is_dir():
        raise AnalysisMemoryNotFoundError("context bundle not found")
    for path in base.glob(f"*/*/{normalized_id}.json"):
        metadata = _load_bundle_metadata(root=root, path=path)
        if metadata is not None and metadata.bundle_id == normalized_id:
            return metadata
    raise AnalysisMemoryNotFoundError("context bundle not found")


def accept_candidate(
    db: Session,
    *,
    candidate_id: str,
    request: CandidateReviewRequest,
) -> CandidateReviewResponse:
    candidate = get_state(db, _required(candidate_id, "candidate_id"))
    if candidate is None:
        raise AnalysisMemoryNotFoundError("analysis candidate not found")
    if candidate.publish_allowed or candidate.quality_gate_action != "manual_review":
        raise AnalysisMemoryReviewError("candidate is not eligible for manual acceptance")
    head = get_head(db, candidate.asset)
    if head is None:
        raise AnalysisMemoryConflictError("canonical head not found")
    if (
        head.canonical_state_id != request.expected_canonical_state_id
        or head.version != request.expected_head_version
        or candidate.previous_state_id != head.canonical_state_id
    ):
        raise AnalysisMemoryConflictError("canonical head changed before candidate review")
    previous = get_state(db, head.canonical_state_id)
    if previous is None or not _is_accepted(previous):
        raise AnalysisMemoryConflictError("canonical head does not reference an accepted state")
    candidate_transition = get_transition_to_state(db, candidate.id)
    if candidate_transition is None:
        raise AnalysisMemoryConflictError("candidate transition is missing")

    acceptance_lineage = get_candidate_acceptance_lineage(db, state=candidate)
    if acceptance_lineage is None:
        raise AnalysisMemoryReviewError(
            "candidate lacks persisted snapshot/final/coordinator acceptance lineage"
        )
    snapshot, final_result, coordinator = acceptance_lineage
    artifact_id = review_artifact_id(
        candidate_state_id=candidate.id,
        request_id=request.request_id,
    )

    review_ref = {
        "artifact_type": "analysis_state_review",
        "candidate_state_id": candidate.id,
        "review_artifact_id": artifact_id,
        "actor": request.actor,
        "reason": request.reason,
        "request_id": request.request_id,
    }
    transition = AnalysisTransitionDocument(
        summary=f"Manual review accepted candidate: {candidate_transition.summary}",
        changes=candidate_transition.actions,
        evidence_refs=[*candidate_transition.evidence_refs, review_ref],
    )
    document = AnalysisStateDocument.model_validate(candidate.payload)
    review = TransitionReviewResult(
        previous_state_id=head.canonical_state_id,
        previous_state_content_hash=previous.content_hash,
        next_state_content_hash=candidate.content_hash,
        transition_content_hash=content_hash(transition),
        transition=transition,
        next_state=document,
        reviewed_evidence_refs=list(transition.evidence_refs),
    )
    quality_gate = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        manual_review_required=False,
        findings=[
            QualityGateFinding(
                code="manual_candidate_review_accepted",
                severity="info",
                message="A permission-gated reviewer accepted the persisted transition candidate.",
                evidence={
                    "candidate_state_id": candidate.id,
                    "review_artifact_id": artifact_id,
                    "request_id": request.request_id,
                },
            )
        ],
        source_ref_count=len(document.source_refs),
    )
    agent_loop = AgentLoopDecision(
        decision="passed",
        review_status="pass",
        publish_allowed=True,
        reasons=["permission_gated_manual_review_accepted"],
        accepted_output=AcceptedOutputReference(
            source="primary",
            agent_name=coordinator.agent_name,
            snapshot_id=coordinator.snapshot_id,
        ),
    )
    try:
        materialization = materialize_reviewed_transition(
            db,
            review=review,
            quality_gate=quality_gate,
            agent_loop=agent_loop,
            task_run_id=candidate.task_run_id,
            expected_head_version=head.version,
            analysis_snapshot_db_id=candidate.analysis_snapshot_db_id,
            final_analysis_result_id=candidate.final_analysis_result_id,
        )
        if (
            materialization.disposition != "canonical_accepted"
            or not materialization.state_id
            or materialization.canonical_version is None
        ):
            raise AnalysisMemoryConflictError("review materializer did not accept the candidate")
        accepted = get_state(db, materialization.state_id)
        if accepted is None:  # pragma: no cover - materializer contract
            raise AnalysisMemoryConflictError("accepted state was not persisted")
        db.flush()
        accepted_transition = get_transition_to_state(db, accepted.id)
        if accepted_transition is None:  # pragma: no cover - append contract
            raise AnalysisMemoryConflictError("accepted transition was not persisted")
        reviewed_at = accepted_transition.created_at or candidate.created_at or candidate.as_of
        artifact = write_analysis_state_review(
            storage_root=_PROJECT_ROOT / "storage",
            payload={
                "schema_version": "analysis_state_review.v1",
                "artifact_id": artifact_id,
                "candidate_state_id": candidate.id,
                "accepted_state_id": accepted.id,
                "transition_id": accepted_transition.id,
                "asset": candidate.asset,
                "run_id": candidate.task_run_id,
                "analysis_snapshot_db_id": snapshot.id,
                "snapshot_id": snapshot.snapshot_id,
                "final_analysis_result_id": final_result.id,
                "accepted_output_agent_name": coordinator.agent_name,
                "accepted_output_snapshot_id": coordinator.snapshot_id,
                "quality_gate": quality_gate.model_dump(mode="json"),
                "agent_loop": agent_loop.model_dump(
                    mode="json",
                    exclude_none=True,
                    exclude_computed_fields=True,
                ),
                "actor": request.actor,
                "reason": request.reason,
                "request_id": request.request_id,
                "reviewed_at": reviewed_at.isoformat(),
            },
        )
        db.commit()
    except (CanonicalHeadConflictError, StateLineageError) as exc:
        db.rollback()
        raise AnalysisMemoryConflictError("canonical head changed before candidate review") from exc
    except (PermissionError, ValueError) as exc:
        db.rollback()
        raise AnalysisMemoryReviewError("candidate review failed contract validation") from exc
    except Exception:
        db.rollback()
        raise

    return CandidateReviewResponse(
        disposition="canonical_accepted",
        canonical_state=_state_view(db, accepted, state_kind="accepted_canonical"),
        head_version=materialization.canonical_version,
        review_artifact=ReviewArtifactView(
            artifact_id=artifact.artifact_id,
            candidate_state_id=candidate.id,
            accepted_state_id=accepted.id,
            transition_id=accepted_transition.id,
            actor=request.actor,
            reason=request.reason,
            request_id=request.request_id,
            artifact_path=artifact.storage_relative_path,
            content_hash=artifact.content_hash,
            sha256=artifact.file_sha256,
            created_at=accepted_transition.created_at,
        ),
    )


def _state_view(
    db: Session,
    state: AnalysisState,
    *,
    state_kind: str,
) -> AnalysisStateView:
    transition = get_transition_to_state(db, state.id)
    artifact_ids = [f"analysis-state:{state.id}"]
    if transition is not None:
        artifact_ids.append(f"analysis-transition:{transition.id}")
    return AnalysisStateView(
        state_id=state.id,
        state_kind=state_kind,
        schema_version=state.schema_version,
        asset=state.asset,
        as_of=state.as_of,
        previous_state_id=state.previous_state_id,
        quality_gate_action=state.quality_gate_action,
        publish_allowed=state.publish_allowed,
        accepted_output_source=state.accepted_output_source,
        accepted_output_agent_name=state.accepted_output_agent_name,
        content_hash=state.content_hash,
        payload=dict(state.payload),
        lineage=AnalysisStateLineage(
            run_id=state.task_run_id,
            analysis_snapshot_db_id=state.analysis_snapshot_db_id,
            final_analysis_result_id=state.final_analysis_result_id,
            accepted_output_snapshot_id=state.accepted_output_snapshot_id,
            input_snapshot_ids=dict(state.input_snapshot_ids or {}),
            source_refs=list(state.source_refs or []),
            artifact_ids=artifact_ids,
        ),
        transition=_transition_view(transition) if transition is not None else None,
        created_at=state.created_at,
    )


def _transition_view(row: AnalysisTransition) -> AnalysisTransitionView:
    return AnalysisTransitionView(
        transition_id=row.id,
        schema_version=row.schema_version,
        asset=row.asset,
        from_state_id=row.from_state_id,
        to_state_id=row.to_state_id,
        run_id=row.task_run_id,
        summary=row.summary,
        changes=list(row.actions or []),
        evidence_refs=list(row.evidence_refs or []),
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


def _context_bundle_rows(*, asset: str, storage_root: Path | None) -> list[ContextBundleMetadata]:
    root = (storage_root or (_PROJECT_ROOT / "storage")).resolve()
    base = root / "outputs" / "context_bundles" / asset
    rows = [
        metadata
        for path in base.glob("*/*.json") if base.is_dir()
        if (metadata := _load_bundle_metadata(root=root, path=path)) is not None
    ]
    return sorted(rows, key=lambda item: (item.assembled_at, item.bundle_id), reverse=True)


def _load_bundle_metadata(*, root: Path, path: Path) -> ContextBundleMetadata | None:
    try:
        relative = path.resolve().relative_to(root).as_posix()
        bundle = load_context_bundle(storage_root=root, storage_relative_path=relative)
    except (OSError, ValueError, ContextBundleLoadError):
        return None
    return ContextBundleMetadata(
        schema_version=bundle.schema_version,
        bundle_id=bundle.bundle_id,
        content_hash=bundle.content_hash,
        asset=bundle.asset,
        run_id=bundle.run_id,
        canonical_state_id=bundle.canonical_state_id,
        cutoff_at=bundle.cutoff_at,
        assembled_at=bundle.assembled_at,
        budget_tokens=bundle.budget_trace.budget_tokens,
        estimated_tokens=bundle.budget_trace.estimated_tokens,
        total_utf8_bytes=bundle.budget_trace.total_utf8_bytes,
        within_budget=bundle.budget_trace.within_budget,
        blocks=[
            ContextBlockMetadata(
                name=block.name,
                utf8_bytes=block.utf8_bytes,
                estimated_tokens=block.estimated_tokens,
                trim_reasons=list(block.trim_reasons),
                retained_evidence_ids=list(block.retained_evidence_ids),
            )
            for block in bundle.blocks
        ],
        freshness=dict(bundle.freshness),
        session=dict(bundle.session),
        alignment=dict(bundle.alignment),
        evidence_cursors={key: value.model_dump(mode="json") for key, value in bundle.evidence_cursors.items()},
        next_evidence_cursors={key: value.model_dump(mode="json") for key, value in bundle.next_evidence_cursors.items()},
        source_refs=list(bundle.source_refs),
        artifact_path=relative,
    )


def _pagination(*, page: int, page_size: int, total: int) -> PaginationMeta:
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


def _is_accepted(state: AnalysisState) -> bool:
    return (
        state.publish_allowed is True
        and state.quality_gate_action == "pass"
        and state.accepted_output_source != "none"
    )


def _candidate_kind(state: AnalysisState) -> str:
    return "candidate" if state.quality_gate_action == "manual_review" else "blocked"


def _asset(value: str) -> str:
    normalized = _required(value, "asset").upper()
    if not _ASSET_RE.fullmatch(normalized):
        raise AnalysisMemoryReviewError("asset has an invalid format")
    return normalized


def _required(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise AnalysisMemoryReviewError(f"{field} must not be blank")
    return normalized
