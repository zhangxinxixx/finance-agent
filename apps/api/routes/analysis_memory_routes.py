"""Analysis-memory read and explicit review routes."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from apps.analysis.state.schemas import StateScope
from apps.api.schemas.analysis_memory import (
    AnalysisStateView,
    AnalysisTransitionView,
    CandidateReviewRequest,
    CandidateReviewResponse,
    CandidateStatePage,
    CanonicalStateResponse,
    ContextBundleMetadata,
    ContextBundleMetadataPage,
)
from apps.api.services import analysis_memory_service
from database.models.engine import get_db

router = APIRouter(prefix="/api/analysis-memory", tags=["analysis-memory"])


def require_analysis_memory_writer(
    x_finance_analysis_memory_token: str | None = Header(
        default=None,
        alias="X-Finance-Analysis-Memory-Token",
    ),
) -> None:
    """Require an explicit write token even for localhost review actions."""

    expected = os.getenv("FINANCE_AGENT_ANALYSIS_MEMORY_WRITE_TOKEN", "").strip()
    if not expected:
        raise _error(
            503,
            "ANALYSIS_MEMORY_WRITE_DISABLED",
            "analysis-memory review writes are not configured",
        )
    if not x_finance_analysis_memory_token or not secrets.compare_digest(
        x_finance_analysis_memory_token,
        expected,
    ):
        raise _error(
            403,
            "ANALYSIS_MEMORY_WRITE_FORBIDDEN",
            "analysis-memory writer permission required",
        )


@router.get("/assets/{asset}/canonical", response_model=CanonicalStateResponse)
def api_analysis_memory_canonical(
    asset: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
    max_depth: int = Query(default=20, alias="maxDepth", ge=1, le=100),
    db: Session = Depends(get_db),
) -> CanonicalStateResponse:
    """Read accepted canonical state only; this route never invokes a model."""
    return _call_read(
        analysis_memory_service.get_latest_canonical,
        db,
        asset=asset,
        state_scope=state_scope,
        max_depth=max_depth,
    )


@router.get("/assets/{asset}/candidates", response_model=CandidateStatePage)
def api_analysis_memory_candidates(
    asset: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
) -> CandidateStatePage:
    return _call_read(
        analysis_memory_service.list_candidates,
        db,
        asset=asset,
        state_scope=state_scope,
        page=page,
        page_size=page_size,
    )


@router.get("/assets/{asset}/context-bundles", response_model=ContextBundleMetadataPage)
def api_analysis_memory_context_bundles(
    asset: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> ContextBundleMetadataPage:
    return _call_read(
        analysis_memory_service.list_context_bundle_metadata,
        asset=asset,
        state_scope=state_scope,
        page=page,
        page_size=page_size,
    )


@router.get("/states/{state_id}", response_model=AnalysisStateView)
def api_analysis_memory_state(
    state_id: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
    db: Session = Depends(get_db),
) -> AnalysisStateView:
    return _call_read(
        analysis_memory_service.get_state_response,
        db,
        state_id=state_id,
        state_scope=state_scope,
    )


@router.get("/transitions/{transition_id}", response_model=AnalysisTransitionView)
def api_analysis_memory_transition(
    transition_id: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
    db: Session = Depends(get_db),
) -> AnalysisTransitionView:
    return _call_read(
        analysis_memory_service.get_transition_response,
        db,
        transition_id=transition_id,
        state_scope=state_scope,
    )


@router.get("/context-bundles/{bundle_id}", response_model=ContextBundleMetadata)
def api_analysis_memory_context_bundle(
    bundle_id: str,
    state_scope: StateScope = Query(default="daily_close", alias="stateScope"),
) -> ContextBundleMetadata:
    return _call_read(
        analysis_memory_service.get_context_bundle_metadata,
        bundle_id=bundle_id,
        state_scope=state_scope,
    )


@router.post("/candidates/{candidate_id}/reviews", response_model=CandidateReviewResponse)
def api_analysis_memory_candidate_review(
    candidate_id: str,
    body: CandidateReviewRequest,
    _writer: None = Depends(require_analysis_memory_writer),
    db: Session = Depends(get_db),
) -> CandidateReviewResponse:
    try:
        return analysis_memory_service.accept_candidate(db, candidate_id=candidate_id, request=body)
    except analysis_memory_service.AnalysisMemoryNotFoundError as exc:
        raise _error(404, "ANALYSIS_MEMORY_NOT_FOUND", str(exc)) from exc
    except analysis_memory_service.AnalysisMemoryConflictError as exc:
        raise _error(409, "ANALYSIS_MEMORY_CONFLICT", str(exc)) from exc
    except analysis_memory_service.AnalysisMemoryReviewError as exc:
        raise _error(422, "ANALYSIS_MEMORY_REVIEW_INVALID", str(exc)) from exc


def _call_read(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except analysis_memory_service.AnalysisMemoryNotFoundError as exc:
        raise _error(404, "ANALYSIS_MEMORY_NOT_FOUND", str(exc)) from exc
    except analysis_memory_service.AnalysisMemoryConflictError as exc:
        raise _error(409, "ANALYSIS_MEMORY_CONFLICT", str(exc)) from exc
    except analysis_memory_service.AnalysisMemoryReviewError as exc:
        raise _error(422, "ANALYSIS_MEMORY_INVALID", str(exc)) from exc


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
