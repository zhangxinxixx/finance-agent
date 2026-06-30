from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceDirection = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]


class EvidenceItem(BaseModel):
    """Structured evidence factor for downstream reducers and decisions."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    factor: str
    direction: EvidenceDirection
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    source_tier: str
    source_refs: list[dict[str, Any]]
    data_category: str
    invalidation_hint: str | None = None
    notes: str | None = None
