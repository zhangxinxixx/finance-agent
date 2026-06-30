from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.analysis.agents.schemas import AgentBias, AgentStatus
from apps.analysis.confidence import ConfidenceKernel

FeasibilityLabel = Literal[
    "not_actionable",
    "research_only",
    "watchlist_candidate",
    "high_conviction_research",
]


class StrategyDecision(BaseModel):
    """Research-only decision object between analysis and rendered artifacts."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    asset: str
    trade_date: str
    run_id: str
    snapshot_id: str
    bias: AgentBias
    status: AgentStatus
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_kernel: ConfidenceKernel
    feasibility_label: FeasibilityLabel
    feasibility_score: float = Field(ge=0.0, le=1.0)
    feasibility_reasons: list[str] = Field(default_factory=list)
    regime_context: str | None = None
    time_horizon: str | None = None
    required_confirmations: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    is_trade_instruction: Literal[False] = False
