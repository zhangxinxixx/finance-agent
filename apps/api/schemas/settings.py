"""Settings read/write schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import SchemaModel


class SettingsPreferencesUpdateRequest(SchemaModel):
    language: str | None = None
    timezone: str | None = None
    report_template: str | None = None
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsSourceUpdateRequest(SchemaModel):
    enabled: bool
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsPreferencesResetRequest(SchemaModel):
    keys: list[str] = Field(default_factory=list)
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsSourceResetRequest(SchemaModel):
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsSecretUpdateRequest(SchemaModel):
    secret_value: str
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsSecretResetRequest(SchemaModel):
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsRollbackRequest(SchemaModel):
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsActionResponse(SchemaModel):
    status: str
    audit_id: str | None = None
    rolled_back_audit_id: str | None = None
    updated_keys: list[str] = Field(default_factory=list)
    source_key: str | None = None
    enabled: bool | None = None
    updated_at: datetime | None = None


class SettingsHistoryEvent(SchemaModel):
    setting_key: str
    scope: str
    source_key: str | None = None
    action: str
    old_value_json: dict | None = None
    new_value_json: dict | None = None
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None
    audit_id: str | None = None
    created_at: datetime | None = None


class SettingsHistoryResponse(SchemaModel):
    events: list[SettingsHistoryEvent] = Field(default_factory=list)
    total: int = 0
