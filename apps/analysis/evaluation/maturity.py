"""Pure maturity gate for append-only shadow evaluation outcomes.

The gate separates an outcome that is safe to persist from a retryable result
caused by a horizon that has not elapsed or canonical candles that have not
arrived yet.  It deliberately owns no persistence or transport concerns.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal, Mapping, Sequence

from .outcomes import HORIZONS, OutcomeEvaluation, _expected_interval, evaluate_strategy_outcome
from .strategy_snapshot import StrategySnapshot, _as_utc


SCHEMA = "shadow_evaluation.maturity.v1"
MaturityStatus = Literal["pending", "persistable"]

RETRYABLE_REASON_CODES = frozenset(
    {
        "complete_candle_after_as_of_missing",
        "horizon_data_incomplete",
        "horizon_data_missing",
    }
)
TERMINAL_UNSCORABLE_REASON_CODES = frozenset(
    {
        "degraded_input",
        "reference_price_missing",
        "unsupported_horizon",
    }
)


@dataclass(frozen=True, slots=True)
class HorizonMaturity:
    """Persistability decision for one canonical evaluation horizon."""

    horizon: str
    status: MaturityStatus
    horizon_end: datetime
    outcome: OutcomeEvaluation | None
    reasons: tuple[str, ...]

    @property
    def persistable(self) -> bool:
        return self.status == "persistable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "status": self.status,
            "persistable": self.persistable,
            "horizon_end": self.horizon_end.isoformat(),
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class OutcomeMaturityPlan:
    """Stable, ordered plan for evaluating one immutable strategy snapshot."""

    schema_version: str
    maturity_id: str
    evaluation_id: str
    snapshot_as_of: datetime
    now: datetime
    horizons: tuple[HorizonMaturity, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "maturity_id": self.maturity_id,
            "evaluation_id": self.evaluation_id,
            "snapshot_as_of": self.snapshot_as_of.isoformat(),
            "now": self.now.isoformat(),
            "horizons": [item.to_dict() for item in self.horizons],
        }


def build_outcome_maturity_plan(
    snapshot: StrategySnapshot,
    market_candles: Sequence[Mapping[str, Any]] | None,
    *,
    now: datetime,
    expected_candle_interval_seconds: float | int | None = None,
) -> OutcomeMaturityPlan:
    """Return ordered persistability decisions without mutating the inputs.

    A blocked snapshot is terminal immediately.  An approved snapshot is not
    evaluated before a horizon ends.  Once mature, retryable candle gaps remain
    pending so that a later run can produce the real append-only outcome.
    """

    normalized_now = _as_utc(now)
    _expected_interval(expected_candle_interval_seconds)
    snapshot_as_of = _as_utc(snapshot.as_of)
    blocked = _is_blocked(snapshot)
    decisions: list[HorizonMaturity] = []

    for horizon in HORIZONS:
        horizon_end = _horizon_end(snapshot_as_of, horizon)
        if not blocked and horizon_end > normalized_now:
            decisions.append(
                HorizonMaturity(
                    horizon=horizon,
                    status="pending",
                    horizon_end=horizon_end,
                    outcome=None,
                    reasons=("horizon_not_mature",),
                )
            )
            continue

        outcome = evaluate_strategy_outcome(
            snapshot,
            market_candles,
            horizon=horizon,
            expected_candle_interval_seconds=expected_candle_interval_seconds,
        )
        status = _outcome_status(outcome)
        decisions.append(
            HorizonMaturity(
                horizon=horizon,
                status=status,
                horizon_end=horizon_end,
                outcome=outcome,
                reasons=outcome.reason_codes,
            )
        )

    return OutcomeMaturityPlan(
        schema_version=SCHEMA,
        maturity_id=_maturity_id(snapshot.evaluation_id),
        evaluation_id=snapshot.evaluation_id,
        snapshot_as_of=snapshot_as_of,
        now=normalized_now,
        horizons=tuple(decisions),
    )


def _is_blocked(snapshot: StrategySnapshot) -> bool:
    gate_status = str(snapshot.quality_gate.get("status") or snapshot.quality_gate.get("decision") or "").lower()
    return not snapshot.publish_allowed or gate_status in {"blocked", "block", "rejected", "degraded"}


def _outcome_status(outcome: OutcomeEvaluation) -> MaturityStatus:
    if outcome.status in {"scored", "blocked"}:
        return "persistable"
    reasons = frozenset(outcome.reason_codes)
    if reasons and reasons.issubset(TERMINAL_UNSCORABLE_REASON_CODES):
        return "persistable"
    if reasons & RETRYABLE_REASON_CODES:
        return "pending"
    return "pending"


def _horizon_end(as_of: datetime, horizon: str) -> datetime:
    if horizon == "session":
        return datetime.combine(as_of.date(), time.max, tzinfo=UTC)
    return as_of + timedelta(hours={"1h": 1, "4h": 4, "24h": 24}[horizon])


def _maturity_id(evaluation_id: str) -> str:
    digest = hashlib.sha256(f"{SCHEMA}:{evaluation_id}".encode()).hexdigest()[:24]
    return f"maturity-{digest}"


__all__ = [
    "HorizonMaturity",
    "OutcomeMaturityPlan",
    "RETRYABLE_REASON_CODES",
    "SCHEMA",
    "TERMINAL_UNSCORABLE_REASON_CODES",
    "build_outcome_maturity_plan",
]
