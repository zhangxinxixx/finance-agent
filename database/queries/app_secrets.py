"""Encrypted app secret repository helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import AppSecret


def get_app_secret(session: Session, source_key: str) -> AppSecret | None:
    return session.scalar(select(AppSecret).where(AppSecret.source_key == source_key))


def upsert_app_secret(
    session: Session,
    *,
    source_key: str,
    secret_name: str,
    encrypted_value: str,
    masked_value: str,
    actor: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    audit_id: str | None = None,
) -> AppSecret:
    record = get_app_secret(session, source_key)
    if record is None:
        record = AppSecret(
            source_key=source_key,
            secret_name=secret_name,
            encrypted_value=encrypted_value,
            masked_value=masked_value,
        )
        session.add(record)

    record.secret_name = secret_name
    record.encrypted_value = encrypted_value
    record.masked_value = masked_value
    record.updated_by = actor
    record.update_reason = reason
    record.request_id = request_id
    record.audit_id = audit_id
    session.flush()
    return record


def reset_app_secret(session: Session, source_key: str) -> bool:
    record = get_app_secret(session, source_key)
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True
