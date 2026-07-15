from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.agents import AgentOutput


class ReportSection(BaseModel):
    """One renderer-ready section for the final research report."""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    source_refs: list[dict[str, Any]]


class FinalReportOutput(BaseModel):
    """Renderer-facing final report output contract.

    This schema validates an already-computed report payload only. It does not
    write files, call workers, read raw/parsed data, or render Markdown/JSON.
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    asset: str
    trade_date: str
    run_id: str
    snapshot_id: str
    input_snapshot_ids: dict[str, Any]
    source_refs: list[dict[str, Any]]
    coordinator_output: AgentOutput
    sections: list[ReportSection] = Field(min_length=1)
    risk_disclosures: list[str]
    created_at: datetime

    @model_validator(mode="after")
    def _require_lineage(self) -> FinalReportOutput:
        missing = [key for key in ("analysis_snapshot", "coordinator") if key not in self.input_snapshot_ids]
        if missing:
            raise ValueError(f"input_snapshot_ids must include lineage keys: {', '.join(missing)}")
        return self


# ── P4-04: Structured Report contract ────────────────────────────────────


class StructuredReportSection(BaseModel):
    """One structured section in the final report JSON output.

    Each section corresponds to a logical unit of the research report:
    summary, macro logic, options structure, market odds, conflicts,
    scenarios, risks, data quality, and provenance.
    """

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(description="Machine-readable section key, e.g. 'one_line_summary'")
    title: str = Field(description="Human-readable section title")
    body: str = Field(description="Section content (deterministic, no LLM)")
    status: str = Field(default="ok", description="ok | partial | unavailable")
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    data_category: str = Field(default="confirmed_data", description="confirmed_data | external_opinion | system_inference")


class StructuredReportVersion(BaseModel):
    """Report version metadata for traceability and diff support."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(description="Unique report identifier: <asset>:<trade_date>:<run_id>:final_report")
    report_type: str = Field(default="structured_final_report")
    report_version: str = Field(default="1.0.0")
    snapshot_id: str
    run_id: str
    trade_date: str
    created_at: datetime
    source_agent_outputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of {agent_name, module, version, bias, confidence} for each contributing agent",
    )
    is_final: bool = Field(default=True)
    status: str = Field(default="generated", description="generated | draft | superseded")


class StructuredReportOutput(BaseModel):
    """Structured final report JSON output (P4-04).

    A deterministic, machine-readable complement to the Markdown report.
    Produced by the same renderer pipeline from the same domain agent outputs,
    without LLM, network, or file reads.
    """

    model_config = ConfigDict(extra="forbid")

    version: StructuredReportVersion
    sections: list[StructuredReportSection] = Field(min_length=1)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    risk_disclosures: list[str] = Field(default_factory=list)


class MacroEventFollowupStructuredPayload(BaseModel):
    """Structured payload for non-trading-day macro event follow-up reports."""

    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(default="macro_event_followup")
    trade_date: str
    anchor_trade_date: str
    anchor_report_refs: list[dict[str, Any]]
    new_macro_events: list[dict[str, Any]]
    impact_assessment: dict[str, Any]
    watch_items: list[dict[str, Any]]
    revision_risk: dict[str, Any]
    source_refs: list[dict[str, Any]]

    @model_validator(mode="after")
    def _require_followup_type(self) -> MacroEventFollowupStructuredPayload:
        if self.report_type != "macro_event_followup":
            raise ValueError("report_type must be macro_event_followup")
        return self


class WeeklyContextRevisionAnchor(BaseModel):
    """Immutable Jin10 weekly report used as the revision baseline."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    report_date: str
    run_id: str
    title: str
    baseline_quality_status: str
    baseline_artifact_refs: list[dict[str, Any]] = Field(min_length=1)


class WeeklyClaimRevision(BaseModel):
    """One evidence-bound change to a claim from the weekly baseline."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    original_claim: str
    action: Literal["maintain", "strengthen", "weaken", "invalidate", "pending"]
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_before: Literal["low", "medium", "high"]
    confidence_after: Literal["low", "medium", "high"]


class WeeklyContextRevisionPayload(BaseModel):
    """Append-only overlay that revises one immutable Jin10 weekly analysis."""

    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(default="weekly_context_revision")
    schema_version: str = Field(default="1.0.0")
    asset: str
    trade_date: str
    run_id: str
    context_as_of: str
    anchor: WeeklyContextRevisionAnchor
    input_snapshot_ids: dict[str, Any]
    freshness: dict[str, dict[str, Any]]
    baseline_claims: list[dict[str, Any]] = Field(min_length=1)
    new_evidence: list[dict[str, Any]]
    claim_revisions: list[WeeklyClaimRevision] = Field(min_length=1)
    executive_summary: str
    confirmation_matrix: dict[str, dict[str, Any]]
    positioning_check: dict[str, Any]
    dominant_transmission_chain: dict[str, Any]
    scenario_updates: list[dict[str, Any]]
    watch_items: list[dict[str, Any]]
    revision_risk: dict[str, Any]
    quality_status: Literal["accepted", "needs_review", "blocked"]
    publication_status: Literal["accepted", "observe"]
    publish_allowed: bool
    analysis_provenance: dict[str, Any]
    source_refs: list[dict[str, Any]]

    @model_validator(mode="after")
    def _require_revision_invariants(self) -> WeeklyContextRevisionPayload:
        if self.report_type != "weekly_context_revision":
            raise ValueError("report_type must be weekly_context_revision")
        if self.publish_allowed != (self.publication_status == "accepted"):
            raise ValueError("publish_allowed must match publication_status")
        if self.publish_allowed and self.quality_status != "accepted":
            raise ValueError("only accepted revisions may be published")
        return self
