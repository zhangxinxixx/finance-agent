from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.monitoring.schemas import DataHealthCheck

MONITORED_JIN10_SOURCES = (
    "jin10_mcp_market",
    "jin10_mcp_flash",
    "jin10_xnews_public",
    "jin10_svip_reports",
    "jin10_datacenter_reports",
)


@dataclass(frozen=True)
class FreshnessRule:
    source_key: str
    threshold_minutes: int
    blocked_capabilities: tuple[str, ...] = ()
    degraded_capabilities: tuple[str, ...] = ()
    stale_allowed: bool = False

    @property
    def required_for_full_analysis(self) -> bool:
        return "full_daily_analysis" in self.blocked_capabilities

    @property
    def required_for_knowledge_distillation(self) -> bool:
        return "knowledge_distillation" in self.blocked_capabilities


FRESHNESS_RULES: dict[str, FreshnessRule] = {
    "jin10_mcp_market": FreshnessRule(
        "jin10_mcp_market",
        threshold_minutes=5,
        blocked_capabilities=("daily_market_snapshot", "full_daily_analysis", "technical_trigger_confirmation"),
    ),
    "jin10_mcp_flash": FreshnessRule(
        "jin10_mcp_flash",
        threshold_minutes=10,
        degraded_capabilities=("full_daily_analysis",),
    ),
    "jin10_xnews_public": FreshnessRule(
        "jin10_xnews_public",
        threshold_minutes=60,
        degraded_capabilities=("full_daily_analysis",),
    ),
    "jin10_svip_reports": FreshnessRule(
        "jin10_svip_reports",
        threshold_minutes=24 * 60,
        blocked_capabilities=("research_report_interpretation", "knowledge_distillation"),
        degraded_capabilities=("full_daily_analysis",),
    ),
    "jin10_datacenter_reports": FreshnessRule(
        "jin10_datacenter_reports",
        threshold_minutes=24 * 60,
        degraded_capabilities=("full_daily_analysis",),
        stale_allowed=True,
    ),
}


def build_source_freshness_checks(
    *,
    health_snapshot: dict[str, Any],
    observed_at: datetime,
    source_keys: tuple[str, ...] = MONITORED_JIN10_SOURCES,
) -> list[DataHealthCheck]:
    items = {
        str(item.get("source_key")): item
        for item in health_snapshot.get("items", [])
        if isinstance(item, dict) and item.get("source_key")
    }
    checks: list[DataHealthCheck] = []
    for source_key in source_keys:
        rule = FRESHNESS_RULES[source_key]
        item = items.get(source_key)
        if item is None:
            blocked_capabilities, degraded_capabilities = capability_impact_for_source(source_key, status="unavailable")
            checks.append(
                DataHealthCheck(
                    source_key=source_key,
                    check_type="freshness",
                    status="unavailable",
                    severity="critical" if blocked_capabilities else "warning",
                    observed_at=observed_at.isoformat(),
                    freshness_threshold_minutes=rule.threshold_minutes,
                    reason_code="source_missing_from_read_model",
                    message=f"{source_key} is missing from data-source health read model",
                    repair_suggestion="Run source registration/status refresh before downstream analysis.",
                    blocked_capabilities=blocked_capabilities,
                    degraded_capabilities=degraded_capabilities,
                    required_for=required_capabilities_for_source(source_key),
                )
            )
            continue
        checks.append(_check_from_source_item(item=item, rule=rule, observed_at=observed_at))
    return checks


