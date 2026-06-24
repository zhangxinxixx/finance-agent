"""Playbook template registry service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.schemas.playbook import (
    PlaybookTemplateCreateRequest,
    PlaybookTemplateDetailResponse,
    PlaybookTemplateListResponse,
    PlaybookTemplateVersion,
)
from database.queries.playbooks import (
    create_playbook_template as create_playbook_template_record,
    get_playbook_template_detail as get_playbook_template_detail_record,
    list_playbook_templates as list_playbook_template_records,
    list_playbook_template_versions as list_playbook_template_versions_records,
)


class PlaybookConflictError(ValueError):
    """Raised when a playbook template version already exists."""


class PlaybookNotFoundError(LookupError):
    """Raised when a playbook template registry entry is missing."""


def _to_version_model(payload) -> PlaybookTemplateVersion:
    return PlaybookTemplateVersion(**payload)


def create_playbook_template(db: Session, body: PlaybookTemplateCreateRequest) -> PlaybookTemplateVersion:
    try:
        record = create_playbook_template_record(
            db,
            playbook_id=body.playbook_id,
            version=body.version,
            status=body.status,
            title=body.title,
            summary=body.summary,
            conditions=list(body.conditions),
            actions=list(body.actions),
            invalidations=list(body.invalidations),
            source_refs=[item.model_dump(mode="json") for item in body.source_refs],
            last_validated=body.last_validated,
            actor=body.actor,
            reason=body.reason,
            request_id=body.request_id,
            audit_id=f"playbook:{body.playbook_id}:{body.version}",
        )
    except ValueError as exc:
        raise PlaybookConflictError(str(exc)) from exc

    db.commit()
    db.refresh(record)
    return _to_version_model(
        {
            "playbook_id": record.playbook_id,
            "version": record.version,
            "status": record.status,
            "title": record.title,
            "summary": record.summary,
            "conditions": list(record.conditions or []),
            "actions": list(record.actions or []),
            "invalidations": list(record.invalidations or []),
            "source_refs": list(record.source_refs or []),
            "last_validated": record.last_validated,
            "actor": record.updated_by,
            "reason": record.update_reason,
            "request_id": record.request_id,
            "audit_id": record.audit_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    )


def list_playbook_templates(db: Session) -> PlaybookTemplateListResponse:
    items = [_to_version_model(item) for item in list_playbook_template_records(db)]
    return PlaybookTemplateListResponse(items=items, total=len(items))


def list_playbook_template_versions(db: Session, playbook_id: str) -> list[PlaybookTemplateVersion]:
    return [_to_version_model(item) for item in list_playbook_template_versions_records(db, playbook_id)]


def get_playbook_template_detail(db: Session, playbook_id: str) -> PlaybookTemplateDetailResponse | None:
    payload = get_playbook_template_detail_record(db, playbook_id)
    if payload is None:
        return None
    versions = payload.pop("versions", [])
    return PlaybookTemplateDetailResponse(
        **payload,
        versions=[_to_version_model(item) for item in versions],
    )
