"""Playbook registry routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.playbook import (
    PlaybookTemplateCreateRequest,
    PlaybookTemplateDetailResponse,
    PlaybookTemplateListResponse,
    PlaybookTemplateVersion,
)
from database.models.engine import get_db

router = APIRouter()


@router.post("/api/playbooks", response_model=PlaybookTemplateVersion)
def api_create_playbook(
    body: PlaybookTemplateCreateRequest,
    db: Session = Depends(get_db),
) -> PlaybookTemplateVersion:
    """登记新的 Playbook 模板版本。"""
    from apps.api import main as api_main

    try:
        return api_main.playbook_service.create_playbook_template(db, body)
    except api_main.playbook_service.PlaybookConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/playbooks", response_model=PlaybookTemplateListResponse)
def api_playbooks(db: Session = Depends(get_db)) -> PlaybookTemplateListResponse:
    """返回 Playbook 模板最新版本列表。"""
    from apps.api import main as api_main

    return api_main.playbook_service.list_playbook_templates(db)


@router.get("/api/playbooks/{playbook_id}", response_model=PlaybookTemplateDetailResponse)
def api_playbook_detail(playbook_id: str, db: Session = Depends(get_db)) -> PlaybookTemplateDetailResponse:
    """返回单个 Playbook 模板族的最新版本和历史版本。"""
    from apps.api import main as api_main

    data = api_main.playbook_service.get_playbook_template_detail(db, playbook_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Playbook template not found")
    return data


@router.get("/api/playbooks/{playbook_id}/versions", response_model=PlaybookTemplateListResponse)
def api_playbook_versions(playbook_id: str, db: Session = Depends(get_db)) -> PlaybookTemplateListResponse:
    """返回单个 Playbook 模板族的版本列表。"""
    from apps.api import main as api_main

    versions = api_main.playbook_service.list_playbook_template_versions(db, playbook_id)
    return PlaybookTemplateListResponse(items=versions, total=len(versions))
