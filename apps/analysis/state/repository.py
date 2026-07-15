"""Append-only repository and canonical-head CAS for persistent analysis state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.analysis.state.hashing import content_hash
from apps.analysis.state.schemas import (
    AnalysisStateDocument,
    AnalysisTransitionDocument,
    StateMaterializationAuthority,
)
from database.models.analysis import AnalysisSnapshot, FinalAnalysisResult
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


class StateLineageError(ValueError):
    """The proposed state does not follow its declared lineage."""


class CanonicalHeadConflictError(RuntimeError):
    """The canonical head changed after the caller assembled its candidate."""


class StateIdempotencyConflictError(RuntimeError):
    """A stable state identity was reused with different immutable content."""


def append_analysis_state(
    session: Session,
    *,
    document: AnalysisStateDocument,
    transition: AnalysisTransitionDocument,
    authority: StateMaterializationAuthority,
    previous_state_id: str | None,
    task_run_id: str,
    analysis_snapshot_db_id: str | None = None,
    final_analysis_result_id: str | None = None,
    state_id: str | None = None,
) -> AnalysisState:
    """Append an immutable state and transition, idempotently within one run.

    When callers omit ``state_id``, a stable UUID is derived from the complete
    append operation. Replaying the same operation returns the existing row;
    reusing an explicit identity for different content is rejected.
    """

    previous = _validate_previous_state(session, asset=document.asset, previous_state_id=previous_state_id)
    normalized_task_run_id = _required_text(task_run_id, field="task_run_id")
    _validate_output_lineage(
        session,
        document=document,
        authority=authority,
        analysis_snapshot_db_id=analysis_snapshot_db_id,
        final_analysis_result_id=final_analysis_result_id,
    )

    payload = document.model_dump(mode="json")
    transition_payload = transition.model_dump(mode="json")
    operation_payload = {
        "document": payload,
        "transition": transition_payload,
        "authority": authority.model_dump(mode="json"),
        "previous_state_id": previous.id if previous is not None else None,
        "task_run_id": normalized_task_run_id,
        "analysis_snapshot_db_id": analysis_snapshot_db_id,
        "final_analysis_result_id": final_analysis_result_id,
    }
    resolved_state_id = state_id or str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:analysis-state:{content_hash(operation_payload)}")
    )
    if state_id is not None:
        resolved_state_id = _required_text(state_id, field="state_id")

    existing = session.get(AnalysisState, resolved_state_id)
    if existing is not None:
        _require_idempotent_append(
            session,
            existing=existing,
            document=document,
            transition_payload=transition_payload,
            authority=authority,
            previous_state_id=previous.id if previous is not None else None,
            task_run_id=normalized_task_run_id,
            analysis_snapshot_db_id=analysis_snapshot_db_id,
            final_analysis_result_id=final_analysis_result_id,
        )
        return existing

    state_kwargs: dict[str, Any] = {
        "id": resolved_state_id,
        "schema_version": document.schema_version,
        "asset": document.asset,
        "as_of": document.as_of,
        "previous_state_id": previous.id if previous is not None else None,
        "task_run_id": normalized_task_run_id,
        "analysis_snapshot_db_id": analysis_snapshot_db_id,
        "final_analysis_result_id": final_analysis_result_id,
        "quality_gate_action": authority.quality_gate_action,
        "publish_allowed": authority.publish_allowed,
        "accepted_output_source": authority.accepted_output_source,
        "accepted_output_agent_name": authority.accepted_output_agent_name,
        "accepted_output_snapshot_id": authority.accepted_output_snapshot_id,
        "input_snapshot_ids": dict(document.input_snapshot_ids),
        "source_refs": list(document.source_refs),
        "evidence_cursors": dict(document.evidence_cursors),
        "payload": payload,
        "content_hash": content_hash(payload),
    }
    state = AnalysisState(**state_kwargs)
    transition_row = AnalysisTransition(
        schema_version=transition.schema_version,
        asset=document.asset,
        from_state_id=previous.id if previous is not None else None,
        to_state_id=state.id,
        task_run_id=state.task_run_id,
        summary=transition.summary,
        actions=transition_payload["changes"],
        evidence_refs=transition_payload["evidence_refs"],
        content_hash=content_hash(
            {
                "from_state_id": previous.id if previous is not None else None,
                "to_state_id": state.id,
                **transition_payload,
            }
        ),
    )
    try:
        with session.begin_nested():
            session.add_all((state, transition_row))
            session.flush()
    except IntegrityError as exc:
        existing = session.get(AnalysisState, resolved_state_id)
        if existing is None:
            raise
        try:
            _require_idempotent_append(
                session,
                existing=existing,
                document=document,
                transition_payload=transition_payload,
                authority=authority,
                previous_state_id=previous.id if previous is not None else None,
                task_run_id=normalized_task_run_id,
                analysis_snapshot_db_id=analysis_snapshot_db_id,
                final_analysis_result_id=final_analysis_result_id,
            )
        except StateIdempotencyConflictError as conflict:
            raise conflict from exc
        return existing
    return state


def advance_canonical_head(
    session: Session,
    *,
    asset: str,
    new_state_id: str,
    expected_state_id: str | None,
    expected_version: int,
    authority: StateMaterializationAuthority,
) -> AnalysisStateHead:
    """Atomically advance the canonical head when state, version and authority match."""

    normalized_asset = _required_text(asset, field="asset")
    if expected_version < 0:
        raise ValueError("expected_version must be non-negative")

    state = session.get(AnalysisState, new_state_id)
    if state is None:
        raise StateLineageError(f"analysis state not found: {new_state_id}")
    if state.asset != normalized_asset:
        raise StateLineageError("new state belongs to a different asset")
    if state.previous_state_id != expected_state_id:
        raise StateLineageError("new state previous_state_id does not match expected canonical state")
    _require_canonical_authority(state, authority)

    current_head = _get_head(session, normalized_asset)
    if current_head is not None and _is_idempotent_head_retry(
        current_head,
        new_state_id=state.id,
        expected_version=expected_version,
    ):
        return current_head

    if expected_state_id is None:
        if expected_version != 0:
            raise CanonicalHeadConflictError("initial canonical head requires expected_version=0")
        if current_head is not None:
            raise CanonicalHeadConflictError("canonical head already exists")
        head = AnalysisStateHead(asset=normalized_asset, canonical_state_id=state.id, version=1)
        try:
            with session.begin_nested():
                session.add(head)
                session.flush()
        except IntegrityError as exc:
            current_head = _get_head(session, normalized_asset, populate_existing=True)
            if current_head is not None and _is_idempotent_head_retry(
                current_head,
                new_state_id=state.id,
                expected_version=expected_version,
            ):
                return current_head
            raise CanonicalHeadConflictError("canonical head was concurrently initialized") from exc
        return head

    result = session.execute(
        update(AnalysisStateHead)
        .where(
            AnalysisStateHead.asset == normalized_asset,
            AnalysisStateHead.canonical_state_id == expected_state_id,
            AnalysisStateHead.version == expected_version,
        )
        .values(canonical_state_id=state.id, version=expected_version + 1)
    )
    if result.rowcount != 1:
        current_head = _get_head(session, normalized_asset, populate_existing=True)
        if current_head is not None and _is_idempotent_head_retry(
            current_head,
            new_state_id=state.id,
            expected_version=expected_version,
        ):
            return current_head
        raise CanonicalHeadConflictError("canonical head compare-and-swap conflict")
    session.flush()
    head = _get_head(session, normalized_asset, populate_existing=True)
    if head is None:  # pragma: no cover - protected by rowcount and the transaction
        raise CanonicalHeadConflictError("canonical head disappeared after compare-and-swap")
    return head


def get_canonical_state(session: Session, asset: str) -> AnalysisState | None:
    """Return the state referenced by the asset's canonical head."""

    return session.scalar(
        select(AnalysisState)
        .join(AnalysisStateHead, AnalysisStateHead.canonical_state_id == AnalysisState.id)
        .where(AnalysisStateHead.asset == asset)
    )


