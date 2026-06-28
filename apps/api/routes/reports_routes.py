"""Reports index/detail routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType
from apps.api.schemas.report import ReportAnalysisInputs, ReportArtifact, ReportDetail
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/reports/index")
def api_reports_index():
    """返回所有报告类型的索引列表。"""
    from apps.api import main as api_main

    return api_main.list_reports_index()


@router.get("/api/reports/dates")
def api_reports_dates():
    """返回所有可用 trade_date 及其模块覆盖。"""
    from apps.api import main as api_main

    return api_main.list_unified_dates()


@router.get("/api/reports/{report_id}", response_model=ReportDetail)
def api_report_detail(report_id: str, db: Session = Depends(get_db)) -> ReportDetail:
    """返回标准报告详情；优先读新 report tables，其次走 legacy adapter。"""
    from apps.api import main as api_main

    detail = api_main.get_report_detail(db, report_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return detail


@router.get("/api/reports/{report_id}/artifacts", response_model=list[ReportArtifact])
def api_report_artifacts(report_id: str, db: Session = Depends(get_db)) -> list[ReportArtifact]:
    from apps.api import main as api_main

    artifacts = api_main.get_report_artifacts(db, report_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return artifacts


@router.get("/api/reports/{report_id}/source")
def api_report_source(report_id: str, db: Session = Depends(get_db)):
    from apps.api import main as api_main

    payload = api_main.get_report_source(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@router.get("/api/reports/{report_id}/analysis")
def api_report_analysis(report_id: str, db: Session = Depends(get_db)):
    from apps.api import main as api_main

    payload = api_main.get_report_analysis(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@router.get("/api/reports/{report_id}/asset/{artifact_type}/{asset_path:path}")
def api_report_artifact_asset(report_id: str, artifact_type: ArtifactType, asset_path: str, db: Session = Depends(get_db)):
    from apps.api import main as api_main

    path = api_main.get_report_artifact_asset_path(db, report_id, artifact_type, asset_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Report artifact asset not found")
    return FileResponse(path)


@router.get("/api/reports/{report_id}/visual")
def api_report_visual(report_id: str, db: Session = Depends(get_db)):
    from apps.api import main as api_main

    payload = api_main.get_report_visual(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@router.get("/api/reports/{report_id}/evidence")
def api_report_evidence(report_id: str, db: Session = Depends(get_db)):
    from apps.api import main as api_main

    payload = api_main.get_report_evidence(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return payload


@router.get("/api/reports/{report_id}/analysis-inputs", response_model=ReportAnalysisInputs)
def api_report_analysis_inputs(report_id: str, db: Session = Depends(get_db)) -> ReportAnalysisInputs:
    from apps.api import main as api_main

    payload = api_main.get_report_analysis_inputs(db, report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Report analysis inputs not found")
    return payload
