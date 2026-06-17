"""App settings repository helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models.analysis import AppSetting, AppSettingEvent


def get_app_setting(session: Session, setting_key: str) -> AppSetting | None:
    return session.scalar(select(AppSetting).where(AppSetting.setting_key == setting_key))


def list_app_settings(session: Session, *, scope: str | None = None) -> list[AppSetting]:
    stmt = select(AppSetting)
    if scope is not None:
        stmt = stmt.where(AppSetting.scope == scope)
    stmt = stmt.order_by(AppSetting.scope.asc(), AppSetting.setting_key.asc())
    return list(session.scalars(stmt))


def list_app_setting_events(
    session: Session,
    *,
    setting_key: str | None = None,
    source_key: str | None = None,
    scope: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[AppSettingEvent]:
    stmt = select(AppSettingEvent)
    if setting_key is not None:
        stmt = stmt.where(AppSettingEvent.setting_key == setting_key)
    if source_key is not None:
        stmt = stmt.where(AppSettingEvent.source_key == source_key)
    if scope is not None:
        stmt = stmt.where(AppSettingEvent.scope == scope)
    if action is not None:
        stmt = stmt.where(AppSettingEvent.action == action)
    if actor is not None:
        stmt = stmt.where(AppSettingEvent.actor == actor)
    if since is not None:
        stmt = stmt.where(AppSettingEvent.created_at >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                AppSettingEvent.setting_key.ilike(like),
                AppSettingEvent.scope.ilike(like),
                AppSettingEvent.source_key.ilike(like),
                AppSettingEvent.action.ilike(like),
                AppSettingEvent.actor.ilike(like),
                AppSettingEvent.reason.ilike(like),
                AppSettingEvent.request_id.ilike(like),
                AppSettingEvent.audit_id.ilike(like),
            )
        )
    stmt = stmt.order_by(AppSettingEvent.created_at.desc(), AppSettingEvent.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_app_setting_event_by_audit_id(session: Session, audit_id: str) -> AppSettingEvent | None:
    return session.scalar(select(AppSettingEvent).where(AppSettingEvent.audit_id == audit_id))


def upsert_app_setting(
    session: Session,
    *,
    setting_key: str,
    scope: str,
    value_json: dict[str, Any],
    source_key: str | None = None,
    actor: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    audit_id: str | None = None,
) -> AppSetting:
    record = get_app_setting(session, setting_key)
    old_value = dict(record.value_json) if record is not None else None
    if record is None:
        record = AppSetting(
            setting_key=setting_key,
            scope=scope,
            source_key=source_key,
            value_json=value_json,
        )
        session.add(record)

    record.scope = scope
    record.source_key = source_key
    record.value_json = value_json
    record.updated_by = actor
    record.update_reason = reason
    record.request_id = request_id
    record.audit_id = audit_id
    _create_app_setting_event(
        session,
        setting_key=setting_key,
        scope=scope,
        source_key=source_key,
        action="set",
        old_value_json=old_value,
        new_value_json=value_json,
        actor=actor,
        reason=reason,
        request_id=request_id,
        audit_id=audit_id,
    )
    session.flush()
    return record


def reset_app_setting(
    session: Session,
    *,
    setting_key: str,
    actor: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    audit_id: str | None = None,
) -> bool:
    record = get_app_setting(session, setting_key)
    if record is None:
        return False
    old_value = dict(record.value_json)
    scope = record.scope
    source_key = record.source_key
    session.delete(record)
    _create_app_setting_event(
        session,
        setting_key=setting_key,
        scope=scope,
        source_key=source_key,
        action="reset",
        old_value_json=old_value,
        new_value_json=None,
        actor=actor,
        reason=reason,
        request_id=request_id,
        audit_id=audit_id,
    )
    session.flush()
    return True


def rollback_app_setting(
    session: Session,
    *,
    setting_key: str,
    scope: str,
    value_json: dict[str, Any] | None,
    source_key: str | None = None,
    actor: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    audit_id: str | None = None,
) -> AppSetting | None:
    record = get_app_setting(session, setting_key)
    old_value = dict(record.value_json) if record is not None else None
    if value_json is None:
        if record is None:
            return None
        session.delete(record)
    else:
        if record is None:
            record = AppSetting(
                setting_key=setting_key,
                scope=scope,
                source_key=source_key,
                value_json=value_json,
            )
            session.add(record)
        record.scope = scope
        record.source_key = source_key
        record.value_json = value_json
        record.updated_by = actor
        record.update_reason = reason
        record.request_id = request_id
        record.audit_id = audit_id
    _create_app_setting_event(
        session,
        setting_key=setting_key,
        scope=scope,
        source_key=source_key,
        action="rollback",
        old_value_json=old_value,
        new_value_json=value_json,
        actor=actor,
        reason=reason,
        request_id=request_id,
        audit_id=audit_id,
    )
    session.flush()
    return record


def _create_app_setting_event(
    session: Session,
    *,
    setting_key: str,
    scope: str,
    source_key: str | None,
    action: str,
    old_value_json: dict[str, Any] | None,
    new_value_json: dict[str, Any] | None,
    actor: str | None,
    reason: str | None,
    request_id: str | None,
    audit_id: str | None,
) -> AppSettingEvent:
    event = AppSettingEvent(
        setting_key=setting_key,
        scope=scope,
        source_key=source_key,
        action=action,
        old_value_json=old_value_json,
        new_value_json=new_value_json,
        actor=actor,
        reason=reason,
        request_id=request_id,
        audit_id=audit_id,
    )
    session.add(event)
    return event
