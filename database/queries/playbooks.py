"""Playbook template registry repository helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.playbook import PlaybookTemplate


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _serialize_template(record: PlaybookTemplate) -> dict[str, Any]:
    return {
        "playbook_id": record.playbook_id,
        "version": record.version,
        "status": record.status,
        "title": record.title,
        "summary": record.summary,
        "conditions": list(record.conditions or []),
        "actions": list(record.actions or []),
        "invalidations": list(record.invalidations or []),
        "source_refs": list(record.source_refs or []),
        "last_validated": record.last_validated.isoformat() if record.last_validated is not None else None,
        "actor": record.updated_by,
        "reason": record.update_reason,
        "request_id": record.request_id,
        "audit_id": record.audit_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def create_playbook_template(
    session: Session,
    *,
    playbook_id: str,
    version: str,
    status: str,
    title: str,
    summary: str,
    conditions: list[str],
    actions: list[str],
    invalidations: list[str],
    source_refs: list[dict[str, Any]],
    last_validated: datetime | str | None = None,
    actor: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    audit_id: str | None = None,
) -> PlaybookTemplate:
    existing = session.scalar(
        select(PlaybookTemplate).where(
            PlaybookTemplate.playbook_id == playbook_id,
            PlaybookTemplate.version == version,
        )
    )
    if existing is not None:
        raise ValueError(f"Duplicate playbook template version: {playbook_id} {version}")

    record = PlaybookTemplate(
        playbook_id=playbook_id,
        version=version,
        status=status,
        title=title,
        summary=summary,
        conditions=list(conditions),
        actions=list(actions),
        invalidations=list(invalidations),
        source_refs=list(source_refs),
        last_validated=_parse_datetime(last_validated),
        updated_by=actor,
        update_reason=reason,
        request_id=request_id,
        audit_id=audit_id,
    )
    session.add(record)
    session.flush()
    return record


def get_playbook_template(session: Session, playbook_id: str) -> PlaybookTemplate | None:
    stmt = (
        select(PlaybookTemplate)
        .where(PlaybookTemplate.playbook_id == playbook_id)
        .order_by(PlaybookTemplate.created_at.desc(), PlaybookTemplate.id.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def list_playbook_template_versions(session: Session, playbook_id: str) -> list[PlaybookTemplate]:
    stmt = (
        select(PlaybookTemplate)
        .where(PlaybookTemplate.playbook_id == playbook_id)
        .order_by(PlaybookTemplate.created_at.desc(), PlaybookTemplate.id.desc())
    )
    return list(session.scalars(stmt))


def get_playbook_template_detail(session: Session, playbook_id: str) -> dict[str, Any] | None:
    latest = get_playbook_template(session, playbook_id)
    if latest is None:
        return None
    versions = [_serialize_template(item) for item in list_playbook_template_versions(session, playbook_id)]
    payload = _serialize_template(latest)
    payload["versions"] = versions
    return payload


def list_playbook_templates(session: Session) -> list[dict[str, Any]]:
    stmt = (
        select(PlaybookTemplate)
        .order_by(PlaybookTemplate.playbook_id.asc(), PlaybookTemplate.created_at.desc(), PlaybookTemplate.id.desc())
    )
    latest_by_playbook: dict[str, PlaybookTemplate] = {}
    for item in session.scalars(stmt):
        if item.playbook_id not in latest_by_playbook:
            latest_by_playbook[item.playbook_id] = item
    items = [_serialize_template(item) for item in latest_by_playbook.values()]
    items.sort(key=lambda item: (item["updated_at"] or item["created_at"], item["playbook_id"]), reverse=True)
    return items
