from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.analysis_policy import (
    GoldAnalysisDecision,
    GoldAnalysisDecisionV2,
)


class AgentBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNAVAILABLE = "unavailable"


class AgentStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class DataCategory(StrEnum):
    """Classification of data provenance for traceability."""
    CONFIRMED_DATA = "confirmed_data"          # Verifiable structured data (FRED, CME raw)
    EXTERNAL_OPINION = "external_opinion"      # LLM/Jin10 generated content
    SYSTEM_INFERENCE = "system_inference"      # Deterministic agent derivations


class AcceptedStateConclusion(BaseModel):
    """Typed Analysis Memory state semantics kept separate from Gold Policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: AgentBias
    direction_tilt: Literal["bullish", "bearish"] | None = None
    state_bias: str = Field(min_length=1, max_length=32)
    market_stage: str = Field(min_length=1, max_length=64)
    core_thesis: str = Field(min_length=1)
    dominant_drivers: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("state_bias", "market_stage", "core_thesis")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("accepted state conclusion text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_direction_semantics(self) -> "AcceptedStateConclusion":
        if self.direction is AgentBias.UNAVAILABLE:
            raise ValueError("accepted state conclusion direction cannot be unavailable")
        expected_direction, expected_tilt = state_bias_direction(self.state_bias)
        if expected_direction is None:
            raise ValueError("state_bias is outside the accepted state vocabulary")
        if expected_direction is not self.direction:
            raise ValueError("state_bias contradicts coarse direction")
        if expected_tilt is not None and self.direction_tilt != expected_tilt:
            raise ValueError("fine state_bias requires matching direction_tilt")
        if expected_tilt is None and self.direction_tilt is not None:
            raise ValueError("direction_tilt is not valid for this state_bias")
        return self


def state_bias_direction(value: str) -> tuple[AgentBias | None, Literal["bullish", "bearish"] | None]:
    normalized = str(value).strip().lower()
    mappings = {
        "mixed_bullish": (AgentBias.MIXED, "bullish"),
        "mixed_bearish": (AgentBias.MIXED, "bearish"),
        "neutral_bullish": (AgentBias.NEUTRAL, "bullish"),
        "neutral_bearish": (AgentBias.NEUTRAL, "bearish"),
        "strong_bullish": (AgentBias.BULLISH, None),
        "strong_bearish": (AgentBias.BEARISH, None),
        "event_risk": (AgentBias.MIXED, None),
    }
    if normalized in mappings:
        return mappings[normalized]
    try:
        return AgentBias(normalized), None
    except ValueError:
        return None, None


class AgentDataGap(BaseModel):
    """Structured current data gap consumed by QualityGate."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: Literal["info", "warning", "p0", "blocker"] = "warning"


class AgentOutput(BaseModel):
    """Unified read-only post-processing output contract for pseudo agents."""

    model_config = ConfigDict(extra="forbid")

    version: str
    agent_name: str
    module: str
    snapshot_id: str
    input_snapshot_ids: dict[str, Any]
    bias: AgentBias
    confidence: float = Field(ge=0.0, le=1.0)
    key_findings: list[str]
    risk_points: list[str]
    watchlist: list[str]
    invalid_conditions: list[str] = Field(
        default_factory=list,
        description="Legacy compatibility projection of invalidation_conditions.",
    )
    invalidation_conditions: list[str] = Field(
        default_factory=list,
        description="Future conditions that would invalidate the analysis; these do not block publication by themselves.",
    )
    active_blockers: list[str] = Field(
        default_factory=list,
        description="Conditions that are active now and must block publication.",
    )
    data_gaps: list[AgentDataGap] = Field(
        default_factory=list,
        description="Current structured data gaps; only p0/blocker gaps directly block publication.",
    )
    review_triggers: list[str] = Field(
        default_factory=list,
        description="Current conditions that require review but are not active publication blockers.",
    )
    summary: str
    source_refs: list[dict[str, Any]]
    status: AgentStatus
    created_at: datetime
    # ── P4-05: Macro regime engine fields (optional, backward-compatible) ──
    market_phase: str | None = Field(
        default=None,
        description=(
            "Macro regime classification: rate_pressure | transition_release | trend_tailwind | "
            "liquidity_crunch | monetary_credit_repricing | unavailable"
        ),
    )
    regime_drivers: dict[str, Any] | None = Field(
        default=None,
        description="Driver evidence for regime classification",
    )
    # ── T4: Data provenance classification ──
    data_category: DataCategory | None = Field(
        default=None,
        description="Data provenance: confirmed_data / external_opinion / system_inference",
    )
    # ── T5: Evidence and quality tracking ──
    evidence_refs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Evidence references pointing to source data supporting this conclusion",
    )
    evidence_items: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Structured evidence factors used by confidence, quality gates, and source trace. "
            "Each item may include factor, direction, strength, confidence, freshness, source_tier, and invalidation_hint."
        ),
    )
    data_quality: list[str] = Field(
        default_factory=list,
        description="Data quality tags: stale_data, proxy_gex, prelim_data, etc.",
    )
    # ── LLM metadata (optional, only for LLM-powered agents) ──
    llm_model: str | None = Field(default=None, description="LLM model used for this analysis")
    llm_provider: str | None = Field(default=None, description="LLM provider name")
    llm_usage: dict[str, Any] | None = Field(default=None, description="Token usage from LLM call")
    llm_latency_ms: int | None = Field(default=None, description="LLM call latency in milliseconds")
    llm_audit_id: str | None = Field(default=None, description="Immutable shared-gateway audit record id")
    # ── Observability payloads (optional; debug/audit only) ──
    prompt_messages: list[dict[str, str]] | None = Field(
        default=None,
        description="Exact prompt messages sent to the LLM, when this agent uses an LLM",
    )
    input_payload: dict[str, Any] | None = Field(
        default=None,
        description="Structured input payload used by the agent for prompt/output inspection",
    )
    accepted_state_conclusion: AcceptedStateConclusion | None = Field(
        default=None,
        description=(
            "Authoritative typed state conclusion; debug input_payload is never authoritative."
        ),
    )
    accepted_gold_analysis_decision: GoldAnalysisDecision | GoldAnalysisDecisionV2 | None = Field(
        default=None,
        description=(
            "Formal deterministic Gold Policy decision; it remains separate from "
            "the Analysis Memory state conclusion contract."
        ),
    )
    llm_raw_output: str | None = Field(
        default=None,
        description="Raw LLM response text before parsing, when available",
    )

    @model_validator(mode="after")
    def _sync_legacy_invalidation_alias(self) -> "AgentOutput":
        combined = _dedupe_strings([*self.invalidation_conditions, *self.invalid_conditions])
        self.invalidation_conditions = combined
        self.invalid_conditions = list(combined)
        return self


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result
