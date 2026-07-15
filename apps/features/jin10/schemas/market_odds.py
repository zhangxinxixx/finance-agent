from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketOddsEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    panel_id: str
    asset: str
    event_type: Literal["price_level", "policy_outcome", "event_outcome"]
    predicate: str
    direction: Literal["up", "down", "neutral", "event"]
    target_value: float | str
    target_unit: str
    horizon_start: str
    horizon_end: str
    timezone: str = "Asia/Shanghai"
    probability: float = Field(ge=0.0, le=1.0)
    probability_raw: str
    probability_semantics: str
    outcome_label: str
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    extraction_status: Literal["accepted", "needs_review", "rejected"]
    validation_flags: list[str] = Field(default_factory=list)
    page_no: int | None = Field(default=None, ge=1)
    figure_id: str | None = None
    bbox: list[int] | None = None
    ocr_text: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def accepted_items_are_anchored(self) -> "MarketOddsEvidenceItem":
        if self.extraction_status == "accepted" and (
            not self.asset
            or not self.horizon_end
            or self.page_no is None
            or not self.figure_id
            or not self.ocr_text
        ):
            raise ValueError("accepted market odds evidence must be semantically complete and figure-anchored")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("bbox must contain four coordinates")
        return self


class Jin10MarketOddsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    feature_id: str
    article_id: str
    report_id: str
    report_type: Literal["market_observation"] = "market_observation"
    published_at: str
    generated_at: str
    source_kind: Literal["jin10_external_market_odds"] = "jin10_external_market_odds"
    data_category: Literal["external_opinion"] = "external_opinion"
    provider_role: Literal["supplemental_source"] = "supplemental_source"
    source_verification_status: Literal["single_source", "multi_source_supported", "conflicted"] = "single_source"
    extraction_status: Literal["accepted", "needs_review", "rejected"]
    parser_version: str
    panel_count: int = Field(ge=0)
    items: list[MarketOddsEvidenceItem] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def panel_count_matches_items(self) -> "Jin10MarketOddsEvidence":
        actual = len({item.panel_id for item in self.items if item.extraction_status != "rejected"})
        if self.panel_count != actual:
            raise ValueError("panel_count must match distinct non-rejected panel ids")
        return self
