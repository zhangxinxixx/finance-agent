"""Source trace routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.source_trace import SourceTraceResponse
from apps.api.services.source_trace_service import (
    get_source_trace_by_artifact_id,
    get_source_trace_by_report_id,
    get_source_trace_by_snapshot_id,
    get_source_trace_by_strategy_card_id,
)
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/source-trace/by-report/{report_id}", response_model=SourceTraceResponse)
def api_source_trace_by_report(report_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 report_id 反查 snapshot/run/artifact 溯源视图。"""
    trace = get_source_trace_by_report_id(db, report_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@router.get("/api/source-trace/by-strategy/{strategy_card_id}", response_model=SourceTraceResponse)
def api_source_trace_by_strategy(strategy_card_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 strategy_card_id 反查关联 run/snapshot/source/artifact。"""
    trace = get_source_trace_by_strategy_card_id(db, strategy_card_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@router.get("/api/source-trace/by-artifact/{artifact_id}", response_model=SourceTraceResponse)
def api_source_trace_by_artifact(artifact_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 artifact_id 反查关联 snapshot/source/artifact 溯源视图。"""
    trace = get_source_trace_by_artifact_id(db, artifact_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace


@router.get("/api/source-trace/{snapshot_id}", response_model=SourceTraceResponse)
def api_source_trace_detail(snapshot_id: str, db: Session = Depends(get_db)) -> SourceTraceResponse:
    """按 snapshot_id 返回 Phase 3 source trace 只读溯源视图。"""
    trace = get_source_trace_by_snapshot_id(db, snapshot_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Source trace not found")
    return trace
