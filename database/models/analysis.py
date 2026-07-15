"""分析持久化模型：AnalysisSnapshot、AgentOutput、FinalAnalysisResult。

使用独立的便携 AnalysisBase（不依赖 PostgreSQL UUID 类型）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


JSONB_COMPAT = JSON().with_variant(JSONB, "postgresql")


class AnalysisBase(DeclarativeBase):
    """Portable base for analysis tables — works on SQLite and PostgreSQL."""

    pass


class AnalysisSnapshot(AnalysisBase):
    """Persist unified premarket_snapshot.json."""

    __tablename__ = "analysis_snapshots"
    __table_args__ = (
        UniqueConstraint("asset", "trade_date", "run_id", "snapshot_id", name="uq_analysis_snapshot"),
        Index("ix_analysis_snapshot_asset_date", "asset", "trade_date"),
        Index("ix_analysis_snapshot_run_id", "run_id"),
        Index("ix_analysis_snapshot_snapshot_id", "snapshot_id"),
        Index("ix_analysis_snapshot_payload_gin", "payload", postgresql_using="gin"),
        Index("ix_analysis_snapshot_source_refs_gin", "source_refs", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")

    # JSONB on PostgreSQL, JSON/TEXT fallback on SQLite.
    input_snapshot_ids: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)

    # Optional module payloads
    macro: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    options: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    positioning: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    news: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    technical: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # FK relationships
    agent_outputs: Mapped[list["AgentOutput"]] = relationship(
        back_populates="analysis_snapshot", cascade="all, delete-orphan"
    )
    final_results: Mapped[list["FinalAnalysisResult"]] = relationship(
        back_populates="analysis_snapshot", cascade="all, delete-orphan"
    )


class AgentOutput(AnalysisBase):
    """Persist C3 pseudo-agent outputs, including coordinator."""

    __tablename__ = "agent_outputs"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "agent_name", "module", "version", name="uq_agent_output"),
        Index("ix_agent_output_asset_date", "asset", "trade_date"),
        Index("ix_agent_output_run_id", "run_id"),
        Index("ix_agent_output_snapshot_id", "snapshot_id"),
        Index("ix_agent_output_agent_name", "agent_name"),
        Index("ix_agent_output_module", "module"),
        Index("ix_agent_output_status", "status"),
        Index("ix_agent_output_payload_gin", "payload", postgresql_using="gin"),
        Index("ix_agent_output_source_refs_gin", "source_refs", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_snapshot_db_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_snapshots.id"), nullable=True, index=True
    )
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    bias: Mapped[str] = mapped_column(String(32), nullable=False)

    # NUMERIC(5,4) → Float (portable)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # JSONB on PostgreSQL, JSON/TEXT fallback on SQLite.
    input_snapshot_ids: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    key_findings: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    risk_points: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    watchlist: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    invalid_conditions: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)

    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # LLM metadata (nullable — C3 agents don't use LLM)
    token_usage: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Prompt governance (P2-11) — which prompt version produced this output
    prompt_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("prompt_versions.id"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # FK relationship
    analysis_snapshot: Mapped["AnalysisSnapshot"] = relationship(back_populates="agent_outputs")
    prompt_version: Mapped["PromptVersion | None"] = relationship("PromptVersion")


class LLMCallAudit(AnalysisBase):
    """Append-only audit record for one shared-gateway LLM invocation.

    Request payloads are sanitized before they reach this model. In particular,
    API credentials are never included and image data URLs are replaced by
    deterministic hash/size metadata.
    """

    __tablename__ = "llm_call_audits"
    __table_args__ = (
        Index("ix_llm_call_audit_created_at", "created_at"),
        Index("ix_llm_call_audit_status", "status"),
        Index("ix_llm_call_audit_provider_model", "provider_resolved", "model_resolved"),
        Index("ix_llm_call_audit_run_id", "run_id"),
        Index("ix_llm_call_audit_report_id", "report_id"),
        Index("ix_llm_call_audit_trade_date", "trade_date"),
        Index("ix_llm_call_audit_context_gin", "context", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    caller: Mapped[str] = mapped_column(String(255), nullable=False, default="unknown")
    provider_requested: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_resolved: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_requested: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_resolved: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort_requested: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reasoning_effort_resolved: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_config: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    request_messages: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )


class FinalAnalysisResult(AnalysisBase):
    """Persist canonical final report / strategy card / run summaries index."""

    __tablename__ = "final_analysis_results"
    __table_args__ = (
        UniqueConstraint("asset", "trade_date", "run_id", name="uq_final_analysis"),
        Index("ix_final_analysis_asset_date", "asset", "trade_date"),
        Index("ix_final_analysis_run_id", "run_id"),
        Index("ix_final_analysis_snapshot_id", "snapshot_id"),
        Index("ix_final_analysis_bias", "final_bias"),
        Index("ix_final_analysis_payload_gin", "payload", postgresql_using="gin"),
        Index("ix_final_analysis_source_refs_gin", "source_refs", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    analysis_snapshot_db_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analysis_snapshots.id"), nullable=True, index=True
    )

    final_bias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # NUMERIC(5,4) → Float (portable)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scenario_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_trade_instruction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # JSONB on PostgreSQL, JSON/TEXT fallback on SQLite.
    input_snapshot_ids: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    source_agent_outputs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    risk_points: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    watchlist: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    invalid_conditions: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)

    strategy_card: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    run_summaries: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False)

    # File paths to artifacts
    final_report_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    strategy_card_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    strategy_card_md_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    run_summary_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Content hashes
    final_report_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_card_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # FK relationship
    analysis_snapshot: Mapped["AnalysisSnapshot"] = relationship(back_populates="final_results")


class DataSourceStatus(AnalysisBase):
    """Unified data source status for ingestion/dashboard observability.

    Tracks configured / raw_ingested / parsed / analysis_ready independently.
    Portable model — works on SQLite and PostgreSQL.
    """

    __tablename__ = "data_source_status"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_data_source_source_key"),
        Index("ix_data_source_status_source_key", "source_key"),
        Index("ix_data_source_status_status", "status"),
        Index("ix_data_source_status_source_group", "source_group"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_method: Mapped[str | None] = mapped_column(String(64), nullable=True)

    configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_ingested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analysis_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    latest_raw_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_parsed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_connected")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_run_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_metadata: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MacroObservation(AnalysisBase):
    """Queryable macro observation fact table derived from collected MacroPoint rows."""

    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint("source_key", "symbol", "observation_date", name="uq_macro_observation_source_symbol_date"),
        Index("ix_macro_observations_source_symbol_date", "source_key", "symbol", "observation_date"),
        Index("ix_macro_observations_symbol_date", "symbol", "observation_date"),
        Index("ix_macro_observations_run_id", "run_id"),
        Index("ix_macro_observations_observation_date", "observation_date"),
        Index("ix_macro_observations_source_refs_gin", "source_refs", postgresql_using="gin"),
        Index("ix_macro_observations_metadata_gin", "metadata", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, doc="Collector/source key, e.g. fred or openbb_fred")
    symbol: Mapped[str] = mapped_column(String(128), nullable=False, doc="Macro or market symbol")
    observation_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Observation date")
    value: Mapped[float | None] = mapped_column(Float, nullable=True, doc="Observed numeric value")
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True, doc="Optional display/unit label")
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True, doc="Optional observation frequency")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Source endpoint or public URL")
    raw_path: Mapped[str | None] = mapped_column(String(512), nullable=True, doc="Raw artifact path when available")
    raw_artifact_id: Mapped[str | None] = mapped_column(String(255), nullable=True, doc="Registered raw artifact id when available")
    parsed_artifact_id: Mapped[str | None] = mapped_column(String(255), nullable=True, doc="Registered parsed artifact id when available")
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, doc="Collection timestamp")
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, doc="Producing run id")
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    observation_metadata: Mapped[dict] = mapped_column("metadata", JSONB_COMPAT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FeatureSnapshot(AnalysisBase):
    """Queryable feature snapshot table for generated feature-layer JSON artifacts."""

    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_feature_snapshots_snapshot_id"),
        UniqueConstraint(
            "domain",
            "snapshot_kind",
            "asset",
            "trade_date",
            "run_id",
            name="uq_feature_snapshots_domain_kind_asset_date_run",
        ),
        Index("ix_feature_snapshots_domain_asset_date", "domain", "asset", "trade_date"),
        Index("ix_feature_snapshots_run_id", "run_id"),
        Index("ix_feature_snapshots_status", "status"),
        Index("ix_feature_snapshots_payload_gin", "payload", postgresql_using="gin"),
        Index("ix_feature_snapshots_source_refs_gin", "source_refs", postgresql_using="gin"),
        Index("ix_feature_snapshots_metadata_gin", "metadata", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False, doc="Stable feature snapshot id")
    domain: Mapped[str] = mapped_column(String(64), nullable=False, doc="Feature domain, e.g. macro")
    snapshot_kind: Mapped[str] = mapped_column(
        String(64), nullable=False, default="snapshot", doc="Feature artifact kind"
    )
    asset: Mapped[str] = mapped_column(String(32), nullable=False, default="XAUUSD")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Feature snapshot date")
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, doc="Producing run id")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    input_snapshot_ids: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    feature_metadata: Mapped[dict] = mapped_column("metadata", JSONB_COMPAT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DailySourceHealthSnapshot(AnalysisBase):
    """Persist a daily source-health snapshot derived from DataSourceStatus."""

    __tablename__ = "daily_source_health_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_daily_source_health_snapshot_date"),
        Index("ix_daily_source_health_snapshot_date", "snapshot_date"),
        Index("ix_daily_source_health_snapshot_status", "overall_status"),
        Index("ix_daily_source_health_payload_gin", "payload", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNAVAILABLE")
    counts: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    stale_sources: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["DailySourceHealthItem"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class DailySourceHealthItem(AnalysisBase):
    """Persist one source row within a daily source-health snapshot."""

    __tablename__ = "daily_source_health_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "source_key", name="uq_daily_source_health_item_source"),
        Index("ix_daily_source_health_item_snapshot_id", "snapshot_id"),
        Index("ix_daily_source_health_item_source_key", "source_key"),
        Index("ix_daily_source_health_item_group", "source_group"),
        Index("ix_daily_source_health_item_data_status", "data_status"),
        Index("ix_daily_source_health_item_payload_gin", "payload", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("daily_source_health_snapshots.id"), nullable=False, index=True
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unavailable")
    freshness_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parsed_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feature_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    analysis_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latest_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    snapshot: Mapped["DailySourceHealthSnapshot"] = relationship(back_populates="items")


class MarketCandle(AnalysisBase):
    """Portable market candle history for Market Monitor price charts."""

    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("asset", "timeframe", "open_time", "source", name="uq_market_candle"),
        Index("ix_market_candle_asset_timeframe_open_time", "asset", "timeframe", "open_time"),
        Index("ix_market_candle_timeframe", "timeframe"),
        Index("ix_market_candle_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Jin10FlashMessage(AnalysisBase):
    """持久化 Jin10 快讯消息表，增量光标拉取，支持断点续拉和排程分析。

    每条快讯以 Jin10 MCP 返回的 id 为业务唯一键，
    按 `created_at` 降序拉取增量（cursor-based），
    key_event 消息自动触发分析任务入队到 task_runs。
    """

    __tablename__ = "jin10_flash_messages"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_jin10_flash_message_id"),
        Index("ix_jin10_flash_time", "message_time"),
        Index("ix_jin10_flash_key_event", "is_key_event"),
        Index("ix_jin10_flash_importance", "importance"),
        Index("ix_jin10_flash_processed", "analysis_processed"),
        Index("ix_jin10_flash_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(128), nullable=False, doc="Jin10 MCP 消息唯一 ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, doc="消息正文")
    message_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="消息原始时间"
    )

    # 分类结果
    is_key_event: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    signal_tags: Mapped[str | None] = mapped_column(Text, nullable=True, doc="逗号分隔的信号标签")
    content_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="flash",
        doc="内容类型：flash=市场快讯, article=中篇报道, report=长文/报告, calendar=日历事件"
    )

    # 分类来源
    classification_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    filter_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 原始数据
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True, doc="MCP 返回原始 JSON")

    # 分析状态
    analysis_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analysis_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, doc="关联的 task_runs.id")
    analysis_result: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Agent 分析结果摘要")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FlashCursorState(AnalysisBase):
    """记录 Jin10 快讯拉取的光标状态，用于断点续拉。"""

    __tablename__ = "flash_cursor_state"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_flash_cursor_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, default="jin10_mcp_flash")
    latest_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_message_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fetch_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AppSetting(AnalysisBase):
    """Auditable app-level settings overlay for non-sensitive configuration writes."""

    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("setting_key", name="uq_app_settings_setting_key"),
        Index("ix_app_settings_scope", "scope"),
        Index("ix_app_settings_source_key", "source_key"),
        Index("ix_app_settings_value_json_gin", "value_json", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value_json: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    update_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AppSecret(AnalysisBase):
    """Encrypted secret storage for settings-managed API keys."""

    __tablename__ = "app_secrets"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_app_secrets_source_key"),
        Index("ix_app_secrets_source_key", "source_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(64), nullable=False, default="api_key")
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    masked_value: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    update_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AppSettingEvent(AnalysisBase):
    """Append-only audit log for settings writes and resets."""

    __tablename__ = "app_setting_events"
    __table_args__ = (
        Index("ix_app_setting_events_setting_key", "setting_key"),
        Index("ix_app_setting_events_scope", "scope"),
        Index("ix_app_setting_events_source_key", "source_key"),
        Index("ix_app_setting_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value_json: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    new_value_json: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromptVersion(AnalysisBase):
    """Versioned prompt templates for agent governance (P2-11).

    Each agent can have multiple prompt versions; only one is active at a time.
    Every AgentOutput run records which prompt_version_id was used, enabling
    full traceability and rollback without overwriting history.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_prompt_versions_agent_version"),
        Index("ix_prompt_versions_agent_id", "agent_id"),
        Index("ix_prompt_versions_status", "status"),
        Index("ix_prompt_versions_enabled", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    prompt_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_template: Mapped[dict] = mapped_column(JSONB_COMPAT, nullable=False, default=dict)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    model_routing: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReviewItem(AnalysisBase):
    """Unified review queue item for low-confidence or failed pipeline outputs."""

    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("review_id", name="uq_review_items_review_id"),
        Index("ix_review_items_status", "status"),
        Index("ix_review_items_run_id", "run_id"),
        Index("ix_review_items_source_module", "source_module"),
        Index("ix_review_items_source_step_id", "source_step_id"),
        Index("ix_review_items_agent_output_id", "agent_output_id"),
        Index("ix_review_items_claim_id", "claim_id"),
        Index("ix_review_items_severity", "severity"),
        Index("ix_review_items_source_refs_gin", "source_refs", postgresql_using="gin"),
        Index("ix_review_items_impact_report_ids_gin", "impact_report_ids", postgresql_using="gin"),
        Index("ix_review_items_evidence_refs_gin", "evidence_refs", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    review_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_module: Mapped[str] = mapped_column(String(64), nullable=False)
    source_step_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_output_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="warning")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    impact_modules: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    impact_report_ids: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    source_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSONB_COMPAT, nullable=False, default=list)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resolution_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolution_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PromptFeedback(AnalysisBase):
    """Human feedback on agent outputs for prompt governance (P2-11).

    Feedback is always added as a new record; historical AgentOutput is never
    modified. Severe feedback can optionally create a ReviewItem for tracking.
    """

    __tablename__ = "prompt_feedback"
    __table_args__ = (
        UniqueConstraint("feedback_id", name="uq_prompt_feedback_feedback_id"),
        Index("ix_prompt_feedback_agent_id", "agent_id"),
        Index("ix_prompt_feedback_agent_output_id", "agent_output_id"),
        Index("ix_prompt_feedback_prompt_version_id", "prompt_version_id"),
        Index("ix_prompt_feedback_status", "status"),
        Index("ix_prompt_feedback_category", "category"),
        Index("ix_prompt_feedback_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feedback_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_output_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="prompt_quality")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_changes: Mapped[dict | None] = mapped_column(JSONB_COMPAT, nullable=True)
    review_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audit_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── Migration helper ──


def ensure_analysis_tables(bind_or_session):
    """Create analysis tables if they don't exist (create_all, works on SQLite and PG).

    Usage:
        ensure_analysis_tables(engine)        # from Engine
        ensure_analysis_tables(session)       # from Session (auto-resolves bind)
    """
    from sqlalchemy.orm import Session as _Session

    bind = bind_or_session
    if isinstance(bind, _Session):
        bind = bind.get_bind()
    # Register auxiliary analysis models before create_all() so metadata includes them.
    from database.models import playbook as _playbook_models  # noqa: F401

    AnalysisBase.metadata.create_all(bind=bind, checkfirst=True)
    _ensure_analysis_columns(bind)


def _ensure_analysis_columns(bind_or_conn) -> None:
    inspector = inspect(bind_or_conn)
    ddl: list[str] = []

    # ── review_items column migrations ──
    if inspector.has_table("review_items"):
        existing = {column["name"] for column in inspector.get_columns("review_items")}
        if "resolution_actor" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN resolution_actor VARCHAR(128)")
        if "resolution_request_id" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN resolution_request_id VARCHAR(128)")
        if "audit_id" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN audit_id VARCHAR(255)")
        if "action_status" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN action_status VARCHAR(64)")
        if "next_run_id" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN next_run_id VARCHAR(255)")
        if "agent_output_id" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN agent_output_id VARCHAR(255)")
        if "claim_id" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN claim_id VARCHAR(255)")
        if "impact_report_ids" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN impact_report_ids JSON")
        if "source_refs" not in existing:
            ddl.append("ALTER TABLE review_items ADD COLUMN source_refs JSON")

    # ── agent_outputs.prompt_version_id migration (P2-11) ──
    if inspector.has_table("agent_outputs"):
        ao_cols = {column["name"] for column in inspector.get_columns("agent_outputs")}
        if "prompt_version_id" not in ao_cols:
            ddl.append("ALTER TABLE agent_outputs ADD COLUMN prompt_version_id VARCHAR(36)")

    # ── jin10_flash_messages.content_type migration ──
    if inspector.has_table("jin10_flash_messages"):
        jf_cols = {column["name"] for column in inspector.get_columns("jin10_flash_messages")}
        if "content_type" not in jf_cols:
            ddl.append("ALTER TABLE jin10_flash_messages ADD COLUMN content_type VARCHAR(16) NOT NULL DEFAULT 'flash'")

    if not ddl:
        return
    if hasattr(bind_or_conn, "begin"):
        with bind_or_conn.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        return
    for statement in ddl:
        bind_or_conn.execute(text(statement))
