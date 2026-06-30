from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModuleState(BaseModel):
    """Normalized state for one decision-input module."""

    model_config = ConfigDict(extra="forbid")

    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class SourceQualitySummary(BaseModel):
    """Lightweight quality summary derived from snapshot source refs."""

    model_config = ConfigDict(extra="forbid")

    total_refs: int
    sources: list[str]
    missing_source_count: int


class DataCompletenessSummary(BaseModel):
    """Module coverage summary for decision input readiness."""

    model_config = ConfigDict(extra="forbid")

    total_modules: int
    available_count: int
    unavailable_count: int
    coverage_ratio: float
    available_modules: list[str]
    unavailable_modules: list[str]


class MarketState(BaseModel):
    """Typed decision-input layer rebuilt from an AnalysisSnapshot dict."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    asset: str
    trade_date: str
    run_id: str
    snapshot_id: str
    macro: ModuleState
    options: ModuleState
    technical: ModuleState
    positioning: ModuleState
    news: ModuleState
    market_odds: ModuleState
    source_quality: SourceQualitySummary
    data_completeness: DataCompletenessSummary
    unavailable_modules: list[str]
    source_refs: list[dict[str, Any]]
    input_snapshot_ids: dict[str, Any]
