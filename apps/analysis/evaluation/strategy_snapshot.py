"""Immutable strategy snapshots used by the shadow evaluator.

This module deliberately has no persistence or transport concerns.  A caller
can serialize :meth:`StrategySnapshot.to_dict` to an append-only output and a
revision naturally receives a different ``evaluation_id`` because the
canonical input changes (or an explicit id can be supplied by the caller).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Literal, Mapping


SetupDirection = Literal["long", "short"]
FillPolicy = Literal["trigger_price_on_touch"]


@dataclass(frozen=True, slots=True)
class EvaluationSetup:
    """Normalized setup consumed by the deterministic outcome evaluator."""

    setup_id: str
    direction: SetupDirection
    trigger_type: str
    trigger_price: float | None
    entry_zone_low: float | None
    entry_zone_high: float | None
    confirmation_rule: tuple[str, ...]
    invalidation_price: float | None
    stop_price: float | None
    target_prices: tuple[float, ...]
    fill_policy: FillPolicy = "trigger_price_on_touch"
    status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup_id": self.setup_id,
            "direction": self.direction,
            "trigger_type": self.trigger_type,
            "trigger_price": self.trigger_price,
            "entry_zone_low": self.entry_zone_low,
            "entry_zone_high": self.entry_zone_high,
            "confirmation_rule": list(self.confirmation_rule),
            "invalidation_price": self.invalidation_price,
            "stop_price": self.stop_price,
            "target_prices": list(self.target_prices),
            "fill_policy": self.fill_policy,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class StrategySnapshot:
    """Frozen, lineage-carrying copy of a strategy decision."""

    evaluation_id: str
    account_id: str
    asset: str
    trade_date: str
    run_id: str
    strategy_id: str
    strategy_version: str
    as_of: datetime
    reference_price: float | None
    bias: str
    confidence: float | None
    mode: str
    publish_allowed: bool
    quality_gate: Mapping[str, Any]
    key_levels: tuple[Mapping[str, Any], ...]
    entry_conditions: tuple[Mapping[str, Any], ...]
    evaluation_setups: tuple[EvaluationSetup, ...]
    invalidation: Mapping[str, Any]
    risk: Mapping[str, Any]
    source_refs: tuple[Mapping[str, Any], ...]
    artifact_refs: tuple[Any, ...]
    prompt_version: str | None = None
    revision: str | None = None
    supersedes_evaluation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible copy without exposing mutable internals."""

        return {
            "evaluation_id": self.evaluation_id,
            "account_id": self.account_id,
            "asset": self.asset,
            "trade_date": self.trade_date,
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "prompt_version": self.prompt_version,
            "as_of": self.as_of.isoformat(),
            "reference_price": self.reference_price,
            "bias": self.bias,
            "confidence": self.confidence,
            "mode": self.mode,
            "publish_allowed": self.publish_allowed,
            "quality_gate": _thaw(self.quality_gate),
            "key_levels": [_thaw(item) for item in self.key_levels],
            "entry_conditions": [_thaw(item) for item in self.entry_conditions],
            "evaluation_setups": [item.to_dict() for item in self.evaluation_setups],
            "invalidation": _thaw(self.invalidation),
            "risk": _thaw(self.risk),
            "source_refs": [_thaw(item) for item in self.source_refs],
            "artifact_refs": [_thaw(item) for item in self.artifact_refs],
            "revision": self.revision,
            "supersedes_evaluation_id": self.supersedes_evaluation_id,
        }


