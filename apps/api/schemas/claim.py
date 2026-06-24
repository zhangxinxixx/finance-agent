"""Claim and claim-review schemas for agent output governance."""

from __future__ import annotations

import enum

from pydantic import Field

from .common import SchemaModel
from .source_trace import ArtifactRef, SourceRef


class ClaimType(str, enum.Enum):
    market_view = "market_view"
    data_fact = "data_fact"
    causal_inference = "causal_inference"
    strategy_condition = "strategy_condition"
    risk_warning = "risk_warning"


class ClaimReviewVerdict(str, enum.Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    contradicted = "contradicted"
    insufficient_evidence = "insufficient_evidence"


class Claim(SchemaModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    source_refs: list[SourceRef] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef | SourceRef] = Field(default_factory=list)
    confidence: float = 0.0


class ClaimReview(SchemaModel):
    claim_id: str
    verdict: ClaimReviewVerdict
    reason: str
    conflicting_refs: list[ArtifactRef | SourceRef] = Field(default_factory=list)
    suggested_action: str | None = None
    reviewer_agent_id: str | None = None


Claim.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
ClaimReview.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
