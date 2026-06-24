"""Common API schema primitives for backend contracts."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from .source_trace import ArtifactRef, SourceRef


class SchemaModel(BaseModel):
    """Base model with strict, reusable Pydantic v2 config."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DataStatus(str, enum.Enum):
    live = "live"
    partial = "partial"
    stale = "stale"
    fallback = "fallback"
    mock = "mock"
    unavailable = "unavailable"
    manual_required = "manual_required"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    success = "success"
    partial_success = "partial_success"
    failed = "failed"
    retrying = "retrying"
    skipped = "skipped"
    degraded = "degraded"
    needs_review = "needs_review"
    cancelled = "cancelled"


class ArtifactType(str, enum.Enum):
    source_md = "source_md"
    analysis_md = "analysis_md"
    visual_html = "visual_html"
    structured_json = "structured_json"
    raw_file = "raw_file"
    parsed_file = "parsed_file"
    feature_json = "feature_json"
    chart_snapshot = "chart_snapshot"


class ReviewStatus(str, enum.Enum):
    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    rerun = "rerun"


class ReportLifecycleStatus(str, enum.Enum):
    draft = "draft"
    generated = "generated"
    snapshot_bound = "snapshot_bound"
    needs_review = "needs_review"
    published = "published"
    exported = "exported"
    archived = "archived"


class WarningItem(SchemaModel):
    code: str
    message: str
    severity: str = "warning"
    field: str | None = None
    hint: str | None = None


class TraceableResponse(SchemaModel):
    """Shared API response envelope for traceable backend artifacts."""

    run_id: str | None = None
    snapshot_id: str | None = None
    data_status: DataStatus = DataStatus.live
    source_refs: list["SourceRef"] = Field(default_factory=list)
    artifact_refs: list["ArtifactRef"] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
