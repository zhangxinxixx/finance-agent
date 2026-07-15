"""Reusable orchestration for one shadow-evaluation run.

The runner owns deterministic snapshot, maturity and append-only persistence
orchestration. Runtime input loading, database sessions, environment variables
and CLI parsing belong to callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .live_snapshot import build_strategy_snapshot_from_live_output
from .maturity import HorizonMaturity, build_outcome_maturity_plan
from .store import EvaluationStore, StoreWriteResult
from .strategy_snapshot import StrategySnapshot


def run_shadow_evaluation(
    *,
    trade_date: str,
    as_of: datetime,
    evaluated_at: datetime,
    storage_root: str | Path,
    live_output: Mapping[str, Any],
    market_candles: Mapping[str, Any],
    write: bool,
) -> dict[str, Any]:
    """Build one immutable snapshot and persist only mature outcomes.

    All runtime inputs are explicit so this function can be reused by a CLI,
    Dagster op, or test without constructing a database session or mutating
    process configuration.
    """

    normalized_as_of = _normalize_timestamp(as_of, argument="as_of")
    maturity_now = _normalize_timestamp(evaluated_at, argument="evaluated_at")
    snapshot = build_strategy_snapshot_from_live_output(
        live_output,
        as_of=normalized_as_of,
        trade_date=trade_date,
    )
    candles = [item for item in market_candles.get("candles") or [] if isinstance(item, Mapping)]
    coverage = market_candles.get("coverage")
    expected_interval = coverage.get("expected_interval_seconds") if isinstance(coverage, Mapping) else None
    maturity = build_outcome_maturity_plan(
        snapshot,
        candles,
        now=maturity_now,
        expected_candle_interval_seconds=expected_interval,
    )
    store = EvaluationStore(storage_root)
    snapshot_result = store.write_snapshot(snapshot) if write else None
    outcome_results: dict[str, StoreWriteResult | None] = {}
    for item in maturity.horizons:
        if write and item.persistable and item.outcome is not None:
            outcome_results[item.horizon] = store.write_outcome(snapshot, item.outcome)
        else:
            outcome_results[item.horizon] = None

    return {
        "trade_date": trade_date,
        "evaluation_id": snapshot.evaluation_id,
        "maturity_id": maturity.maturity_id,
        "maturity_schema_version": maturity.schema_version,
        "evaluated_at": maturity.now.isoformat(),
        "strategy_status": live_output.get("strategy_status"),
        "publish_allowed": snapshot.publish_allowed,
        "dry_run": not write,
        "snapshot": (snapshot_result.path.as_posix() if snapshot_result else store.snapshot_path(snapshot).as_posix()),
        "snapshot_write_performed": snapshot_result is not None,
        "snapshot_created": snapshot_result.created if snapshot_result else None,
        "outcomes": {
            item.horizon: {
                "maturity_status": item.status,
                "maturity_reasons": list(item.reasons),
                "horizon_end": item.horizon_end.isoformat(),
                "status": item.outcome.status if item.outcome else None,
                "classification": item.outcome.classification if item.outcome else None,
                "write_performed": outcome_results[item.horizon] is not None,
                "created": (
                    outcome_results[item.horizon].created if outcome_results[item.horizon] is not None else None
                ),
                "path": _outcome_summary_path(
                    store=store,
                    snapshot=snapshot,
                    maturity=item,
                    result=outcome_results[item.horizon],
                ),
            }
            for item in maturity.horizons
        },
    }


def _normalize_timestamp(value: datetime, *, argument: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{argument} must include a timezone")
    return value.astimezone(timezone.utc)


def _outcome_summary_path(
    *,
    store: EvaluationStore,
    snapshot: StrategySnapshot,
    maturity: HorizonMaturity,
    result: StoreWriteResult | None,
) -> str | None:
    if result is not None:
        return result.path.as_posix()
    if maturity.persistable and maturity.outcome is not None:
        return store.outcome_path(snapshot, maturity.horizon).as_posix()
    return None


__all__ = ["run_shadow_evaluation"]
