"""Deterministic, read-only strategy outcome evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from math import isfinite
from typing import Any, Literal, Mapping, Sequence

from .strategy_snapshot import EvaluationSetup, StrategySnapshot, _as_utc, _bias_direction, _number

HORIZONS = ("1h", "4h", "session", "24h")
OutcomeStatus = Literal["scored", "blocked", "unscorable"]
OutcomeClass = Literal["correct", "incorrect", "neutral", "hold", "invalidated", "blocked", "unscorable"]
OutcomeLifecycle = Literal[
    "never_triggered",
    "invalidated_before_entry",
    "triggered",
    "triggered_then_invalidated",
    "target_reached",
    "same_bar_ambiguous",
    "insufficient_market_path",
    "insufficient_strategy_contract",
    "blocked",
]


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    evaluation_id: str
    horizon: str
    status: OutcomeStatus
    classification: OutcomeClass
    lifecycle_status: OutcomeLifecycle
    scoreable: bool
    reason_codes: tuple[str, ...]
    as_of: datetime
    market_start: datetime | None
    horizon_end: datetime | None
    exit_time: datetime | None
    reference_price: float | None
    setup_id: str | None
    fill_price: float | None
    fill_time: datetime | None
    target_price: float | None
    target_time: datetime | None
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
            "lifecycle_status": self.lifecycle_status,
            "scoreable": self.scoreable,
            "reason_codes": list(self.reason_codes),
            "as_of": self.as_of.isoformat(),
            "market_start": self.market_start.isoformat() if self.market_start else None,
            "horizon_end": self.horizon_end.isoformat() if self.horizon_end else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "reference_price": self.reference_price,
            "setup_id": self.setup_id,
            "fill_price": self.fill_price,
            "fill_time": self.fill_time.isoformat() if self.fill_time else None,
            "target_price": self.target_price,
            "target_time": self.target_time.isoformat() if self.target_time else None,
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


@dataclass(frozen=True, slots=True)
class _MarketPath:
    lifecycle_status: OutcomeLifecycle
    trigger_index: int | None = None
    trigger_time: datetime | None = None
    invalidation_index: int | None = None
    invalidation_time: datetime | None = None
    target_index: int | None = None
    target_price: float | None = None
    target_time: datetime | None = None


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
    deterministic fill price instead.
    """

    interval = _expected_interval(expected_candle_interval_seconds)
    as_of = _as_utc(snapshot.as_of)
    if horizon not in HORIZONS:
        return _unscorable(snapshot, horizon, as_of, "unsupported_horizon")
    if _blocked_snapshot(snapshot):
        return _blocked(snapshot, horizon, as_of)
    if _degraded_sources(snapshot.source_refs):
        return _unscorable(snapshot, horizon, as_of, "degraded_input")
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

    setup = _select_setup(snapshot)
    if setup is None:
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "evaluation_setup_missing",
            lifecycle_status="insufficient_strategy_contract",
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
        )
    trigger_price = setup.trigger_price
    invalidation_price = setup.stop_price or setup.invalidation_price
    if not _valid_price(trigger_price):
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "trigger_price_missing",
            lifecycle_status="insufficient_strategy_contract",
            setup_id=setup.setup_id,
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
        )
    if not _valid_price(invalidation_price):
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "invalidation_price_missing",
            lifecycle_status="insufficient_strategy_contract",
            setup_id=setup.setup_id,
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
        )
    direction = 1 if setup.direction == "long" else -1
    if (direction > 0 and invalidation_price >= trigger_price) or (
        direction < 0 and invalidation_price <= trigger_price
    ):
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            "invalid_setup_price_order",
            lifecycle_status="insufficient_strategy_contract",
            setup_id=setup.setup_id,
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
        )
    path = _market_path(
        window,
        direction=direction,
        trigger=trigger_price,
        invalidation=invalidation_price,
        targets=setup.target_prices,
        interval=interval,
        pretriggered=setup.status == "triggered",
        pretrigger_time=as_of,
    )
    if path.lifecycle_status == "same_bar_ambiguous":
        ambiguous_with_invalidation = path.invalidation_index is not None
        return _unscorable(
            snapshot,
            horizon,
            as_of,
            (
                "same_bar_trigger_and_invalidation"
                if ambiguous_with_invalidation
                else "same_bar_trigger_and_target"
            ),
            extra_reasons=("intrabar_path_unknown",),
            lifecycle_status="same_bar_ambiguous",
            setup_id=setup.setup_id,
            market_start=_observation_time(window[0], interval),
            horizon_end=horizon_end,
            triggered=True,
            invalidated=ambiguous_with_invalidation,
            trigger_time=path.trigger_time,
            invalidation_time=path.invalidation_time,
            target_price=path.target_price,
            target_time=path.target_time,
        )
    triggered = path.trigger_time is not None
    invalidated = path.invalidation_time is not None
    exit_candle = window[-1]
    fill_price = trigger_price if triggered else None
    if path.lifecycle_status == "invalidated_before_entry":
        classification: OutcomeClass = "invalidated"
        exit_time = path.invalidation_time
        exit_price = invalidation_price
        return_abs = None
        return_pct = None
        accuracy = "not_applicable"
    elif path.lifecycle_status == "never_triggered":
        classification = "hold"
        exit_time = _observation_time(exit_candle, interval)
        exit_price = exit_candle.close
        return_abs = None
        return_pct = None
        accuracy = "not_applicable"
    elif path.lifecycle_status == "triggered_then_invalidated":
        classification = "invalidated"
        exit_time = path.invalidation_time
        exit_price = invalidation_price
        return_abs = exit_price - fill_price if fill_price is not None else None
        return_pct = return_abs / fill_price if return_abs is not None and fill_price else None
        accuracy = "incorrect"
    elif path.lifecycle_status == "target_reached":
        classification = "correct"
        exit_time = path.target_time
        exit_price = path.target_price
        return_abs = exit_price - fill_price if exit_price is not None and fill_price is not None else None
        return_pct = return_abs / fill_price if return_abs is not None and fill_price else None
        accuracy = "correct"
    else:
        exit_time = _observation_time(exit_candle, interval)
        exit_price = exit_candle.close
        return_abs = exit_price - fill_price if fill_price is not None else None
        return_pct = return_abs / fill_price if return_abs is not None and fill_price else None
        band = abs(fill_price * neutral_band_pct) if neutral_band_pct is not None and fill_price else abs(neutral_band)
        accuracy = _accuracy(direction, return_abs or 0.0, band)
        classification = "neutral" if accuracy == "neutral" else ("correct" if accuracy == "correct" else "incorrect")

    excursion_end_index = (
        path.invalidation_index
        if path.lifecycle_status == "triggered_then_invalidated"
        else (path.target_index if path.lifecycle_status == "target_reached" else len(window) - 1)
    )
    excursion_window = (
        window[path.trigger_index : excursion_end_index + 1]
        if path.trigger_index is not None and excursion_end_index is not None
        else []
    )
    mfe, mae = _excursions(excursion_window, fill_price, direction) if fill_price is not None and excursion_window else (None, None)
    if path.lifecycle_status == "target_reached" and return_abs is not None:
        mfe = max(0.0, direction * return_abs)
    if path.lifecycle_status == "triggered_then_invalidated" and return_abs is not None:
        mae = max(0.0, -direction * return_abs)
    reasons = []
    if path.lifecycle_status == "never_triggered":
        reasons.append("trigger_not_observed")
    elif path.lifecycle_status == "invalidated_before_entry":
        reasons.append("invalidation_before_entry")
    elif path.lifecycle_status == "triggered_then_invalidated":
        reasons.append("invalidation_after_entry")
    elif path.lifecycle_status == "target_reached":
        reasons.append("target_observed")
    return OutcomeEvaluation(
        evaluation_id=snapshot.evaluation_id,
        horizon=horizon,
        status="scored",
        classification=classification,
        lifecycle_status=path.lifecycle_status,
        scoreable=True,
        reason_codes=tuple(reasons),
        as_of=as_of,
        market_start=_observation_time(window[0], interval),
        horizon_end=horizon_end,
        exit_time=exit_time,
        reference_price=snapshot.reference_price,
        setup_id=setup.setup_id,
        fill_price=fill_price,
        fill_time=path.trigger_time,
        target_price=path.target_price,
        target_time=path.target_time,
        exit_price=exit_price,
        return_abs=return_abs,
        return_pct=return_pct,
        direction_accuracy=accuracy,
        triggered=triggered,
        invalidated=invalidated,
        trigger_time=path.trigger_time,
        invalidation_time=path.invalidation_time,
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
        if at is None or not all(_valid_price(value) for value in (high, low, close)):
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


def _select_setup(snapshot: StrategySnapshot) -> EvaluationSetup | None:
    active = str(snapshot.risk.get("active_scenario") or "").lower()
    if active == "no_trade":
        return None
    eligible = tuple(
        setup
        for setup in snapshot.evaluation_setups
        if setup.status not in {"blocked_rr", "blocked_data", "unavailable"}
    )
    preferred = active if active in {"long", "short"} else _bias_direction(snapshot.bias)
    if preferred is not None:
        return next((setup for setup in eligible if setup.direction == preferred), None)
    return eligible[0] if len(eligible) == 1 else None


def _market_path(
    candles: Sequence[_Candle],
    *,
    direction: int,
    trigger: float,
    invalidation: float,
    targets: Sequence[float],
    interval: timedelta | None,
    pretriggered: bool,
    pretrigger_time: datetime,
) -> _MarketPath:
    target = _first_target(direction, trigger, targets)
    trigger_index = 0 if pretriggered else None
    trigger_time = pretrigger_time if pretriggered else None
    for index, candle in enumerate(candles):
        observed_at = _observation_time(candle, interval)
        trigger_hit = candle.high >= trigger if direction > 0 else candle.low <= trigger
        invalidation_hit = candle.low <= invalidation if direction > 0 else candle.high >= invalidation
        target_hit = target is not None and (candle.high >= target if direction > 0 else candle.low <= target)
        if trigger_index is None:
            if trigger_hit and invalidation_hit:
                return _MarketPath(
                    lifecycle_status="same_bar_ambiguous",
                    trigger_index=index,
                    trigger_time=observed_at,
                    invalidation_index=index,
                    invalidation_time=observed_at,
                )
            if invalidation_hit:
                return _MarketPath(
                    lifecycle_status="invalidated_before_entry",
                    invalidation_index=index,
                    invalidation_time=observed_at,
                )
            if not trigger_hit:
                continue
            trigger_index = index
            trigger_time = observed_at
            if target_hit:
                return _MarketPath(
                    lifecycle_status="same_bar_ambiguous",
                    trigger_index=index,
                    trigger_time=observed_at,
                    target_index=index,
                    target_price=target,
                    target_time=observed_at,
                )
            continue
        if invalidation_hit and target_hit:
            return _MarketPath(
                lifecycle_status="same_bar_ambiguous",
                trigger_index=trigger_index,
                trigger_time=trigger_time,
                invalidation_index=index,
                invalidation_time=observed_at,
                target_index=index,
                target_price=target,
                target_time=observed_at,
            )
        if invalidation_hit:
            return _MarketPath(
                lifecycle_status="triggered_then_invalidated",
                trigger_index=trigger_index,
                trigger_time=trigger_time,
                invalidation_index=index,
                invalidation_time=observed_at,
            )
        if target_hit:
            return _MarketPath(
                lifecycle_status="target_reached",
                trigger_index=trigger_index,
                trigger_time=trigger_time,
                target_index=index,
                target_price=target,
                target_time=observed_at,
            )
    if trigger_index is None:
        return _MarketPath(lifecycle_status="never_triggered")
    return _MarketPath(lifecycle_status="triggered", trigger_index=trigger_index, trigger_time=trigger_time)


def _first_target(direction: int, trigger: float, targets: Sequence[float]) -> float | None:
    eligible = [
        value
        for value in targets
        if _valid_price(value) and (value > trigger if direction > 0 else value < trigger)
    ]
    if not eligible:
        return None
    return min(eligible) if direction > 0 else max(eligible)


def _valid_price(value: float | None) -> bool:
    return value is not None and isfinite(value) and value > 0


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


def _unscorable(
    snapshot: StrategySnapshot,
    horizon: str,
    as_of: datetime,
    reason: str,
    *,
    extra_reasons: tuple[str, ...] = (),
    lifecycle_status: OutcomeLifecycle = "insufficient_market_path",
    setup_id: str | None = None,
    market_start: datetime | None = None,
    horizon_end: datetime | None = None,
    triggered: bool = False,
    invalidated: bool = False,
    trigger_time: datetime | None = None,
    invalidation_time: datetime | None = None,
    target_price: float | None = None,
    target_time: datetime | None = None,
) -> OutcomeEvaluation:
    return OutcomeEvaluation(
        evaluation_id=snapshot.evaluation_id,
        horizon=horizon,
        status="unscorable",
        classification="unscorable",
        lifecycle_status=lifecycle_status,
        scoreable=False,
        reason_codes=(reason, *extra_reasons),
        as_of=as_of,
        market_start=market_start,
        horizon_end=horizon_end,
        exit_time=None,
        reference_price=snapshot.reference_price,
        setup_id=setup_id,
        fill_price=None,
        fill_time=None,
        target_price=target_price,
        target_time=target_time,
        exit_price=None,
        return_abs=None,
        return_pct=None,
        direction_accuracy="not_applicable",
        triggered=triggered,
        invalidated=invalidated,
        trigger_time=trigger_time,
        invalidation_time=invalidation_time,
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
        lifecycle_status="blocked",
        scoreable=False,
        reason_codes=("quality_gate_blocked",),
        as_of=as_of,
        market_start=None,
        horizon_end=_horizon_end(as_of, horizon) if horizon in HORIZONS else None,
        exit_time=None,
        reference_price=snapshot.reference_price,
        setup_id=None,
        fill_price=None,
        fill_time=None,
        target_price=None,
        target_time=None,
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