def build_strategy_snapshot(
    *,
    asset: str,
    trade_date: str,
    run_id: str,
    strategy_id: str,
    strategy_version: str,
    as_of: datetime,
    reference_price: float | None,
    bias: str,
    confidence: float | None = None,
    account_id: str = "codex-xauusd-shadow",
    mode: str = "shadow",
    publish_allowed: bool = False,
    quality_gate: Mapping[str, Any] | None = None,
    key_levels: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    entry_conditions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    evaluation_setups: list[Mapping[str, Any] | EvaluationSetup]
    | tuple[Mapping[str, Any] | EvaluationSetup, ...]
    | None = None,
    invalidation: Mapping[str, Any] | None = None,
    risk: Mapping[str, Any] | None = None,
    source_refs: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    artifact_refs: list[Any] | tuple[Any, ...] | None = None,
    prompt_version: str | None = None,
    revision: str | None = None,
    supersedes_evaluation_id: str | None = None,
    evaluation_id: str | None = None,
) -> StrategySnapshot:
    """Build a deterministic snapshot from strategy output and lineage.

    ``evaluation_id`` defaults to a content hash.  Supplying ``revision`` or
    an explicit id is the non-destructive way to represent a revised decision;
    no previous snapshot is ever mutated by this function.
    """

    normalized_as_of = _as_utc(as_of)
    normalized_setups = _normalize_evaluation_setups(
        evaluation_setups=evaluation_setups,
        entry_conditions=entry_conditions or (),
        invalidation=invalidation or {},
        risk=risk or {},
        bias=str(bias),
    )
    payload = {
        "account_id": str(account_id),
        "asset": str(asset),
        "trade_date": str(trade_date),
        "run_id": str(run_id),
        "strategy_id": str(strategy_id),
        "strategy_version": str(strategy_version),
        "prompt_version": prompt_version,
        "as_of": normalized_as_of.isoformat(),
        "reference_price": _number(reference_price),
        "bias": str(bias),
        "confidence": _number(confidence),
        "mode": str(mode),
        "publish_allowed": bool(publish_allowed),
        "quality_gate": quality_gate or {},
        "key_levels": list(key_levels or []),
        "entry_conditions": list(entry_conditions or []),
        "evaluation_setups": [item.to_dict() for item in normalized_setups],
        "invalidation": invalidation or {},
        "risk": risk or {},
        "source_refs": list(source_refs or []),
        "artifact_refs": list(artifact_refs or []),
        "revision": revision,
        "supersedes_evaluation_id": supersedes_evaluation_id,
    }
    canonical = _canonical_json(payload)
    resolved_id = str(evaluation_id) if evaluation_id else f"eval-{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"
    return StrategySnapshot(
        evaluation_id=resolved_id,
        account_id=str(account_id),
        asset=str(asset),
        trade_date=str(trade_date),
        run_id=str(run_id),
        strategy_id=str(strategy_id),
        strategy_version=str(strategy_version),
        prompt_version=prompt_version,
        as_of=normalized_as_of,
        reference_price=_number(reference_price),
        bias=str(bias),
        confidence=_number(confidence),
        mode=str(mode),
        publish_allowed=bool(publish_allowed),
        quality_gate=_freeze(quality_gate or {}),
        key_levels=tuple(_freeze(item) for item in key_levels or ()),
        entry_conditions=tuple(_freeze(item) for item in entry_conditions or ()),
        evaluation_setups=normalized_setups,
        invalidation=_freeze(invalidation or {}),
        risk=_freeze(risk or {}),
        source_refs=tuple(_freeze(item) for item in source_refs or ()),
        artifact_refs=tuple(_freeze(item) for item in artifact_refs or ()),
        revision=revision,
        supersedes_evaluation_id=supersedes_evaluation_id,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_evaluation_setups(
    *,
    evaluation_setups: list[Mapping[str, Any] | EvaluationSetup]
    | tuple[Mapping[str, Any] | EvaluationSetup, ...]
    | None,
    entry_conditions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    invalidation: Mapping[str, Any],
    risk: Mapping[str, Any],
    bias: str,
) -> tuple[EvaluationSetup, ...]:
    if evaluation_setups is not None:
        return tuple(
            item if isinstance(item, EvaluationSetup) else _evaluation_setup_from_mapping(item, fallback_direction=bias)
            for item in evaluation_setups
        )

    result: list[EvaluationSetup] = []
    for index, condition in enumerate(entry_conditions, start=1):
        setup_id = str(condition.get("setup_id") or f"legacy-setup-{index}")
        nested_invalidation = _nested_setup(invalidation, setup_id)
        risk_setup = _nested_setup(risk, setup_id)
        combined = {
            **dict(condition),
            "setup_id": setup_id,
            "invalidation_price": _first_number(
                nested_invalidation.get("invalidation_price"),
                nested_invalidation.get("invalidation_level"),
                nested_invalidation.get("level"),
                invalidation.get("invalidation_price"),
                invalidation.get("invalidation_level"),
                invalidation.get("level"),
            ),
            "stop_price": _first_number(
                nested_invalidation.get("stop_price"),
                nested_invalidation.get("stop_reference"),
                invalidation.get("stop_price"),
                invalidation.get("stop"),
                invalidation.get("stop_reference"),
            ),
            "target_prices": condition.get("target_prices") or risk_setup.get("targets") or [],
        }
        result.append(_evaluation_setup_from_mapping(combined, fallback_direction=bias))
    return tuple(result)


def _evaluation_setup_from_mapping(value: Mapping[str, Any], *, fallback_direction: str) -> EvaluationSetup:
    direction = _setup_direction(value.get("direction"), fallback=fallback_direction)
    zone_low, zone_high = _entry_zone(value)
    trigger_price = _first_number(
        value.get("trigger_price"),
        value.get("price"),
        value.get("level"),
        value.get("reference_price"),
        value.get("value"),
    )
    if trigger_price is None:
        trigger_price = zone_high if direction == "long" else zone_low
    invalidation_price = _first_number(
        value.get("invalidation_price"),
        value.get("invalidation_level"),
        value.get("stop_reference"),
    )
    stop_price = _first_number(value.get("stop_price"), value.get("stop_reference"), invalidation_price)
    fill_policy = str(value.get("fill_policy") or "trigger_price_on_touch")
    if fill_policy != "trigger_price_on_touch":
        raise ValueError(f"unsupported evaluation fill_policy: {fill_policy}")
    return EvaluationSetup(
        setup_id=str(value.get("setup_id") or "evaluation-setup"),
        direction=direction,
        trigger_type=str(value.get("trigger_type") or ("break_above" if direction == "long" else "break_below")),
        trigger_price=trigger_price,
        entry_zone_low=zone_low,
        entry_zone_high=zone_high,
        confirmation_rule=_strings(value.get("confirmation_rule") or value.get("confirmation_conditions")),
        invalidation_price=invalidation_price,
        stop_price=stop_price,
        target_prices=_target_prices(value.get("target_prices") or value.get("targets")),
        fill_policy="trigger_price_on_touch",
        status=str(value.get("status") or "unknown"),
    )


def _setup_direction(value: Any, *, fallback: str) -> SetupDirection:
    normalized = str(value or fallback).strip().lower()
    if normalized in {"long", "bullish", "bull", "buy", "above", "up"}:
        return "long"
    if normalized in {"short", "bearish", "bear", "sell", "below", "down"}:
        return "short"
    fallback_direction = _bias_direction(fallback)
    if fallback_direction is None:
        raise ValueError("evaluation setup direction must be long or short")
    return fallback_direction


def _bias_direction(value: str) -> SetupDirection | None:
    normalized = str(value).strip().lower()
    if any(token in normalized for token in ("bull", "long", "buy", "up")):
        return "long"
    if any(token in normalized for token in ("bear", "short", "sell", "down")):
        return "short"
    return None


def _entry_zone(value: Mapping[str, Any]) -> tuple[float | None, float | None]:
    low = _number(value.get("entry_zone_low"))
    high = _number(value.get("entry_zone_high"))
    zone = value.get("entry_zone")
    if (low is None or high is None) and isinstance(zone, (list, tuple)) and len(zone) >= 2:
        first, second = _number(zone[0]), _number(zone[1])
        if first is not None and second is not None:
            low, high = min(first, second), max(first, second)
    return low, high


def _nested_setup(value: Mapping[str, Any], setup_id: str) -> dict[str, Any]:
    for item in value.get("setups") or ():
        if isinstance(item, Mapping) and str(item.get("setup_id") or "") == setup_id:
            return dict(item)
    return {}


def _target_prices(value: Any) -> tuple[float, ...]:
    result: list[float] = []
    for item in value or ():
        number = _number(item.get("price")) if isinstance(item, Mapping) else _number(item)
        if number is not None and number not in result:
            result.append(number)
    return tuple(result)


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    return tuple(str(item) for item in value or () if str(item).strip())


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_thaw(_freeze(value)), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
