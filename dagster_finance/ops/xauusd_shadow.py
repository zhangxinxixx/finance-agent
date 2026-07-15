"""Dagster op for the finalized XAU/USD provider shadow summary."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from dagster import Config, op
from pydantic import Field

from apps.analysis.evaluation.runner import run_shadow_evaluation
from apps.analysis.strategy.history_store import StrategyHistoryStore
from apps.api.services.live_strategy_service import (
    get_live_strategy_history,
    get_live_strategy_latest,
)
from apps.api.services.market_candle_service import get_market_candles
from apps.monitoring.xauusd_shadow_summary import (
    build_xauusd_shadow_summary,
    default_shadow_output_path,
    write_xauusd_shadow_summary,
)


class XauusdShadowConfig(Config):
    """Runtime inputs for one UTC trade-date shadow summary."""

    trade_date: Optional[str] = None
    storage_root: str = "./storage"


class XauusdLiveStrategyHistoryConfig(Config):
    """Runtime inputs for one immutable live-strategy history artifact."""

    as_of: Optional[str] = None
    storage_root: str = "./storage"


class XauusdShadowEvaluationConfig(Config):
    """Runtime inputs for replaying eligible live-strategy history."""

    evaluated_at: Optional[str] = None
    storage_root: str = "./storage"
    history_limit: int = Field(default=20, ge=1, le=100)


LIVE_STRATEGY_SCHEMA_VERSION = "live_strategy.v1"
LIVE_STRATEGY_ASSET = "XAUUSD"


def _default_trade_date() -> date:
    return (datetime.now(UTC) - timedelta(days=1)).date()


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "xauusd_shadow", "step": "shadow_summary"},
)
def xauusd_shadow_summary_op(context, config: XauusdShadowConfig) -> dict[str, Any]:
    """Build and write exactly one finalized daily shadow artifact."""
    trade_date = date.fromisoformat(config.trade_date) if config.trade_date else _default_trade_date()
    storage_root = Path(config.storage_root)
    payload = build_xauusd_shadow_summary(
        context.resources.db_session,
        trade_date=trade_date,
        storage_root=storage_root,
    )

    finalization = payload.get("finalization")
    if not isinstance(finalization, dict) or finalization.get("finalized") is not True:
        context.log.info(
            "XAUUSD shadow summary skipped: trade_date=%s finalized=%s reasons=%s",
            trade_date.isoformat(),
            finalization.get("finalized") if isinstance(finalization, dict) else None,
            payload.get("reasons", []),
        )
        return {
            "status": "skipped",
            "trade_date": trade_date.isoformat(),
            "finalized": False,
            "reasons": payload.get("reasons", []),
        }

    output_path = default_shadow_output_path(storage_root=storage_root, trade_date=trade_date)
    written_path, created = write_xauusd_shadow_summary(payload, output_path=output_path)
    context.log.info(
        "XAUUSD shadow summary finalized: trade_date=%s path=%s created=%s",
        trade_date.isoformat(),
        written_path,
        created,
    )
    return {
        "status": "written" if created else "unchanged",
        "trade_date": trade_date.isoformat(),
        "finalized": True,
        "output_path": str(written_path),
        "created": created,
    }


def _parse_as_of(value: str | None) -> datetime:
    return _parse_utc_timestamp(value, argument="as_of", default_now=True)


def _parse_utc_timestamp(
    value: str | None,
    *,
    argument: str,
    default_now: bool = False,
) -> datetime:
    if value is None:
        if default_now:
            return datetime.now(UTC)
        raise ValueError(f"{argument} must be a valid ISO-8601 UTC timestamp")
    if not isinstance(value, str):
        raise ValueError(f"{argument} must be a valid ISO-8601 UTC timestamp")
    value = value.strip()
    if not value:
        if default_now:
            return datetime.now(UTC)
        raise ValueError(f"{argument} must be a valid ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{argument} must be a valid ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{argument} must include a UTC timezone")
    return parsed.astimezone(UTC)


def _history_gate(strategy: Any) -> list[str]:
    """Return deterministic reasons when a live result cannot be frozen."""
    if not isinstance(strategy, Mapping):
        return ["strategy_payload_unavailable"]

    reasons: list[str] = []
    if strategy.get("schema_version") != LIVE_STRATEGY_SCHEMA_VERSION:
        reasons.append("schema_version_required")
    if strategy.get("asset") != LIVE_STRATEGY_ASSET:
        reasons.append("asset_identity_required")
    for field in ("strategy_id", "strategy_version", "updated_at"):
        if not isinstance(strategy.get(field), str) or not strategy[field].strip():
            reasons.append(f"{field}_required")
    if strategy.get("strategy_status") == "SUSPENDED_DATA":
        reasons.append("strategy_suspended_data")

    market = strategy.get("live_market")
    if not isinstance(market, Mapping) or market.get("status") != "available":
        reasons.append("canonical_market_unavailable")

    quality = strategy.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, Mapping) else None
    if not isinstance(quality, Mapping) or canonical is None:
        reasons.append("data_quality_unavailable")
    elif not isinstance(canonical, Mapping) or canonical.get("status") != "available":
        reasons.append("canonical_data_unavailable")
    return list(dict.fromkeys(reasons))


@op(
    required_resource_keys={"db_session"},
    name="xauusd_live_strategy_history_op",
    tags={"pipeline": "xauusd_shadow", "step": "live_strategy_history"},
)
def xauusd_live_strategy_history_op(
    context, config: XauusdLiveStrategyHistoryConfig
) -> dict[str, Any]:
    """Freeze a gated live strategy through the append-only history store."""
    as_of = _parse_as_of(config.as_of)
    strategy = get_live_strategy_latest(
        asset=LIVE_STRATEGY_ASSET,
        db=context.resources.db_session,
        now=as_of,
    )
    reasons = _history_gate(strategy)
    if reasons:
        context.log.info(
            "XAUUSD live strategy history skipped: as_of=%s reasons=%s",
            as_of.isoformat(),
            reasons,
        )
        return {
            "status": "skipped",
            "asset": LIVE_STRATEGY_ASSET,
            "as_of": as_of.isoformat(),
            "strategy_id": strategy.get("strategy_id") if isinstance(strategy, Mapping) else None,
            "strategy_version": strategy.get("strategy_version") if isinstance(strategy, Mapping) else None,
            "reasons": reasons,
        }

    result = StrategyHistoryStore(config.storage_root).write(strategy)
    context.log.info(
        "XAUUSD live strategy history %s: as_of=%s artifact_ref=%s",
        "written" if result.created else "unchanged",
        as_of.isoformat(),
        result.artifact_ref,
    )
    return {
        "status": "written" if result.created else "unchanged",
        "asset": LIVE_STRATEGY_ASSET,
        "as_of": as_of.isoformat(),
        "strategy_id": strategy["strategy_id"],
        "strategy_version": strategy["strategy_version"],
        "artifact_ref": result.artifact_ref,
        "output_path": str(result.path),
        "created": result.created,
        "reasons": [],
    }


def _evaluation_artifact_ref(path_value: Any, *, storage_root: Path) -> str:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("evaluation runner returned an invalid artifact path")
    path = Path(path_value)
    try:
        return path.resolve(strict=False).relative_to(storage_root.resolve(strict=False)).as_posix()
    except ValueError as exc:
        raise ValueError("evaluation runner artifact path escapes storage root") from exc


@op(
    required_resource_keys={"db_session"},
    name="xauusd_shadow_evaluation_op",
    tags={"pipeline": "xauusd_shadow", "step": "shadow_evaluation"},
)
def xauusd_shadow_evaluation_op(
    context,
    history_freeze: dict[str, Any],
    config: XauusdShadowEvaluationConfig,
) -> dict[str, Any]:
    """Evaluate eligible immutable strategy versions with one candle query."""
    evaluated_at = _parse_utc_timestamp(
        config.evaluated_at,
        argument="evaluated_at",
        default_now=True,
    )
    storage_root = Path(config.storage_root)
    history = get_live_strategy_history(
        asset=LIVE_STRATEGY_ASSET,
        storage_root=storage_root,
        limit=config.history_limit,
    )
    items = history.get("items")
    if not isinstance(items, list):
        raise ValueError("live strategy history returned invalid items")
    if not items:
        context.log.info(
            "XAUUSD shadow evaluation skipped: evaluated_at=%s no eligible history",
            evaluated_at.isoformat(),
        )
        return {
            "status": "skipped",
            "asset": LIVE_STRATEGY_ASSET,
            "evaluated_at": evaluated_at.isoformat(),
            "history_limit": config.history_limit,
            "history_freeze_status": history_freeze.get("status"),
            "processed": 0,
            "snapshot_counts": {"created": 0, "unchanged": 0},
            "outcome_counts": {"created": 0, "unchanged": 0, "pending": 0},
            "artifact_refs": [],
            "evaluations": [],
            "reasons": ["eligible_strategy_history_unavailable"],
        }

    market_candles = get_market_candles(
        asset=LIVE_STRATEGY_ASSET,
        timeframe="5m",
        limit=2000,
        session=context.resources.db_session,
    )
    snapshot_counts = {"created": 0, "unchanged": 0}
    outcome_counts = {"created": 0, "unchanged": 0, "pending": 0}
    artifact_refs: list[str] = []
    evaluations: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("live strategy history item must be a mapping")
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("live strategy history item must include a payload")
        updated_at = _parse_utc_timestamp(
            payload.get("updated_at"),
            argument="history payload updated_at",
        )
        trade_date = updated_at.date().isoformat()
        result = run_shadow_evaluation(
            trade_date=trade_date,
            as_of=updated_at,
            evaluated_at=evaluated_at,
            storage_root=storage_root,
            live_output=payload,
            market_candles=market_candles,
            write=True,
        )

        snapshot_created = result.get("snapshot_created")
        if not isinstance(snapshot_created, bool):
            raise ValueError("evaluation runner did not report snapshot persistence")
        snapshot_counts["created" if snapshot_created else "unchanged"] += 1
        snapshot_ref = _evaluation_artifact_ref(result.get("snapshot"), storage_root=storage_root)
        record_refs = [snapshot_ref]

        outcomes = result.get("outcomes")
        if not isinstance(outcomes, Mapping):
            raise ValueError("evaluation runner returned invalid outcomes")
        for outcome in outcomes.values():
            if not isinstance(outcome, Mapping):
                raise ValueError("evaluation runner returned an invalid outcome")
            if outcome.get("maturity_status") == "pending":
                outcome_counts["pending"] += 1
                continue
            if outcome.get("write_performed") is not True:
                raise ValueError("persistable evaluation outcome was not written")
            outcome_created = outcome.get("created")
            if not isinstance(outcome_created, bool):
                raise ValueError("evaluation runner did not report outcome persistence")
            outcome_counts["created" if outcome_created else "unchanged"] += 1
            record_refs.append(
                _evaluation_artifact_ref(outcome.get("path"), storage_root=storage_root)
            )

        artifact_refs.extend(record_refs)
        evaluations.append(
            {
                "strategy_id": payload.get("strategy_id"),
                "strategy_version": payload.get("strategy_version"),
                "trade_date": trade_date,
                "as_of": updated_at.isoformat(),
                "evaluation_id": result.get("evaluation_id"),
                "snapshot_created": snapshot_created,
                "artifact_refs": record_refs,
            }
        )

    unique_artifact_refs = list(dict.fromkeys(artifact_refs))
    context.log.info(
        "XAUUSD shadow evaluation completed: evaluated_at=%s processed=%s "
        "snapshots=%s outcomes=%s",
        evaluated_at.isoformat(),
        len(evaluations),
        snapshot_counts,
        outcome_counts,
    )
    return {
        "status": "completed",
        "asset": LIVE_STRATEGY_ASSET,
        "evaluated_at": evaluated_at.isoformat(),
        "history_limit": config.history_limit,
        "history_freeze_status": history_freeze.get("status"),
        "processed": len(evaluations),
        "snapshot_counts": snapshot_counts,
        "outcome_counts": outcome_counts,
        "artifact_refs": unique_artifact_refs,
        "evaluations": evaluations,
        "reasons": [],
    }
