from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    invalid_conditions: list[str]
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
    data_quality: list[str] = Field(
        default_factory=list,
        description="Data quality tags: stale_data, proxy_gex, prelim_data, etc.",
    )
    # ── LLM metadata (optional, only for LLM-powered agents) ──
    llm_model: str | None = Field(default=None, description="LLM model used for this analysis")
    llm_provider: str | None = Field(default=None, description="LLM provider name")
    llm_usage: dict[str, Any] | None = Field(default=None, description="Token usage from LLM call")
    llm_latency_ms: int | None = Field(default=None, description="LLM call latency in milliseconds")
    # ── Observability payloads (optional; debug/audit only) ──
    prompt_messages: list[dict[str, str]] | None = Field(
        default=None,
        description="Exact prompt messages sent to the LLM, when this agent uses an LLM",
    )
    input_payload: dict[str, Any] | None = Field(
        default=None,
        description="Structured input payload used by the agent for prompt/output inspection",
    )
    llm_raw_output: str | None = Field(
        default=None,
        description="Raw LLM response text before parsing, when available",
    )
