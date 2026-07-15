"""Schemas for the read-only live strategy ViewModel."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LiveStrategyOutput(BaseModel):
    """Frozen ``live_strategy.v1`` response contract.

    The nested payloads intentionally remain dictionaries: they carry immutable
    references to existing StrategyCard and options-decision read models.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["live_strategy.v1"]
    status: Literal["available", "partial", "unavailable"]
    strategy_id: str
    baseline_strategy_id: str | None
    strategy_version: str
    asset: str
    strategy_status: Literal["WAITING", "WATCHING", "ARMED", "TRIGGERED", "SUSPENDED_DATA"]
    updated_at: str
    update_reason: dict[str, Any]
    baseline: dict[str, Any]
    live_market: dict[str, Any]
    market_state: dict[str, Any]
    feasibility: dict[str, Any]
    active_scenario: Literal["long", "short", "no_trade"] | None
    setups: list[dict[str, Any]]
    no_trade: dict[str, Any]
    event_overlay: dict[str, Any] = Field(default_factory=dict, exclude_if=lambda value: value == {})
    source_refs: list[dict[str, Any]]
    artifact_refs: list[Any]
    data_quality: dict[str, Any]
