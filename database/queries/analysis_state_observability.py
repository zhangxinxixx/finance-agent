"""Read-only queries for analysis-state observability views."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


def get_state(session: Session, state_id: str) -> AnalysisState | None:
    return session.get(AnalysisState, state_id)


def get_head(session: Session, asset: str) -> AnalysisStateHead | None:
    return session.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == asset))


def get_transition(session: Session, transition_id: str) -> AnalysisTransition | None:
    return session.get(AnalysisTransition, transition_id)


def get_transition_to_state(session: Session, state_id: str) -> AnalysisTransition | None:
    return session.scalar(select(AnalysisTransition).where(AnalysisTransition.to_state_id == state_id))


def get_candidate_acceptance_lineage(
    session: Session,
    *,
    state: AnalysisState,
) -> tuple[AnalysisSnapshot, FinalAnalysisResult, AgentOutput] | None:
    """Resolve persisted primary-output authority for a review candidate."""

    if state.analysis_snapshot_db_id is None or state.final_analysis_result_id is None:
        return None
    snapshot = session.get(AnalysisSnapshot, state.analysis_snapshot_db_id)
    final_result = session.get(FinalAnalysisResult, state.final_analysis_result_id)
    if snapshot is None or final_result is None or not final_result.snapshot_id:
        return None
    coordinator = session.scalar(
        select(AgentOutput)
        .where(
            AgentOutput.analysis_snapshot_db_id == snapshot.id,
            AgentOutput.run_id == state.task_run_id,
            AgentOutput.snapshot_id == final_result.snapshot_id,
            AgentOutput.agent_name == "coordinator_agent",
            AgentOutput.status == "success",
        )
        .order_by(AgentOutput.created_at.desc(), AgentOutput.id.desc())
    )
    if coordinator is None:
        return None
    if (
        snapshot.asset != state.asset
        or snapshot.run_id != state.task_run_id
        or final_result.asset != state.asset
        or final_result.run_id != state.task_run_id
        or final_result.analysis_snapshot_db_id != snapshot.id
        or coordinator.asset != state.asset
    ):
        return None
    return snapshot, final_result, coordinator


def list_candidate_states_page(
    session: Session,
    *,
    asset: str,
    page: int,
    page_size: int,
) -> tuple[list[AnalysisState], int]:
    """List non-canonical, non-publishable states without mutating read state."""

    canonical_ids = select(AnalysisStateHead.canonical_state_id)
    predicate = (
        AnalysisState.asset == asset,
        AnalysisState.publish_allowed.is_(False),
        AnalysisState.id.not_in(canonical_ids),
    )
    total = int(session.scalar(select(func.count()).select_from(AnalysisState).where(*predicate)) or 0)
    rows = list(
        session.scalars(
            select(AnalysisState)
            .where(*predicate)
            .order_by(AnalysisState.as_of.desc(), AnalysisState.created_at.desc(), AnalysisState.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, total
