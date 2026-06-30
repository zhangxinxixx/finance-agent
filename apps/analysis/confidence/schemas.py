from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceKernel(BaseModel):
    """Central confidence breakdown used by research decision surfaces."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    data_confidence: float = Field(ge=0.0, le=1.0)
    freshness_confidence: float = Field(ge=0.0, le=1.0)
    evidence_confidence: float = Field(ge=0.0, le=1.0)
    cross_source_confidence: float = Field(ge=0.0, le=1.0)
    conflict_penalty: float = Field(ge=0.0, le=1.0)
    model_dependency_penalty: float = Field(ge=0.0, le=1.0)
    regime_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)
    caps: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