def _check_from_source_item(*, item: dict[str, Any], rule: FreshnessRule, observed_at: datetime) -> DataHealthCheck:
    source_key = str(item.get("source_key") or rule.source_key)
    data_status = str(item.get("data_status") or "unavailable").lower()
    freshness_status = str(item.get("freshness_status") or "unknown").lower()
    latest_observed_at = item.get("latest_health_at") or item.get("latest_data_date")
    latest_dt = _parse_datetime(latest_observed_at)
    lag_minutes = int((observed_at - latest_dt).total_seconds() // 60) if latest_dt else None
    status = _status(data_status=data_status, freshness_status=freshness_status, lag_minutes=lag_minutes, rule=rule)
    severity = _severity(status=status, required=bool(rule.blocked_capabilities))
    reason_code = None
    if status == "stale":
        reason_code = "freshness_stale"
    elif status == "partial":
        reason_code = str(item.get("gating_reason") or item.get("freshness_reason") or "source_partial")
    elif status in {"unavailable", "blocked", "unknown"}:
        reason_code = str(item.get("gating_reason") or item.get("freshness_reason") or "source_unavailable")
    message = _message(source_key=source_key, status=status, lag_minutes=lag_minutes, threshold=rule.threshold_minutes)
    blocked_capabilities, degraded_capabilities = capability_impact_for_source(source_key, status=status)
    return DataHealthCheck(
        source_key=source_key,
        check_type="freshness",
        status=status,
        severity=severity,
        observed_at=observed_at.isoformat(),
        latest_observed_at=str(latest_observed_at) if latest_observed_at else None,
        freshness_threshold_minutes=rule.threshold_minutes,
        lag_minutes=lag_minutes,
        reason_code=reason_code,
        message=message,
        repair_suggestion=_repair_suggestion(status),
        source_refs=[{"source": "data_source_health", "source_key": source_key}],
        blocked_capabilities=blocked_capabilities,
        degraded_capabilities=degraded_capabilities,
        required_for=required_capabilities_for_source(source_key),
        metadata={
            "data_status": data_status,
            "freshness_status": freshness_status,
            "freshness_reason": item.get("freshness_reason"),
            "health_state": item.get("health_state"),
            "readiness_state": item.get("readiness_state"),
            "gate_state": item.get("gate_state"),
            "required_for_full_analysis": rule.required_for_full_analysis,
            "required_for_knowledge_distillation": rule.required_for_knowledge_distillation,
            "stale_allowed": rule.stale_allowed,
        },
    )


def _status(*, data_status: str, freshness_status: str, lag_minutes: int | None, rule: FreshnessRule) -> str:
    if data_status == "waiting" or freshness_status == "waiting":
        return "waiting"
    if data_status == "unavailable":
        return "unavailable"
    if freshness_status == "stale" or (lag_minutes is not None and lag_minutes > rule.threshold_minutes):
        return "stale"
    if data_status == "live":
        return "ok"
    if data_status == "partial":
        return "partial"
    return "unknown"


def _severity(*, status: str, required: bool) -> str:
    if status == "ok":
        return "info"
    if status == "waiting":
        return "warning"
    if status in {"unavailable", "blocked"}:
        return "critical" if required else "warning"
    if status == "stale":
        return "high" if required else "warning"
    return "warning"


def _message(*, source_key: str, status: str, lag_minutes: int | None, threshold: int) -> str:
    if status == "ok":
        return f"{source_key} is fresh"
    if status == "waiting":
        return f"{source_key} is waiting for its expected publication"
    if status == "stale":
        return f"{source_key} is stale; lag={lag_minutes}m threshold={threshold}m"
    if status == "partial":
        return f"{source_key} is partially available"
    if status == "unavailable":
        return f"{source_key} is unavailable"
    return f"{source_key} freshness is unknown"


def _repair_suggestion(status: str) -> str | None:
    if status in {"ok", "waiting", "partial"}:
        return None
    if status == "stale":
        return "Refresh the source before allowing full analysis or distillation."
    return "Run the source probe or collector and inspect latest task_runs."


def required_capabilities_for_source(source_key: str) -> tuple[str, ...]:
    rule = FRESHNESS_RULES.get(source_key)
    if rule is None:
        return ()
    return tuple(dict.fromkeys((*rule.blocked_capabilities, *rule.degraded_capabilities)))


def capability_impact_for_source(source_key: str, *, status: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if status == "ok":
        return (), ()
    rule = FRESHNESS_RULES.get(source_key)
    if rule is None:
        return (), ()
    if status == "waiting":
        degraded = tuple(dict.fromkeys((*rule.blocked_capabilities, *rule.degraded_capabilities)))
        return (), degraded
    return rule.blocked_capabilities, rule.degraded_capabilities


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
