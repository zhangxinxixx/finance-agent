"""Fail-closed readiness gate for the canonical premarket graph."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dagster import Config, op


DEFAULT_MAX_AGE_MINUTES = 60


class PremarketReadinessGateConfig(Config):
    storage_root: str = "./storage"
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES
    observed_at: str | None = None


def evaluate_premarket_readiness(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    """Evaluate the persisted data-quality readiness artifact.

    This is intentionally independent from the agent quality gate: it decides
    whether domain agents may start at all. Missing, malformed, stale, or
    blocked readiness is never treated as publishable.
    """

    path = storage_root / "monitoring" / trade_date / "downstream_readiness.json"
    source_ref = path.relative_to(storage_root).as_posix()
    readiness = _read_json(path)
    now = _as_utc(observed_at or datetime.now(timezone.utc))
    if readiness is None:
        return _blocked(source_ref, "downstream_readiness_missing", trade_date, max_age_minutes)

    artifact_trade_date = str(readiness.get("trade_date") or "")
    if artifact_trade_date != trade_date:
        return _blocked(
            source_ref,
            "downstream_readiness_trade_date_mismatch",
            trade_date,
            max_age_minutes,
            artifact_trade_date=artifact_trade_date or None,
        )

    gate_time = _parse_datetime(readiness.get("observed_at"))
    if gate_time is None:
        return _blocked(source_ref, "downstream_readiness_timestamp_missing", trade_date, max_age_minutes)

    age_minutes = int((now - gate_time).total_seconds() // 60)
    if age_minutes < -5:
        return _blocked(
            source_ref,
            "downstream_readiness_from_future",
            trade_date,
            max_age_minutes,
            observed_at=gate_time.isoformat(),
            age_minutes=age_minutes,
        )
    if age_minutes > max_age_minutes:
        return _blocked(
            source_ref,
            "downstream_readiness_stale",
            trade_date,
            max_age_minutes,
            observed_at=gate_time.isoformat(),
            age_minutes=age_minutes,
        )

    readiness_state = str(readiness.get("readiness") or "unknown")
    capabilities = readiness.get("capabilities")
    full_analysis = capabilities.get("full_daily_analysis") if isinstance(capabilities, dict) else None
    can_run_full = readiness.get("can_run_full_analysis")
    if readiness_state not in {"ready", "partial"}:
        return _blocked(
            source_ref,
            "downstream_readiness_not_ready",
            trade_date,
            max_age_minutes,
            observed_at=gate_time.isoformat(),
            age_minutes=age_minutes,
            readiness=readiness_state,
            blocked_outputs=readiness.get("blocked_outputs") or [],
        )
    if can_run_full is not True or full_analysis in {None, "blocked"}:
        return _blocked(
            source_ref,
            "downstream_full_analysis_blocked",
            trade_date,
            max_age_minutes,
            observed_at=gate_time.isoformat(),
            age_minutes=age_minutes,
            readiness=readiness_state,
            blocked_outputs=readiness.get("blocked_outputs") or [],
        )

    return {
        "decision": "allow",
        "readiness": readiness_state,
        "reason_code": None,
        "trade_date": trade_date,
        "artifact_trade_date": artifact_trade_date,
        "source_ref": source_ref,
        "observed_at": gate_time.isoformat(),
        "age_minutes": age_minutes,
        "max_age_minutes": max_age_minutes,
        "capabilities": capabilities if isinstance(capabilities, dict) else {},
        "blocked_outputs": readiness.get("blocked_outputs") or [],
    }


@op(tags={"pipeline": "premarket", "step": "readiness_gate"})
def premarket_readiness_gate_op(
    context,
    config: PremarketReadinessGateConfig,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Gate the canonical C4 graph using the snapshot's trade date."""

    trade_date = _snapshot_trade_date(snapshot)
    decision = evaluate_premarket_readiness(
        storage_root=Path(config.storage_root),
        trade_date=trade_date,
        observed_at=_parse_datetime(config.observed_at) if config.observed_at else None,
        max_age_minutes=config.max_age_minutes,
    )
    context.log.info(
        "Premarket readiness gate: decision=%s trade_date=%s reason=%s",
        decision["decision"],
        trade_date,
        decision.get("reason_code"),
    )
    return decision


def _snapshot_trade_date(snapshot: dict[str, Any]) -> str:
    value = snapshot.get("trade_date")
    if not value and isinstance(snapshot.get("metadata"), dict):
        value = snapshot["metadata"].get("trade_date") or snapshot["metadata"].get("as_of")
    if not value:
        value = snapshot.get("as_of")
    if not value:
        raise ValueError("premarket readiness gate requires snapshot trade_date")
    return str(value)[:10]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _blocked(
    source_ref: str,
    reason_code: str,
    trade_date: str,
    max_age_minutes: int,
    *,
    observed_at: str | None = None,
    age_minutes: int | None = None,
    artifact_trade_date: str | None = None,
    readiness: str | None = None,
    blocked_outputs: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "decision": "block",
        "readiness": readiness,
        "reason_code": reason_code,
        "trade_date": trade_date,
        "artifact_trade_date": artifact_trade_date,
        "source_ref": source_ref,
        "observed_at": observed_at,
        "age_minutes": age_minutes,
        "max_age_minutes": max_age_minutes,
        "capabilities": {},
        "blocked_outputs": blocked_outputs or [],
    }
