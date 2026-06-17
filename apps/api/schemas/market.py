"""Market chart context schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import TraceableResponse
from .source_trace import ArtifactRef, SourceRef


class MarketChartContext(TraceableResponse):
    symbol: str
    timeframe: str
    quote: dict[str, Any] = Field(default_factory=dict)
    candles: list[dict[str, Any]] = Field(default_factory=list)
    levels: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    strategy_zones: list[dict[str, Any]] = Field(default_factory=list)


MarketChartContext.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
