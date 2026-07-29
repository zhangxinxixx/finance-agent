"""Immutable, audit-ready input contract for the daily XAUUSD policy chain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FreshnessStatus = Literal["fresh", "stale", "missing"]
QualityStatus = Literal["accepted", "observe", "blocked"]
AlignmentStatus = Literal["aligned", "misaligned", "unknown"]
AnalysisReadiness = Literal["ready", "observe", "blocked"]


class FrozenContract(BaseModel):
    """Base configuration for formal policy inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReference(FrozenContract):
    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    retrieved_at: datetime


class VariableObservation(FrozenContract):
    """A single named, time-bound input variable.

    ``value`` is deliberately optional: unavailable data is represented explicitly
    through the quality fields, never inferred from a fabricated value.
    """

    series_id: str = Field(min_length=1)
    market_role: str = Field(min_length=1)
    value: float | None
    unit: str = Field(min_length=1)
    as_of: datetime
    expected_frequency: str = Field(min_length=1)
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_explicit_missing_semantics(self) -> "VariableObservation":
        if self.freshness_status == "missing" and self.value is not None:
            raise ValueError("missing observations must set value to None")
        if self.value is None and self.freshness_status != "missing":
            raise ValueError("a null value must be explicitly marked missing")
        return self


class OfficialEvent(FrozenContract):
    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    occurred_at: datetime
    reaction_window_end: datetime | None = None
    reaction_summary: str | None = None
    reaction_asset: Literal["XAUUSD"] | None = None
    reaction_return_pct: float | None = None
    reaction_status: Literal["confirmed", "observe", "unconfirmed"] = "unconfirmed"
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    reaction_source_refs: tuple[SourceReference, ...] = ()

    @model_validator(mode="after")
    def _require_structured_confirmed_reaction(self) -> "OfficialEvent":
        if self.reaction_status == "confirmed" and (
            self.reaction_window_end is None
            or self.reaction_asset != "XAUUSD"
            or self.reaction_return_pct is None
            or not self.reaction_summary
            or not self.reaction_source_refs
        ):
            raise ValueError("confirmed events require a complete structured XAUUSD reaction window")
        return self


class OfficialEventSnapshot(FrozenContract):
    """Official-event input and its own data passport."""

    events: tuple[OfficialEvent, ...]
    as_of: datetime
    expected_frequency: str = Field(min_length=1)
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)


class DataQualitySnapshot(FrozenContract):
    freshness_status: FreshnessStatus
    completeness_status: Literal["complete", "partial", "missing"]
    alignment_status: AlignmentStatus
    analysis_readiness: AnalysisReadiness


class FeatureSnapshotInput(FrozenContract):
    """Hashable policy payload before the deterministic identity is attached."""

    schema_version: Literal["feature_snapshot.v1"]
    asset: Literal["XAUUSD"]
    scope: Literal["daily_close"]
    as_of: datetime
    xauusd_spot: VariableObservation
    gc_futures: VariableObservation
    us02y: VariableObservation
    us10y: VariableObservation
    us30y: VariableObservation
    t10yie: VariableObservation
    real10y: VariableObservation
    broad_dollar: VariableObservation
    wti: VariableObservation
    brent: VariableObservation
    etf_flow: VariableObservation
    cot: VariableObservation
    cme_options_regime: VariableObservation
    official_events: OfficialEventSnapshot

    @model_validator(mode="after")
    def _enforce_canonical_series_and_market_roles(self) -> "FeatureSnapshotInput":
        required = {
            "xauusd_spot": ("XAUUSD_SPOT", "spot"),
            "gc_futures": ("GC_FUTURES", "futures"),
            "us02y": ("US02Y", "yield"),
            "us10y": ("US10Y", "yield"),
            "us30y": ("US30Y", "yield"),
            "t10yie": ("T10YIE", "breakeven_inflation"),
            "real10y": ("DFII10", "real_yield"),
            "broad_dollar": ("DTWEXBGS", "broad_dollar"),
            "wti": ("WTI", "oil"),
            "brent": ("BRENT", "oil"),
            "etf_flow": ("GOLD_ETF_FLOW", "flow"),
            "cot": ("GOLD_COT", "positioning"),
            "cme_options_regime": ("CME_GC_OPTIONS_REGIME", "options_regime"),
        }
        for field_name, (series_id, market_role) in required.items():
            observation = getattr(self, field_name)
            if observation.series_id != series_id or observation.market_role != market_role:
                raise ValueError(
                    f"{field_name} must use series_id={series_id} and market_role={market_role}"
                )
        return self


class FeatureSnapshot(FeatureSnapshotInput):
    """Formal immutable FeatureSnapshot including deterministic identity fields."""

    data_quality: DataQualitySnapshot
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=1)
