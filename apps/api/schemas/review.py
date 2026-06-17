"""Review queue schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ReviewStatus, SchemaModel
from .source_trace import ArtifactRef
from .source_trace import SourceRef


class ReviewActionRequest(SchemaModel):
    note: str | None = None
    reason: str | None = None
    actor: str | None = None
    request_id: str | None = None
    expected_status: str | None = None


class ReviewItem(SchemaModel):
    review_id: str
    run_id: str | None = None
    source_module: str
    source_step_id: str | None = None
    agent_output_id: str | None = None
    claim_id: str | None = None
    severity: str
    reason: str
    impact_modules: list[str] = Field(default_factory=list)
    impact_report_ids: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    suggested_action: str | None = None
    status: ReviewStatus = ReviewStatus.pending
    resolution_action: str | None = None
    resolution_note: str | None = None
    resolution_actor: str | None = None
    resolution_request_id: str | None = None
    audit_id: str | None = None
    action_status: str | None = None
    next_run_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
