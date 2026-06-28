"""Settings read routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas.settings import SettingsHistoryResponse
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/settings/status")
def api_settings_status(db: Session = Depends(get_db)):
    """返回配置状态概览（密钥已脱敏）。"""
    from apps.api import main as api_main

    return api_main.settings_service.build_settings_status(db=db)


@router.get("/api/settings/history", response_model=SettingsHistoryResponse)
def api_settings_history(
    limit: int = 50,
    setting_key: str | None = None,
    source_key: str | None = None,
    scope: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    days: int | None = None,
    db: Session = Depends(get_db),
) -> SettingsHistoryResponse:
    """返回 Settings 最近配置变更历史。"""
    from apps.api import main as api_main

    return api_main.settings_service.build_settings_history(
        db,
        limit=limit,
        setting_key=setting_key,
        source_key=source_key,
        scope=scope,
        action=action,
        actor=actor,
        q=q,
        days=days,
    )
