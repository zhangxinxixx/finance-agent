"""Append-only replay of legacy shadow outcomes under the current contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from apps.features.market_data import select_canonical_xauusd_rows

from .outcomes import HORIZONS, evaluate_strategy_outcome
from .store import EvaluationStore
from .strategy_snapshot import StrategySnapshot, build_strategy_snapshot

REPLAY_REVISION = "shadow-evaluation-contract-v2-replay"
EXPECTED_INTERVAL_SECONDS = 300


class ReplayCoverageError(ValueError):
    """The selected historical market path is not complete enough to replay."""


def run_shadow_replay(
    *,
    snapshot_payload: Mapping[str, Any],
    market_rows: Sequence[Any],
    horizon: str,
    storage_root: str | Path,
    write: bool = False,
) -> dict[str, Any]:
    """Replay one explicit horizon without modifying the legacy artifacts."""

    if horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon: {horizon}")
    legacy_id = _required_text(snapshot_payload, "evaluation_id")
    as_of = _parse_timestamp(snapshot_payload.get("as_of"), field="as_of")
    horizon_end = _horizon_end(as_of, horizon)
    canonical = select_canonical_xauusd_rows(market_rows)
    candles = [_candle_payload(row) for row in canonical]
    candles = [item for item in candles if item is not None]
    window = [
        item
        for item in candles
        if _parse_timestamp(item["time"], field="candle.time") > as_of
        and _parse_timestamp(item["time"], field="candle.time") + timedelta(seconds=EXPECTED_INTERVAL_SECONDS)
        <= horizon_end
    ]
    coverage = _validate_coverage(window, as_of=as_of, horizon_end=horizon_end)
    market_ref = {
        "source": "canonical_xauusd_5m_replay",
        "status": "complete",
        "horizon": horizon,
        "first_open_time": coverage["first_open_time"],
        "last_open_time": coverage["last_open_time"],
        "candle_count": coverage["candle_count"],
        "providers": coverage["providers"],
        "series_sha256": _series_hash(window),
    }
    snapshot = build_replay_snapshot(
        snapshot_payload,
        market_source_ref=market_ref,
        revision=f"{REPLAY_REVISION}:{horizon}",
    )
    outcome = evaluate_strategy_outcome(
        snapshot,
        window,
        horizon=horizon,
        expected_candle_interval_seconds=EXPECTED_INTERVAL_SECONDS,
    )
    store = EvaluationStore(storage_root)
    snapshot_result = store.write_snapshot(snapshot) if write else None
    outcome_result = store.write_outcome(snapshot, outcome) if write else None
    return {
        "schema_version": "shadow_evaluation_replay.v1",
        "dry_run": not write,
        "supersedes_evaluation_id": legacy_id,
        "evaluation_id": snapshot.evaluation_id,
        "horizon": horizon,
        "coverage": coverage,
        "outcome": {
            "status": outcome.status,
            "classification": outcome.classification,
            "lifecycle_status": outcome.lifecycle_status,
            "reason_codes": list(outcome.reason_codes),
            "scoreable": outcome.scoreable,
        },
        "snapshot": {
            "path": store.snapshot_path(snapshot).as_posix(),
            "write_performed": snapshot_result is not None,
            "created": snapshot_result.created if snapshot_result else None,
        },
        "outcome_artifact": {
            "path": store.outcome_path(snapshot, horizon).as_posix(),
            "write_performed": outcome_result is not None,
            "created": outcome_result.created if outcome_result else None,
        },
    }


def build_replay_snapshot(
    payload: Mapping[str, Any],
    *,
    market_source_ref: Mapping[str, Any],
    revision: str = REPLAY_REVISION,
) -> StrategySnapshot:
    """Rebuild a legacy snapshot with explicit supersession lineage."""

    legacy_id = _required_text(payload, "evaluation_id")
    evaluation_setups = payload.get("evaluation_setups")
    normalized_setups = (
        [dict(item) for item in evaluation_setups if isinstance(item, Mapping)]
        if isinstance(evaluation_setups, (list, tuple))
        else None
    )
    source_refs = [dict(item) for item in payload.get("source_refs") or [] if isinstance(item, Mapping)]
    source_refs.append(dict(market_source_ref))
    artifact_refs = list(payload.get("artifact_refs") or [])
    artifact_refs.append(
        {
            "artifact_type": "superseded_strategy_snapshot",
            "evaluation_id": legacy_id,
        }
    )
    return build_strategy_snapshot(
        account_id=_required_text(payload, "account_id"),
        asset=_required_text(payload, "asset"),
        trade_date=_required_text(payload, "trade_date"),
        run_id=_required_text(payload, "run_id"),
        strategy_id=_required_text(payload, "strategy_id"),
        strategy_version=_required_text(payload, "strategy_version"),
        prompt_version=_optional_text(payload.get("prompt_version")),
        as_of=_parse_timestamp(payload.get("as_of"), field="as_of"),
        reference_price=_optional_number(payload.get("reference_price")),
        bias=_required_text(payload, "bias"),
        confidence=_optional_number(payload.get("confidence")),
        mode=str(payload.get("mode") or "shadow"),
        publish_allowed=bool(payload.get("publish_allowed")),
        quality_gate=_mapping(payload.get("quality_gate")),
        key_levels=_mapping_list(payload.get("key_levels")),
        entry_conditions=_mapping_list(payload.get("entry_conditions")),
        evaluation_setups=normalized_setups,
        invalidation=_mapping(payload.get("invalidation")),
        risk=_mapping(payload.get("risk")),
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        revision=revision,
        supersedes_evaluation_id=legacy_id,
    )


def _validate_coverage(
    candles: list[dict[str, Any]],
    *,
    as_of: datetime,
    horizon_end: datetime,
) -> dict[str, Any]:
    interval = timedelta(seconds=EXPECTED_INTERVAL_SECONDS)
    if not candles:
        raise ReplayCoverageError("historical 5m path is unavailable for the selected horizon")
    times = [_parse_timestamp(item["time"], field="candle.time") for item in candles]
    gaps = [
        int((current - previous).total_seconds())
        for previous, current in zip(times, times[1:], strict=False)
        if current - previous > interval
    ]
    first_observed = times[0] + interval
    last_observed = times[-1] + interval
    # A snapshot can land inside the currently forming 5m bar. The evaluator
    # intentionally starts from the next bar open, so its first observable
    # close may be almost two intervals after ``as_of`` without a data gap.
    if first_observed - as_of > interval * 2:
        gaps.insert(0, int((first_observed - as_of).total_seconds()))
    if horizon_end - last_observed >= interval:
        gaps.append(int((horizon_end - last_observed).total_seconds()))
    if gaps:
        raise ReplayCoverageError(f"historical 5m path contains gaps: {gaps}")
    return {
        "status": "complete",
        "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS,
        "candle_count": len(candles),
        "first_open_time": times[0].isoformat(),
        "last_open_time": times[-1].isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "providers": sorted({str(item.get("source") or "unknown") for item in candles}),
        "gap_count": 0,
    }


def _candle_payload(row: Any) -> dict[str, Any] | None:
    timestamp = _value(row, "open_time")
    if not isinstance(timestamp, datetime):
        return None
    open_price = _optional_number(_value(row, "open"))
    high = _optional_number(_value(row, "high"))
    low = _optional_number(_value(row, "low"))
    close = _optional_number(_value(row, "close"))
    if any(value is None or value <= 0 for value in (high, low, close)) or high < low:
        return None
    return {
        "time": _as_utc(timestamp).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "partial": False,
        "source": str(_value(row, "source") or "unknown"),
    }


def _series_hash(candles: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(list(candles), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _horizon_end(as_of: datetime, horizon: str) -> datetime:
    if horizon == "session":
        return datetime.combine(as_of.date(), datetime.max.time(), tzinfo=UTC)
    return as_of + timedelta(hours={"1h": 1, "4h": 4, "24h": 24}[horizon])


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO-8601") from exc
    else:
        raise ValueError(f"{field} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"snapshot {field} is required")
    return value


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _value(row: Any, key: str) -> Any:
    return row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["ReplayCoverageError", "build_replay_snapshot", "run_shadow_replay"]
