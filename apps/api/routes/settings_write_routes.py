"""Settings write routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.settings import (
    SettingsActionResponse,
    SettingsPreferencesResetRequest,
    SettingsPreferencesUpdateRequest,
    SettingsRollbackRequest,
    SettingsSecretResetRequest,
    SettingsSecretUpdateRequest,
    SettingsSourceResetRequest,
    SettingsSourceUpdateRequest,
)
from database.models.engine import get_db

router = APIRouter()


@router.post("/api/settings/preferences", response_model=SettingsActionResponse)
def api_settings_update_preferences(
    body: SettingsPreferencesUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入非敏感全局偏好配置。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.update_preferences(db, body)
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/settings/preferences/reset", response_model=SettingsActionResponse)
def api_settings_reset_preferences(
    body: SettingsPreferencesResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """将指定全局偏好回退为默认值。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.reset_preferences(db, body)
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/settings/sources/{source_key}", response_model=SettingsActionResponse)
def api_settings_update_source(
    source_key: str,
    body: SettingsSourceUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入数据源 enable/disable 请求，不改变 runtime connectivity 检测。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.update_source_enabled(db, source_key, body)
    except api_main.settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc


@router.post("/api/settings/sources/{source_key}/reset", response_model=SettingsActionResponse)
def api_settings_reset_source(
    source_key: str,
    body: SettingsSourceResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """清除数据源 enable/disable overlay，回退到默认检测值。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.reset_source_enabled(db, source_key, body)
    except api_main.settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/settings/secrets/{source_key}", response_model=SettingsActionResponse)
def api_settings_update_secret(
    source_key: str,
    body: SettingsSecretUpdateRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """写入加密 secret storage，仅回显 masked/configured 元数据。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.update_secret(db, source_key, body)
    except api_main.settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except api_main.settings_service.SettingsSecretStorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Settings secret storage is not configured") from exc


@router.post("/api/settings/secrets/{source_key}/reset", response_model=SettingsActionResponse)
def api_settings_reset_secret(
    source_key: str,
    body: SettingsSecretResetRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """清除加密 secret storage 中保存的密钥。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.reset_secret(db, source_key, body)
    except api_main.settings_service.SettingsSourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings source not found") from exc
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/settings/history/{audit_id}/rollback", response_model=SettingsActionResponse)
def api_settings_rollback_history_event(
    audit_id: str,
    body: SettingsRollbackRequest,
    db: Session = Depends(get_db),
) -> SettingsActionResponse:
    """按历史 audit_id 回滚非敏感设置。"""
    from apps.api import main as api_main

    try:
        return api_main.settings_service.rollback_settings_event(db, audit_id, body)
    except api_main.settings_service.SettingsHistoryEventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Settings history event not found") from exc
    except api_main.settings_service.SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
