"""Data source status schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import DataStatus, TraceableResponse
from .source_trace import ArtifactRef, SourceRef


class DataSourceStatus(TraceableResponse):
    source_id: str
    source_name: str
    priority: int | None = None
    config_status: str | None = None
    runtime_status: str | None = None
    latest_data_date: str | None = None
    last_success_at: datetime | None = None
    last_run_at: datetime | None = None
    completeness: float | None = None
    latency: float | None = None
    affected_modules: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    related_steps: list[str] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)


class DataSourceActionRequest(TraceableResponse):
    action: str | None = None
    actor: str | None = None
    reason: str | None = None
    request_id: str | None = None


class ManualUploadRequest(DataSourceActionRequest):
    source_key: str
    file_name: str
    sha256: str | None = None
    artifact_path: str | None = None


class DataSourceActionResponse(TraceableResponse):
    status: str
    action: str
    source_key: str
    run_id: str | None = None
    audit_id: str | None = None
    data_status: DataStatus = DataStatus.manual_required


class DataSourceTestRequest(DataSourceActionRequest):
    limit: int = Field(default=5, ge=1, le=20)


class DataSourceTestResponse(TraceableResponse):
    status: str
    action: str = "test"
    source_key: str
    run_id: str | None = None
    audit_id: str | None = None
    duration_ms: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, str | None] = Field(default_factory=dict)


DataSourceStatus.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
DataSourceActionRequest.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
ManualUploadRequest.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
DataSourceActionResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
DataSourceTestRequest.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
DataSourceTestResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
