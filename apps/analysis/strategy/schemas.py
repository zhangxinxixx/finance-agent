from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.agents import AgentBias


class StrategyCardOutput(BaseModel):
    """Research-only strategy card contract for downstream renderers."""

    model_config = ConfigDict(extra="forbid")

    version: str
    asset: str
    trade_date: str
    run_id: str
    bias: AgentBias
    confidence: float = Field(ge=0.0, le=1.0)
    scenario_summary: str
    key_levels_from_options: list[str]
    risk_points: list[str]
    invalid_conditions: list[str]
    watchlist: list[str]
    trigger_conditions: list[str] = Field(default_factory=list)
    confirmation_conditions: list[str] = Field(default_factory=list)
    market_regime: str | None = None
    source_refs: list[dict[str, Any]]
    input_snapshot_ids: dict[str, Any]
    created_at: datetime
    is_trade_instruction: Literal[False]
    # ── T5: Evidence and quality tracking ──
    evidence_refs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Aggregated evidence references from coordinator and risk outputs",
    )
    data_quality: list[str] = Field(
        default_factory=list,
        description="Aggregated data quality tags from contributing agents",
    )
    data_category_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of data_category counts across source_refs",
    )
    confidence_kernel: dict[str, Any] | None = Field(
        default=None,
        description="Central ConfidenceKernel breakdown propagated from coordinator output",
    )
    gold_macro_conditions: dict[str, Any] | None = Field(
        default=None,
        description="Conditional gold macro signals derived from GoldMacroOverview for strategy gating",
    )

    @model_validator(mode="after")
    def _require_lineage(self) -> StrategyCardOutput:
        missing = [key for key in ("analysis_snapshot", "coordinator") if key not in self.input_snapshot_ids]
        if missing:
            raise ValueError(f"input_snapshot_ids must include lineage keys: {', '.join(missing)}")
        return self
