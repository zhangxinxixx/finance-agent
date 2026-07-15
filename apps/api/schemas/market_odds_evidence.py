from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import SchemaModel


class MarketOddsEvidenceGroup(SchemaModel):
    group_key: str
    label: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class MarketOddsAnalysisContext(SchemaModel):
    source: Literal["accepted_agent_analysis", "deterministic_fallback"]
    quality_status: Literal["accepted", "unavailable"]
    structure_summary: str
    gold_implication: str
    confirmation_variables: list[str] = Field(default_factory=list)


class MarketOddsEvidenceViewModel(SchemaModel):
    article_id: str
    report_id: str
    trade_date: str
    as_of: str
    source_role: Literal["supplemental_source"] = "supplemental_source"
    source_verification_status: str
    extraction_status: str
    panel_count: int
    groups: list[MarketOddsEvidenceGroup] = Field(default_factory=list)
    interpretation: dict[str, Any] = Field(default_factory=dict)
    analysis_context: MarketOddsAnalysisContext
    internal_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    parser_version: str
    feature_schema_version: str
