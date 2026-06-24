"""Playbook template registry schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import SchemaModel


class PlaybookSourceRef(SchemaModel):
    source_ref: str
    label: str | None = None
    endpoint: str | None = None
    artifact_path: str | None = None
    snapshot_id: str | None = None
    run_id: str | None = None


class PlaybookTemplateCreateRequest(SchemaModel):
    playbook_id: str
    version: str
    status: str
    title: str
    summary: str
    conditions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    invalidations: list[str] = Field(default_factory=list)
    source_refs: list[PlaybookSourceRef] = Field(default_factory=list)
    last_validated: datetime | None = None
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class PlaybookTemplateVersion(SchemaModel):
    playbook_id: str
    version: str
    status: str
    title: str
    summary: str
    conditions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    invalidations: list[str] = Field(default_factory=list)
    source_refs: list[PlaybookSourceRef] = Field(default_factory=list)
    last_validated: datetime | None = None
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None
    audit_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlaybookTemplateListResponse(SchemaModel):
    items: list[PlaybookTemplateVersion] = Field(default_factory=list)
    total: int = 0


class PlaybookTemplateDetailResponse(PlaybookTemplateVersion):
    versions: list[PlaybookTemplateVersion] = Field(default_factory=list)
