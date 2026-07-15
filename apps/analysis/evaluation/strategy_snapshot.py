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
from typing import Any, Mapping


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
    invalidation: Mapping[str, Any]
    risk: Mapping[str, Any]
    source_refs: tuple[Mapping[str, Any], ...]
    artifact_refs: tuple[Any, ...]
    prompt_version: str | None = None
    revision: str | None = None

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
            "invalidation": _thaw(self.invalidation),
            "risk": _thaw(self.risk),
            "source_refs": [_thaw(item) for item in self.source_refs],
            "artifact_refs": [_thaw(item) for item in self.artifact_refs],
            "revision": self.revision,
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
    invalidation: Mapping[str, Any] | None = None,
    risk: Mapping[str, Any] | None = None,
    source_refs: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    artifact_refs: list[Any] | tuple[Any, ...] | None = None,
    prompt_version: str | None = None,
    revision: str | None = None,
    evaluation_id: str | None = None,
) -> StrategySnapshot:
    """Build a deterministic snapshot from strategy output and lineage.

    ``evaluation_id`` defaults to a content hash.  Supplying ``revision`` or
    an explicit id is the non-destructive way to represent a revised decision;
    no previous snapshot is ever mutated by this function.
    """

    normalized_as_of = _as_utc(as_of)
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
        "invalidation": invalidation or {},
        "risk": risk or {},
        "source_refs": list(source_refs or []),
        "artifact_refs": list(artifact_refs or []),
        "revision": revision,
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
        invalidation=_freeze(invalidation or {}),
        risk=_freeze(risk or {}),
        source_refs=tuple(_freeze(item) for item in source_refs or ()),
        artifact_refs=tuple(_freeze(item) for item in artifact_refs or ()),
        revision=revision,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