def list_candidate_states(session: Session, asset: str) -> list[AnalysisState]:
    """Return immutable observe/review candidates without inventing a candidate head."""

    return list(
        session.scalars(
            select(AnalysisState)
            .where(AnalysisState.asset == asset, AnalysisState.publish_allowed.is_(False))
            .order_by(AnalysisState.as_of.desc(), AnalysisState.created_at.desc(), AnalysisState.id.desc())
        )
    )


def get_state_history(session: Session, state_id: str, *, max_depth: int = 100) -> list[AnalysisState]:
    """Traverse ``previous_state_id`` from newest to oldest with cycle protection."""

    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    history: list[AnalysisState] = []
    seen: set[str] = set()
    current_id: str | None = state_id
    while current_id is not None:
        if current_id in seen:
            raise StateLineageError("analysis state lineage contains a cycle")
        if len(history) >= max_depth:
            raise StateLineageError("analysis state lineage exceeds max_depth")
        seen.add(current_id)
        current = session.get(AnalysisState, current_id)
        if current is None:
            raise StateLineageError(f"analysis state not found: {current_id}")
        history.append(current)
        current_id = current.previous_state_id
    return history


def _validate_previous_state(
    session: Session,
    *,
    asset: str,
    previous_state_id: str | None,
) -> AnalysisState | None:
    if previous_state_id is None:
        return None
    previous = session.get(AnalysisState, previous_state_id)
    if previous is None:
        raise StateLineageError(f"previous analysis state not found: {previous_state_id}")
    if previous.asset != asset:
        raise StateLineageError("previous analysis state belongs to a different asset")
    return previous


