"""Strategy card schemas."""

from __future__ import annotations

from pydantic import Field

from .common import ReviewStatus, SchemaModel, TraceableResponse
from .source_trace import ArtifactRef, SourceRef


class StrategyCard(TraceableResponse):
    strategy_card_id: str
    symbol: str
    trading_date: str
    bias: str
    market_regime: str | None = None
    confidence: float | None = None
    main_scenario: str | None = None
    alternative_scenarios: list[str] = Field(default_factory=list)
    key_levels: list[dict] = Field(default_factory=list)
    trigger_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    confirmation_conditions: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    report_refs: list[str] = Field(default_factory=list)
    module_signals: list[dict] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.not_required
    replay_status: str | None = None


class StrategyAssetSummary(SchemaModel):
    asset: str
    sample_size: int = 0
    latest_trade_date: str | None = None
    latest_run_id: str | None = None
    latest_snapshot_id: str | None = None
    regime_counts: list["StrategyRegimeSummary"] = Field(default_factory=list)


class StrategyRegimeSummary(SchemaModel):
    market_regime: str
    sample_size: int = 0


class StrategyAssetListResponse(SchemaModel):
    items: list[StrategyAssetSummary] = Field(default_factory=list)
    count: int = 0


StrategyAssetSummary.model_rebuild(_types_namespace={"StrategyRegimeSummary": StrategyRegimeSummary})
StrategyCard.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef, "StrategyRegimeSummary": StrategyRegimeSummary})
