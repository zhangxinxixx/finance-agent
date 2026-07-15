"""Adapter that freezes the deterministic ``live_strategy.v1`` read model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .strategy_snapshot import StrategySnapshot, build_strategy_snapshot


def build_strategy_snapshot_from_live_output(
    live_output: Mapping[str, Any],
    *,
    as_of: datetime,
    trade_date: str | None = None,
    run_id: str | None = None,
    account_id: str = "codex-xauusd-shadow",
) -> StrategySnapshot:
    """Freeze a live strategy response without recalculating its decisions."""

    if live_output.get("schema_version") != "live_strategy.v1":
        raise ValueError("live output must use live_strategy.v1")
    asset = str(live_output.get("asset") or "").upper()
    if asset != "XAUUSD":
        raise ValueError("shadow evaluation currently supports only XAUUSD")

    as_of = _as_utc(as_of)
    baseline = _mapping(live_output.get("baseline"))
    market = _mapping(live_output.get("live_market"))
    market_state = _mapping(live_output.get("market_state"))
    feasibility = _mapping(live_output.get("feasibility"))
    quality = _mapping(live_output.get("data_quality"))
    status = str(live_output.get("status") or "unavailable")
    canonical_status = _mapping(quality.get("canonical_candle")).get("status")
    publish_allowed = status == "available" and canonical_status == "available"
    warnings = [str(item) for item in quality.get("warnings") or []]
    quality_gate = {
        "status": "approved" if publish_allowed else "blocked",
        "reason_codes": warnings or (["live_strategy_not_available"] if not publish_allowed else []),
        "strategy_status": live_output.get("strategy_status"),
    }
    setups = [dict(item) for item in live_output.get("setups") or [] if isinstance(item, Mapping)]
    entry_conditions = [
        {
            "setup_id": setup.get("setup_id"),
            "direction": setup.get("direction"),
            "status": setup.get("status"),
            "entry_zone": setup.get("entry_zone"),
            "trigger_conditions": setup.get("trigger_conditions") or [],
            "confirmation_conditions": setup.get("confirmation_conditions") or [],
        }
        for setup in setups
    ]
    evaluation_setups = [_evaluation_setup(setup) for setup in setups]
    invalidation = {
        "setups": [
            {"setup_id": setup.get("setup_id"), "level": setup.get("invalidation_level"), "stop_reference": setup.get("stop_reference")}
            for setup in setups
        ]
    }
    risk = {
        "setups": setups,
        "active_scenario": live_output.get("active_scenario"),
        "feasibility": feasibility,
        "no_trade": live_output.get("no_trade"),
    }
    baseline_trade_date = baseline.get("trade_date")
    resolved_trade_date = trade_date or (str(baseline_trade_date) if baseline_trade_date else as_of.date().isoformat())
    resolved_run_id = run_id or str(baseline.get("run_id") or live_output.get("strategy_id") or "live-strategy")
    return build_strategy_snapshot(
        account_id=account_id,
        asset=asset,
        trade_date=resolved_trade_date,
        run_id=resolved_run_id,
        strategy_id=str(live_output.get("strategy_id") or resolved_run_id),
        strategy_version=str(live_output.get("strategy_version") or "live_strategy.rules.v2"),
        as_of=as_of,
        reference_price=_number(market.get("price")),
        bias=str(baseline.get("bias") or "neutral"),
        confidence=_number(baseline.get("confidence")),
        mode="shadow",
        publish_allowed=publish_allowed,
        quality_gate=quality_gate,
        key_levels=[dict(item) for item in market_state.get("key_levels") or [] if isinstance(item, Mapping)],
        entry_conditions=entry_conditions,
        evaluation_setups=evaluation_setups,
        invalidation=invalidation,
        risk=risk,
        source_refs=[dict(item) for item in live_output.get("source_refs") or [] if isinstance(item, Mapping)],
        artifact_refs=list(live_output.get("artifact_refs") or []),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _evaluation_setup(setup: Mapping[str, Any]) -> dict[str, Any]:
    direction = str(setup.get("direction") or "").lower()
    zone = [_number(item) for item in setup.get("entry_zone") or []]
    zone = [item for item in zone if item is not None]
    zone_low = min(zone) if zone else None
    zone_high = max(zone) if zone else None
    trigger_price = zone_high if direction == "long" else (zone_low if direction == "short" else None)
    return {
        "setup_id": setup.get("setup_id"),
        "direction": direction,
        "status": setup.get("status"),
        "trigger_type": "break_above" if direction == "long" else "break_below",
        "trigger_price": trigger_price,
        "entry_zone_low": zone_low,
        "entry_zone_high": zone_high,
        "confirmation_rule": setup.get("confirmation_conditions") or [],
        "invalidation_price": setup.get("invalidation_level"),
        "stop_price": setup.get("stop_reference"),
        "target_prices": [
            target.get("price")
            for target in setup.get("targets") or []
            if isinstance(target, Mapping)
        ],
        "fill_policy": "trigger_price_on_touch",
    }


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["build_strategy_snapshot_from_live_output"]