def _require_idempotent_append(
    session: Session,
    *,
    existing: AnalysisState,
    document: AnalysisStateDocument,
    transition_payload: dict[str, Any],
    authority: StateMaterializationAuthority,
    previous_state_id: str | None,
    task_run_id: str,
    analysis_snapshot_db_id: str | None,
    final_analysis_result_id: str | None,
) -> None:
    payload = document.model_dump(mode="json")
    expected_state = {
        "schema_version": document.schema_version,
        "asset": document.asset,
        "previous_state_id": previous_state_id,
        "task_run_id": task_run_id,
        "analysis_snapshot_db_id": analysis_snapshot_db_id,
        "final_analysis_result_id": final_analysis_result_id,
        "quality_gate_action": authority.quality_gate_action,
        "publish_allowed": authority.publish_allowed,
        "accepted_output_source": authority.accepted_output_source,
        "accepted_output_agent_name": authority.accepted_output_agent_name,
        "accepted_output_snapshot_id": authority.accepted_output_snapshot_id,
        "input_snapshot_ids": dict(document.input_snapshot_ids),
        "source_refs": list(document.source_refs),
        "evidence_cursors": dict(document.evidence_cursors),
        "payload": payload,
        "content_hash": content_hash(payload),
    }
    actual_state = {field: getattr(existing, field) for field in expected_state}
    if not _same_instant(existing.as_of, document.as_of) or actual_state != expected_state:
        raise StateIdempotencyConflictError("analysis state identity already has different immutable content")

    transition = session.scalar(select(AnalysisTransition).where(AnalysisTransition.to_state_id == existing.id))
    expected_transition_hash = content_hash(
        {
            "from_state_id": previous_state_id,
            "to_state_id": existing.id,
            **transition_payload,
        }
    )
    if transition is None or {
        "schema_version": transition.schema_version,
        "asset": transition.asset,
        "from_state_id": transition.from_state_id,
        "task_run_id": transition.task_run_id,
        "summary": transition.summary,
        "actions": transition.actions,
        "evidence_refs": transition.evidence_refs,
        "content_hash": transition.content_hash,
    } != {
        "schema_version": transition_payload["schema_version"],
        "asset": document.asset,
        "from_state_id": previous_state_id,
        "task_run_id": task_run_id,
        "summary": transition_payload["summary"],
        "actions": transition_payload["changes"],
        "evidence_refs": transition_payload["evidence_refs"],
        "content_hash": expected_transition_hash,
    }:
        raise StateIdempotencyConflictError("analysis state transition identity has different immutable content")


def _same_instant(left: datetime, right: datetime) -> bool:
    def normalized(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    return normalized(left) == normalized(right)


def _get_head(session: Session, asset: str, *, populate_existing: bool = False) -> AnalysisStateHead | None:
    statement = select(AnalysisStateHead).where(AnalysisStateHead.asset == asset)
    if populate_existing:
        statement = statement.execution_options(populate_existing=True)
    return session.scalar(statement)


def _is_idempotent_head_retry(
    head: AnalysisStateHead,
    *,
    new_state_id: str,
    expected_version: int,
) -> bool:
    return head.canonical_state_id == new_state_id and head.version == expected_version + 1


def _validate_output_lineage(
    session: Session,
    *,
    document: AnalysisStateDocument,
    authority: StateMaterializationAuthority,
    analysis_snapshot_db_id: str | None,
    final_analysis_result_id: str | None,
) -> None:
    snapshot: AnalysisSnapshot | None = None
    if analysis_snapshot_db_id is not None:
        snapshot = session.get(AnalysisSnapshot, analysis_snapshot_db_id)
        if snapshot is None:
            raise StateLineageError(f"analysis snapshot not found: {analysis_snapshot_db_id}")
        if snapshot.asset != document.asset:
            raise StateLineageError("analysis snapshot belongs to a different asset")

    if final_analysis_result_id is not None:
        result = session.get(FinalAnalysisResult, final_analysis_result_id)
        if result is None:
            raise StateLineageError(f"final analysis result not found: {final_analysis_result_id}")
        if result.asset != document.asset:
            raise StateLineageError("final analysis result belongs to a different asset")
        if snapshot is not None and result.analysis_snapshot_db_id not in {None, snapshot.id}:
            raise StateLineageError("final analysis result conflicts with analysis snapshot")

    accepted_snapshot_id = authority.accepted_output_snapshot_id
    if snapshot is not None and accepted_snapshot_id is not None and accepted_snapshot_id != snapshot.snapshot_id:
        raise StateLineageError("accepted_output snapshot_id conflicts with analysis snapshot")


def _require_canonical_authority(
    state: AnalysisState,
    authority: StateMaterializationAuthority,
) -> None:
    expected = {
        "quality_gate_action": state.quality_gate_action,
        "publish_allowed": state.publish_allowed,
        "accepted_output_source": state.accepted_output_source,
        "accepted_output_agent_name": state.accepted_output_agent_name,
        "accepted_output_snapshot_id": state.accepted_output_snapshot_id,
    }
    if not authority.publish_allowed or authority.quality_gate_action != "pass":
        raise PermissionError("canonical materialization requires QualityGate PASS")
    if authority.accepted_output_source == "none":
        raise PermissionError("canonical materialization requires authoritative accepted_output")
    if authority.model_dump() != expected:
        raise PermissionError("canonical materialization authority does not match immutable state")


def _required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized
