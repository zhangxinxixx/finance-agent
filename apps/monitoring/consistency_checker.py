from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apps.monitoring.schemas import DataHealthCheck


@dataclass(frozen=True)
class NumericObservation:
    metric: str
    source: str
    value: float
    observed_at: datetime
    source_ref: str | None = None
    artifact_ref: str | None = None


@dataclass(frozen=True)
class ConsistencyRule:
    metric: str
    tolerance_pct: float
    critical_tolerance_pct: float
    max_time_gap_minutes: int


XAUUSD_CONSISTENCY_RULE = ConsistencyRule(
    metric="XAUUSD",
    tolerance_pct=0.5,
    critical_tolerance_pct=2.0,
    max_time_gap_minutes=15,
)


class MarketConsistencyChecker:
    def __init__(
        self,
        *,
        storage_root: Path | str = "storage",
        candle_loader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.storage_root = Path(storage_root)
        self.candle_loader = candle_loader or _load_latest_xauusd_candle

    def run(self, *, observed_at: datetime) -> list[DataHealthCheck]:
        primary = _load_jin10_quote(self.storage_root)
        try:
            secondary = _observation_from_candle_payload(self.candle_loader())
        except Exception as exc:  # pragma: no cover - database/runtime boundary
            return [_secondary_load_failure_check(observed_at=observed_at, exc=exc)]
        return [
            build_numeric_consistency_check(
                primary=primary,
                secondary=secondary,
                rule=XAUUSD_CONSISTENCY_RULE,
                observed_at=observed_at,
            )
        ]


def build_numeric_consistency_check(
    *,
    primary: NumericObservation | None,
    secondary: NumericObservation | None,
    rule: ConsistencyRule,
    observed_at: datetime,
) -> DataHealthCheck:
    source_key = f"consistency:{rule.metric}"
    if primary is None or secondary is None:
        missing = [name for name, value in (("primary", primary), ("secondary", secondary)) if value is None]
        return DataHealthCheck(
            source_key=source_key,
            check_type="consistency",
            status="waiting",
            severity="warning",
            observed_at=observed_at.isoformat(),
            reason_code="consistency_observation_missing",
            message=f"{rule.metric} consistency check is waiting for {', '.join(missing)} observation",
            repair_suggestion="Refresh both independent observations before evaluating a price conflict.",
            metadata={"metric": rule.metric, "missing_observations": missing, "comparison_performed": False},
        )

    primary_family = _source_family(primary.source)
    secondary_family = _source_family(secondary.source)
    time_gap_minutes = int(abs((primary.observed_at - secondary.observed_at).total_seconds()) // 60)
    base_metadata = {
        "metric": rule.metric,
        "primary_source": primary.source,
        "secondary_source": secondary.source,
        "primary_source_family": primary_family,
        "secondary_source_family": secondary_family,
        "primary_value": primary.value,
        "secondary_value": secondary.value,
        "primary_observed_at": primary.observed_at.isoformat(),
        "secondary_observed_at": secondary.observed_at.isoformat(),
        "time_gap_minutes": time_gap_minutes,
        "max_time_gap_minutes": rule.max_time_gap_minutes,
        "tolerance_pct": rule.tolerance_pct,
        "critical_tolerance_pct": rule.critical_tolerance_pct,
    }
    source_refs = [
        {"source": primary.source, "source_ref": primary.source_ref},
        {"source": secondary.source, "source_ref": secondary.source_ref},
    ]
    artifact_refs = [
        {"artifact_type": "consistency_input", "path": path}
        for path in (primary.artifact_ref, secondary.artifact_ref)
        if path
    ]

    if primary_family == secondary_family:
        return DataHealthCheck(
            source_key=source_key,
            check_type="consistency",
            status="waiting",
            severity="warning",
            observed_at=observed_at.isoformat(),
            reason_code="consistency_sources_not_independent",
            message=f"{rule.metric} observations share source family {primary_family}; cross-source comparison skipped",
            repair_suggestion="Provide an observation from an independent market-data provider.",
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            metadata={**base_metadata, "comparison_performed": False},
        )

    if time_gap_minutes > rule.max_time_gap_minutes:
        return DataHealthCheck(
            source_key=source_key,
            check_type="consistency",
            status="waiting",
            severity="warning",
            observed_at=observed_at.isoformat(),
            reason_code="consistency_time_mismatch",
            message=f"{rule.metric} observations are {time_gap_minutes} minutes apart; comparison skipped",
            repair_suggestion="Refresh the older observation before evaluating a price conflict.",
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            metadata={**base_metadata, "comparison_performed": False},
        )

    diff_abs = abs(primary.value - secondary.value)
    denominator = max(abs(primary.value), abs(secondary.value))
    diff_pct = (diff_abs / denominator * 100.0) if denominator else 0.0
    metadata = {
        **base_metadata,
        "comparison_performed": True,
        "diff_abs": diff_abs,
        "diff_pct": diff_pct,
    }
    if diff_pct <= rule.tolerance_pct:
        status = "ok"
        severity = "info"
        reason_code = None
        blocked_capabilities: tuple[str, ...] = ()
        degraded_capabilities: tuple[str, ...] = ()
        message = f"{rule.metric} cross-source difference is within tolerance"
        repair_suggestion = None
    elif diff_pct >= rule.critical_tolerance_pct:
        status = "blocked"
        severity = "critical"
        reason_code = "consistency_critical_divergence"
        blocked_capabilities = ("daily_market_snapshot", "full_daily_analysis", "technical_trigger_confirmation")
        degraded_capabilities = ()
        message = f"{rule.metric} cross-source difference exceeds critical tolerance"
        repair_suggestion = "Inspect both source artifacts and block price-sensitive analysis until the conflict is resolved."
    else:
        status = "partial"
        severity = "high"
        reason_code = "consistency_divergence"
        blocked_capabilities = ()
        degraded_capabilities = ("full_daily_analysis", "technical_trigger_confirmation")
        message = f"{rule.metric} cross-source difference exceeds warning tolerance"
        repair_suggestion = "Inspect both source artifacts before relying on price-sensitive conclusions."
    return DataHealthCheck(
        source_key=source_key,
        check_type="consistency",
        status=status,
        severity=severity,
        observed_at=observed_at.isoformat(),
        reason_code=reason_code,
        message=message,
        repair_suggestion=repair_suggestion,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        blocked_capabilities=blocked_capabilities,
        degraded_capabilities=degraded_capabilities,
        required_for=("daily_market_snapshot", "full_daily_analysis", "technical_trigger_confirmation"),
        metadata=metadata,
    )


def _load_jin10_quote(storage_root: Path) -> NumericObservation | None:
    path = storage_root / "outputs" / "jin10" / "quotes_cache.json"
    payload = _read_json(path)
    quote = ((payload.get("quotes") or {}).get("XAUUSD") or {}) if isinstance(payload, dict) else {}
    value = _float_or_none(quote.get("price"))
    observed_at = _parse_datetime(quote.get("time") or payload.get("generated_at"))
    if value is None or observed_at is None:
        return None
    return NumericObservation(
        metric="XAUUSD",
        source="jin10_mcp_market",
        value=value,
        observed_at=observed_at,
        source_ref="jin10_mcp_market:XAUUSD",
        artifact_ref=_relative(path, storage_root),
    )


def _secondary_load_failure_check(*, observed_at: datetime, exc: Exception) -> DataHealthCheck:
    return DataHealthCheck(
        source_key="consistency:XAUUSD",
        check_type="consistency",
        status="waiting",
        severity="warning",
        observed_at=observed_at.isoformat(),
        reason_code="consistency_secondary_load_failed",
        message=f"XAUUSD secondary observation could not be loaded: {type(exc).__name__}",
        repair_suggestion="Restore the market candle read model, then rerun the consistency check.",
        metadata={
            "metric": "XAUUSD",
            "comparison_performed": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )


def _observation_from_candle_payload(payload: dict[str, Any]) -> NumericObservation | None:
    candles = payload.get("candles") if isinstance(payload, dict) else None
    latest = candles[-1] if isinstance(candles, list) and candles else None
    if not isinstance(latest, dict):
        return None
    value = _float_or_none(latest.get("close"))
    observed_at = _parse_datetime(latest.get("time"))
    if value is None or observed_at is None:
        return None
    provider = str(payload.get("provider") or latest.get("source") or "market_candles")
    source_trace = payload.get("source_trace") if isinstance(payload.get("source_trace"), dict) else {}
    return NumericObservation(
        metric="XAUUSD",
        source=provider,
        value=value,
        observed_at=observed_at,
        source_ref=str(source_trace.get("primary_source") or "market_candles:XAUUSD:1m"),
        artifact_ref=str(source_trace.get("latest_raw_path")) if source_trace.get("latest_raw_path") else None,
    )


def _load_latest_xauusd_candle() -> dict[str, Any]:
    from apps.api.services.market_candle_service import get_market_candles

    return get_market_candles(asset="XAUUSD", timeframe="1m", limit=1)


def _source_family(source: str) -> str:
    normalized = source.strip().lower()
    if "jin10" in normalized:
        return "jin10"
    if "yahoo" in normalized or "yfinance" in normalized:
        return "yahoo"
    if "openbb" in normalized:
        return "openbb"
    return normalized or "unknown"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
