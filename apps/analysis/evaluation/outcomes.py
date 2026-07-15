"""Deterministic, read-only strategy outcome evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from math import isfinite
from typing import Any, Literal, Mapping, Sequence

from .strategy_snapshot import StrategySnapshot, _as_utc, _number

HORIZONS = ("1h", "4h", "session", "24h")
OutcomeStatus = Literal["scored", "blocked", "unscorable"]
OutcomeClass = Literal["correct", "incorrect", "neutral", "hold", "invalidated", "blocked", "unscorable"]


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    evaluation_id: str
    horizon: str
    status: OutcomeStatus
    classification: OutcomeClass
    scoreable: bool
    reason_codes: tuple[str, ...]
    as_of: datetime
    market_start: datetime | None
    horizon_end: datetime | None
    exit_time: datetime | None
    reference_price: float | None
    exit_price: float | None
    return_abs: float | None
    return_pct: float | None
    direction_accuracy: str
    triggered: bool
    invalidated: bool
    trigger_time: datetime | None
    invalidation_time: datetime | None
    mfe: float | None
    mae: float | None
    source_refs: tuple[Mapping[str, Any], ...]
    artifact_refs: tuple[Any, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "horizon": self.horizon,
            "status": self.status,
            "classification": self.classification,
            "scoreable": self.scoreable,
            "reason_codes": list(self.reason_codes),
            "as_of": self.as_of.isoformat(),
            "market_start": self.market_start.isoformat() if self.market_start else None,
            "horizon_end": self.horizon_end.isoformat() if self.horizon_end else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "reference_price": self.reference_price,
            "exit_price": self.exit_price,
            "return_abs": self.return_abs,
            "return_pct": self.return_pct,
            "direction_accuracy": self.direction_accuracy,
            "triggered": self.triggered,
            "invalidated": self.invalidated,
            "trigger_time": self.trigger_time.isoformat() if self.trigger_time else None,
            "invalidation_time": self.invalidation_time.isoformat() if self.invalidation_time else None,
            "mfe": self.mfe,
            "mae": self.mae,
            "source_refs": [dict(item) for item in self.source_refs],
            "artifact_refs": list(self.artifact_refs),
        }


@dataclass(frozen=True, slots=True)
class _Candle:
    at: datetime
    high: float
    low: float
    close: float


def evaluate_strategy_outcome(
    snapshot: StrategySnapshot,
    market_candles: Sequence[Mapping[str, Any]] | None,
    *,
    horizon: str,
    neutral_band: float = 0.0,
    neutral_band_pct: float | None = None,
    expected_candle_interval_seconds: float | int | None = None,
) -> OutcomeEvaluation:
    """Evaluate one immutable snapshot against complete observed candles.

    No candle or price is invented.  ``neutral_band`` is an absolute price
    move; callers may use ``neutral_band_pct`` to express a fraction of the
    snapshot reference price instead.
    """

    interval = _expected_interval(expected_candle_interval_seconds)
    as_of = _as_utc(snapshot.as_of)
    if horizon not in HORIZONS:
        return _unscorable(snapshot, horizon, as_of, "unsupported_horizon")
    if _blocked_snapshot(snapshot):
        return _blocked(snapshot, horizon, as_of)
    if _degraded_sources(snapshot.source_refs):
        return _unscorable(snapshot, horizon, as_of, "degraded_input")
    if snapshot.reference_price is None or snapshot.reference_price <= 0:
        return _unscorable(snapshot, horizon, as_of, "reference_price_missing")

    candles = _normalize_candles(market_candles)
    first = next((candle for candle in candles if candle.at > as_of), None)
    if first is None:
        return _unscorable(snapshot, horizon, as_of, "complete_candle_after_as_of_missing")
    horizon_end = _horizon_end(as_of, horizon)
    window = [
        candle
        for candle in candles
        if candle.at > as_of and _observation_time(candle, interval) <= horizon_end
    ]
    if not window:
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "horizon_data_missing",
            market_start=_observation_time(first, interval),
            horizon_end=horizon_end,
        )
    if _horizon_coverage_incomplete(window[-1], horizon_end, interval):
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "horizon_data_incomplete",
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
        )

    direction = _direction(snapshot.bias)
    trigger_price = _trigger_price(snapshot)
    invalidation_price = _invalidation_price(snapshot)
    trigger_time, invalidation_time = _event_times(
        window,
        direction,
        trigger_price,
        invalidation_price,
        interval,
    )
    triggered = trigger_time is not None
    invalidated = invalidation_time is not None
    exit_candle = window[-1]
    reference = snapshot.reference_price
    return_abs = exit_candle.close - reference
    return_pct = return_abs / reference
    band = abs(reference * neutral_band_pct) if neutral_band_pct is not None else abs(neutral_band)
    accuracy = _accuracy(direction, return_abs, band)

    if invalidated:
        classification: OutcomeClass = "invalidated"
    elif not triggered:
        classification = "hold"
    elif accuracy == "neutral":
        classification = "neutral"
    elif accuracy == "correct":
        classification = "correct"
    else:
        classification = "incorrect"

    excursion_window = [
        candle
        for candle in window
        if trigger_time is not None and _observation_time(candle, interval) >= trigger_time
    ]
    mfe, mae = _excursions(excursion_window, reference, direction) if triggered and excursion_window else (None, None)
    reasons = []
    if not triggered:
        reasons.append("trigger_not_observed")
    if invalidated:
        reasons.append("invalidation_observed")
    return OutcomeEvaluation(
        evaluation_id=snapshot.evaluation_id,
        horizon=horizon,
        status="scored",
        classification=classification,
        scoreable=True,
        reason_codes=tuple(reasons),
        as_of=as_of,
        market_start=_observation_time(window[0], interval),
        horizon_end=horizon_end,
        exit_time=_observation_time(exit_candle, interval),
        reference_price=reference,
        exit_price=exit_candle.close,
        return_abs=return_abs,
        return_pct=return_pct,
        direction_accuracy=accuracy,
        triggered=triggered,
        invalidated=invalidated,
        trigger_time=trigger_time,
        invalidation_time=invalidation_time,
        mfe=mfe,
        mae=mae,
        source_refs=snapshot.source_refs,
        artifact_refs=snapshot.artifact_refs,
    )


def _blocked_snapshot(snapshot: StrategySnapshot) -> bool:
    gate_status = str(snapshot.quality_gate.get("status") or snapshot.quality_gate.get("decision") or "").lower()
    return not snapshot.publish_allowed or gate_status in {"blocked", "block", "rejected", "degraded"}


def _degraded_sources(refs: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(ref.get("status") or "").lower() in {"degraded", "unavailable", "missing", "failed"} for ref in refs)


def _normalize_candles(rows: Sequence[Mapping[str, Any]] | None) -> list[_Candle]:
    result: list[_Candle] = []
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get("partial") is True:
            continue
        at = _parse_time(row.get("time") or row.get("timestamp") or row.get("open_time"))
        high, low, close = _number(row.get("high")), _number(row.get("low")), _number(row.get("close"))
        if at is None or high is None or low is None or close is None:
            continue
        if high < low:
            continue
        result.append(_Candle(at=at, high=high, low=low, close=close))
    return sorted(result, key=lambda item: item.at)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _expected_interval(value: float | int | None) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError("expected_candle_interval_seconds must be a finite positive number")
    return timedelta(seconds=value)


def _observation_time(candle: _Candle, interval: timedelta | None) -> datetime:
    return candle.at + interval if interval is not None else candle.at


def _horizon_coverage_incomplete(candle: _Candle, horizon_end: datetime, interval: timedelta | None) -> bool:
    observation_time = _observation_time(candle, interval)
    if interval is None:
        return observation_time < horizon_end
    return horizon_end - observation_time >= interval


def _horizon_end(as_of: datetime, horizon: str) -> datetime:
    if horizon == "session":
        return datetime.combine(as_of.date(), time.max, tzinfo=UTC)
    hours = {"1h": 1, "4h": 4, "24h": 24}[horizon]
    return as_of + timedelta(hours=hours)


def _direction(bias: str) -> int:
    value = str(bias).lower()
    if any(token in value for token in ("bull", "long", "up", "buy")):
        return 1
    if any(token in value for token in ("bear", "short", "down", "sell")):
        return -1
    return 0


def _trigger_price(snapshot: StrategySnapshot) -> float | None:
    for condition in snapshot.entry_conditions:
        for key in ("trigger_price", "price", "level", "reference_price", "value"):
            value = _number(condition.get(key))
            if value is not None:
                return value
    return None


def _invalidation_price(snapshot: StrategySnapshot) -> float | None:
    for key in ("invalidation_level", "level", "stop", "stop_reference", "price", "value"):
        value = _number(snapshot.invalidation.get(key))
        if value is not None:
            return value
    return None


def _event_times(
    candles: Sequence[_Candle],
    direction: int,
    trigger: float | None,
    invalidation: float | None,
    interval: timedelta | None,
) -> tuple[datetime | None, datetime | None]:
    if direction == 0:
        return None, None
    trigger_at = None
    invalidation_at = None
    for candle in candles:
        if trigger is not None and trigger_at is None and ((direction > 0 and candle.high >= trigger) or (direction < 0 and candle.low <= trigger)):
            trigger_at = _observation_time(candle, interval)
        if invalidation is not None and invalidation_at is None and ((direction > 0 and candle.low <= invalidation) or (direction < 0 and candle.high >= invalidation)):
            invalidation_at = _observation_time(candle, interval)
    return trigger_at, invalidation_at


def _accuracy(direction: int, return_abs: float, neutral_band: float) -> str:
    if direction == 0:
        return "not_applicable"
    if abs(return_abs) <= neutral_band:
        return "neutral"
    return "correct" if (return_abs > 0) == (direction > 0) else "incorrect"


def _excursions(candles: Sequence[_Candle], reference: float, direction: int) -> tuple[float, float]:
    if direction > 0:
        return max(0.0, max(candle.high - reference for candle in candles)), max(0.0, max(reference - candle.low for candle in candles))
    return max(0.0, max(reference - candle.low for candle in candles)), max(0.0, max(candle.high - reference for candle in candles))


def _unscorable(snapshot: StrategySnapshot, horizon: str, as_of: datetime, reason: str, *, market_start: datetime | None = None, horizon_end: datetime | None = None) -> OutcomeEvaluation:
    return OutcomeEvaluation(
        evaluation_id=snapshot.evaluation_id,
        horizon=horizon,
        status="unscorable",
        classification="unscorable",
        scoreable=False,
        reason_codes=(reason,),
        as_of=as_of,
        market_start=market_start,
        horizon_end=horizon_end,
        exit_time=None,
        reference_price=snapshot.reference_price,
        exit_price=None,
        return_abs=None,
        return_pct=None,
        direction_accuracy="not_applicable",
        triggered=False,
        invalidated=False,
        trigger_time=None,
        invalidation_time=None,
        mfe=None,
        mae=None,
        source_refs=snapshot.source_refs,
        artifact_refs=snapshot.artifact_refs,
    )


def _blocked(snapshot: StrategySnapshot, horizon: str, as_of: datetime) -> OutcomeEvaluation:
    return OutcomeEvaluation(
        evaluation_id=snapshot.evaluation_id,
        horizon=horizon,
        status="blocked",
        classification="blocked",
        scoreable=False,
        reason_codes=("quality_gate_blocked",),
        as_of=as_of,
        market_start=None,
        horizon_end=_horizon_end(as_of, horizon) if horizon in HORIZONS else None,
        exit_time=None,
        reference_price=snapshot.reference_price,
        exit_price=None,
        return_abs=None,
        return_pct=None,
        direction_accuracy="not_applicable",
        triggered=False,
        invalidated=False,
        trigger_time=None,
        invalidation_time=None,
        mfe=None,
        mae=None,
        source_refs=snapshot.source_refs,
        artifact_refs=snapshot.artifact_refs,
    )
