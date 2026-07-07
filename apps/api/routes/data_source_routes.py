"""Data source and ingestion action routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas.data_source import (
    DataSourceActionRequest,
    DataSourceActionResponse,
    DataSourceTestRequest,
    DataSourceTestResponse,
    ManualUploadRequest,
)
from apps.api import data_service
from apps.api.services import ingestion_action_service, ingestion_source_test_service, source_service
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/data-sources/status")
def api_data_sources_status():
    """返回数据源 configured/raw/parsed/analysis_ready 四层状态。"""
    return data_service.get_data_source_statuses()


@router.get("/api/data-sources/registry")
def api_data_sources_registry():
    """返回统一数据源 registry 契约。"""
    return source_service.get_data_sources_registry()


@router.get("/api/data-status/summary")
def api_data_status_summary():
    """返回全局数据状态摘要，供前端 DataStatusBar 使用。"""
    return source_service.get_data_status_summary()


@router.get("/api/data-sources/health/latest")
def api_data_source_health_latest():
    """返回最新派生数据源健康快照。"""
    return source_service.get_data_source_health_latest()


@router.get("/api/data-sources/health")
def api_data_source_health(date: str | None = None, db: Session = Depends(get_db)):
    """返回指定日期的数据源健康快照；当前实现基于最新状态派生。"""
    return source_service.get_data_source_health_latest(date=date, db=db)


@router.get("/api/data-sources/{source_key}/history")
def api_data_source_history(source_key: str, limit: int = 30, db: Session = Depends(get_db)):
    """返回单个数据源的每日健康历史。"""
    return source_service.get_data_source_history(source_key, db=db, limit=limit)


@router.post("/api/ingestion/sources/{source_key}/retry", response_model=DataSourceActionResponse)
def api_ingestion_source_retry(
    source_key: str,
    body: DataSourceActionRequest | None = None,
    db: Session = Depends(get_db),
) -> DataSourceActionResponse:
    """登记数据源重试请求，返回可追踪 task_run。"""
    return ingestion_action_service.create_ingestion_retry(db, source_key, body)


@router.post("/api/ingestion/sources/{source_key}/test", response_model=DataSourceTestResponse)
def api_ingestion_source_test(
    source_key: str,
    body: DataSourceTestRequest | None = None,
    db: Session = Depends(get_db),
) -> DataSourceTestResponse:
    """执行轻量数据源 probe，返回页面预览并写入 probe 审计。"""
    return ingestion_source_test_service.run_ingestion_source_test(db, source_key, body)


@router.post("/api/ingestion/manual-upload", response_model=DataSourceActionResponse)
def api_ingestion_manual_upload(
    body: ManualUploadRequest,
    db: Session = Depends(get_db),
) -> DataSourceActionResponse:
    """登记手工上传 raw/staging artifact；解析后续必须回主链。"""
    return ingestion_action_service.register_manual_upload(db, body)
