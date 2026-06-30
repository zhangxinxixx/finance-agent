"""Report summary/detail schemas for standardized artifacts and read models."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .claim import Claim, ClaimReview
from .common import DataStatus, ReportLifecycleStatus, ReviewStatus, SchemaModel, TraceableResponse
from .review import ReviewItem
from .source_trace import ArtifactRef, SnapshotRef, SourceRef


class ReportArtifact(ArtifactRef):
    label: str | None = None
    content_type: str | None = None
    report_id: str | None = None
    is_primary: bool = False


class ReportSummary(TraceableResponse):
    report_id: str
    family: str
    title: str
    asset: str | None = None
    trade_date: str | None = None
    lifecycle_status: ReportLifecycleStatus = ReportLifecycleStatus.generated
    review_status: ReviewStatus = ReviewStatus.not_required
    generated_at: datetime | None = None


class ReportDetail(ReportSummary):
    artifacts: list[ReportArtifact] = Field(default_factory=list)
    input_snapshot_ids: list[str] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    structured_payload: dict | None = None
    gold_macro_overview: dict | None = None


class ReportDeterministicInput(SchemaModel):
    input_id: str
    input_type: str
    title: str
    data_status: DataStatus = DataStatus.live
    snapshot: SnapshotRef | None = None
    sections: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    payload: dict | None = None


class ReportAnalysisAgentOutput(SchemaModel):
    agent_output_id: str
    registry_id: str | None = None
    agent_name: str
    display_name: str
    role: str
    module: str
    version: str
    run_id: str | None = None
    snapshot_id: str | None = None
    status: str
    bias: str
    confidence: float
    summary: str = ""
    summary_zh: str = ""
    key_findings: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    invalid_conditions: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    claim_reviews: list[ClaimReview] = Field(default_factory=list)
    claim_count: int = 0
    fact_review_status: str | None = None
    prompt_version: str | None = None
    generated_by: str | None = None
    llm_model: str | None = None
    created_at: datetime | None = None


class ReportAnalysisInputs(TraceableResponse):
    report_id: str
    family: str | None = None
    title: str | None = None
    asset: str | None = None
    trade_date: str | None = None
    deterministic_inputs: list[ReportDeterministicInput] = Field(default_factory=list)
    agent_outputs: list[ReportAnalysisAgentOutput] = Field(default_factory=list)
    fact_reviews: list[ReportAnalysisAgentOutput] = Field(default_factory=list)
    synthesis_outputs: list[ReportAnalysisAgentOutput] = Field(default_factory=list)


ReportSummary.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
ReportDetail.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef, "SnapshotRef": SnapshotRef})
ReportDeterministicInput.model_rebuild(
    _types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef, "SnapshotRef": SnapshotRef}
)
ReportAnalysisAgentOutput.model_rebuild(
    _types_namespace={
        "SourceRef": SourceRef,
        "ArtifactRef": ArtifactRef,
        "SnapshotRef": SnapshotRef,
        "Claim": Claim,
        "ClaimReview": ClaimReview,
    }
)
ReportAnalysisInputs.model_rebuild(
    _types_namespace={
        "SourceRef": SourceRef,
        "ArtifactRef": ArtifactRef,
        "SnapshotRef": SnapshotRef,
        "Claim": Claim,
        "ClaimReview": ClaimReview,
    }
)
