"""Typed public contracts for analysis-state observability and review."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from apps.api.schemas.common import SchemaModel


class PaginationMeta(SchemaModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AnalysisTransitionView(SchemaModel):
    transition_id: str
    schema_version: str
    asset: str
    from_state_id: str | None
    to_state_id: str
    run_id: str
    summary: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    content_hash: str
    created_at: datetime | None = None


class AnalysisStateLineage(SchemaModel):
    run_id: str
    analysis_snapshot_db_id: str | None = None
    final_analysis_result_id: str | None = None
    accepted_output_snapshot_id: str | None = None
    input_snapshot_ids: dict[str, str] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)


class AnalysisStateView(SchemaModel):
    state_id: str
    state_kind: Literal["accepted_canonical", "candidate", "blocked"]
    schema_version: str
    asset: str
    as_of: datetime
    previous_state_id: str | None
    quality_gate_action: str
    publish_allowed: bool
    accepted_output_source: str
    accepted_output_agent_name: str | None = None
    content_hash: str
    payload: dict[str, Any]
    lineage: AnalysisStateLineage
    transition: AnalysisTransitionView | None = None
    created_at: datetime | None = None


class CanonicalStateResponse(SchemaModel):
    schema_version: Literal["analysis_memory_read.v1"] = "analysis_memory_read.v1"
    asset: str
    head_version: int = Field(ge=1)
    state: AnalysisStateView
    canonical_chain: list[AnalysisStateView] = Field(default_factory=list)


class CandidateStatePage(SchemaModel):
    schema_version: Literal["analysis_memory_read.v1"] = "analysis_memory_read.v1"
    asset: str
    data: list[AnalysisStateView]
    pagination: PaginationMeta


class ContextBlockMetadata(SchemaModel):
    name: str
    utf8_bytes: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    trim_reasons: list[str] = Field(default_factory=list)
    retained_evidence_ids: list[str] = Field(default_factory=list)


class ContextBundleMetadata(SchemaModel):
    schema_version: str
    bundle_id: str
    content_hash: str
    asset: str
    run_id: str
    canonical_state_id: str
    cutoff_at: datetime
    assembled_at: datetime
    budget_tokens: int = Field(gt=0)
    estimated_tokens: int = Field(ge=0)
    total_utf8_bytes: int = Field(ge=0)
    within_budget: bool
    blocks: list[ContextBlockMetadata]
    freshness: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    alignment: dict[str, Any] = Field(default_factory=dict)
    evidence_cursors: dict[str, Any] = Field(default_factory=dict)
    next_evidence_cursors: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    artifact_path: str


class ContextBundleMetadataPage(SchemaModel):
    schema_version: Literal["analysis_memory_read.v1"] = "analysis_memory_read.v1"
    asset: str
    data: list[ContextBundleMetadata]
    pagination: PaginationMeta


class CandidateReviewRequest(SchemaModel):
    action: Literal["accept"]
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=1, max_length=255)
    expected_canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=1)

    @field_validator(
        "actor",
        "reason",
        "request_id",
        "expected_canonical_state_id",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ReviewArtifactView(SchemaModel):
    artifact_id: str
    artifact_type: Literal["analysis_state_review"] = "analysis_state_review"
    candidate_state_id: str
    accepted_state_id: str
    transition_id: str
    actor: str
    reason: str
    request_id: str
    artifact_path: str
    content_hash: str
    sha256: str
    created_at: datetime | None = None


class CandidateReviewResponse(SchemaModel):
    schema_version: Literal["analysis_memory_review.v1"] = "analysis_memory_review.v1"
    disposition: Literal["canonical_accepted"]
    canonical_state: AnalysisStateView
    head_version: int = Field(ge=1)
    review_artifact: ReviewArtifactView

    @model_validator(mode="after")
    def validate_review_binding(self) -> "CandidateReviewResponse":
        if self.canonical_state.state_kind != "accepted_canonical":
            raise ValueError("review response must contain accepted canonical state")
        if self.review_artifact.accepted_state_id != self.canonical_state.state_id:
            raise ValueError("review artifact must bind the accepted canonical state")
        return self
