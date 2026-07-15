from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from apps.api.schemas.data_source import DataSourceTestRequest
from apps.monitoring.freshness_rules import capability_impact_for_source, required_capabilities_for_source
from apps.monitoring.schemas import DataHealthCheck

DEFAULT_PROBE_SOURCE_KEYS = (
    "jin10_mcp_flash",
    "jin10_mcp_calendar",
    "jin10_mcp_market",
    "jin10_xnews_public",
    "jin10_datacenter_reports",
    "jin10_svip_reports",
)


class SourceProbeRunner:
    """Run the existing audited ingestion probes and normalize their results."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] | None = None,
        probe: Callable[..., Any] | None = None,
    ) -> None:
        self.session_factory = session_factory or _default_session_factory
        self.probe = probe or _default_probe

    def run(
        self,
        *,
        observed_at: datetime | None = None,
        source_keys: Iterable[str] = DEFAULT_PROBE_SOURCE_KEYS,
        limit: int = 5,
    ) -> list[DataHealthCheck]:
        if not 1 <= limit <= 20:
            raise ValueError("source probe limit must be between 1 and 20")
        now = observed_at or datetime.now(timezone.utc)
        checks: list[DataHealthCheck] = []
        for source_key in source_keys:
            try:
                with self.session_factory() as db:
                    response = self.probe(
                        db,
                        source_key,
                        DataSourceTestRequest(
                            actor="data_quality_monitor",
                            reason="scheduled source quality probe",
                            request_id=f"data-quality:{source_key}:{now.isoformat()}",
                            limit=limit,
                        ),
                    )
            except Exception as exc:  # pragma: no cover - runtime/database boundary
                checks.append(_probe_exception_check(source_key=source_key, observed_at=now, exc=exc))
                continue
            checks.append(build_source_probe_check(response=response, observed_at=now))
        return checks


def build_source_probe_check(*, response: Any, observed_at: datetime) -> DataHealthCheck:
    source_key = str(response.source_key)
    data_status = _enum_value(response.data_status)
    status = _health_status(probe_status=str(response.status), data_status=data_status)
    blocked_capabilities, degraded_capabilities = _capability_impact(source_key=source_key, status=status)
    summary = response.summary if isinstance(response.summary, dict) else {}
    source_refs = [_model_dict(item) for item in response.source_refs]
    artifact_refs = [_model_dict(item) for item in response.artifact_refs]
    reason_code = None if status == "ok" else str(summary.get("reason_code") or f"source_probe_{status}")
    return DataHealthCheck(
        source_key=source_key,
        check_type="source_probe",
        status=status,
        severity=_severity(status=status, blocked=bool(blocked_capabilities)),
        observed_at=observed_at.isoformat(),
        latest_artifact_ref=_latest_artifact_ref(artifact_refs),
        reason_code=reason_code,
        message=str(summary.get("reason") or summary.get("message") or f"{source_key} probe returned {status}"),
        repair_suggestion=_repair_suggestion(status=status, data_status=data_status),
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        blocked_capabilities=blocked_capabilities,
        degraded_capabilities=degraded_capabilities,
        required_for=_required_capabilities(source_key),
        metadata={
            "probe_status": str(response.status),
            "data_status": data_status,
            "run_id": response.run_id,
            "audit_id": getattr(response, "audit_id", None),
            "duration_ms": response.duration_ms,
            "preview_count": len(response.preview),
            "summary": summary,
        },
    )


def _probe_exception_check(*, source_key: str, observed_at: datetime, exc: Exception) -> DataHealthCheck:
    blocked_capabilities, degraded_capabilities = _capability_impact(source_key=source_key, status="unavailable")
    return DataHealthCheck(
        source_key=source_key,
        check_type="source_probe",
        status="unavailable",
        severity=_severity(status="unavailable", blocked=bool(blocked_capabilities)),
        observed_at=observed_at.isoformat(),
        reason_code="source_probe_execution_failed",
        message=f"{source_key} probe execution failed: {type(exc).__name__}",
        repair_suggestion="Inspect the ingestion source-test task and retry the probe.",
        blocked_capabilities=blocked_capabilities,
        degraded_capabilities=degraded_capabilities,
        required_for=_required_capabilities(source_key),
        metadata={"error_type": type(exc).__name__, "error_message": str(exc)},
    )


def _health_status(*, probe_status: str, data_status: str) -> str:
    if probe_status == "ok" and data_status == "live":
        return "ok"
    if data_status == "manual_required" or probe_status == "blocked":
        return "blocked"
    if data_status == "stale":
        return "stale"
    if data_status in {"partial", "fallback"}:
        return "partial"
    if data_status == "unavailable" or probe_status in {"failed", "unsupported"}:
        return "unavailable"
    return "unknown"


def _capability_impact(*, source_key: str, status: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blocked, degraded = capability_impact_for_source(source_key, status=status)
    if blocked or degraded or status == "ok":
        return blocked, degraded
    if source_key == "jin10_mcp_calendar":
        return (), ("full_daily_analysis",)
    return (), ()


def _required_capabilities(source_key: str) -> tuple[str, ...]:
    capabilities = required_capabilities_for_source(source_key)
    if capabilities:
        return capabilities
    if source_key == "jin10_mcp_calendar":
        return ("full_daily_analysis",)
    return ()


def _severity(*, status: str, blocked: bool) -> str:
    if status == "ok":
        return "info"
    if status in {"blocked", "unavailable"} and blocked:
        return "critical"
    if status in {"blocked", "unavailable", "stale"}:
        return "high"
    return "warning"


def _repair_suggestion(*, status: str, data_status: str) -> str | None:
    if status == "ok":
        return None
    if data_status == "manual_required":
        return "Complete the required manual or authenticated source step, then rerun the probe."
    return "Inspect the archived probe artifacts and latest ingestion_source_test TaskRun before retrying."


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return value.model_dump(mode="json", exclude_none=True)


def _latest_artifact_ref(artifact_refs: list[dict[str, Any]]) -> str | None:
    for artifact in artifact_refs:
        path = artifact.get("file_path") or artifact.get("path")
        if path:
            return str(path)
    return None


def _default_session_factory() -> Any:
    from database.models.engine import SessionLocal

    return SessionLocal()


def _default_probe(db: Any, source_key: str, body: DataSourceTestRequest) -> Any:
    from apps.api.services.ingestion_source_test_service import run_ingestion_source_test

    return run_ingestion_source_test(db, source_key, body)
