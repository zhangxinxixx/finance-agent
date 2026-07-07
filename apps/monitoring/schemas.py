from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

HealthStatus = Literal["ok", "stale", "partial", "unavailable", "blocked", "unknown"]
Severity = Literal["info", "warning", "high", "critical"]


@dataclass(frozen=True)
class DataHealthCheck:
    source_key: str
    check_type: str
    status: HealthStatus
    severity: Severity
    observed_at: str
    message: str
    expected_at: str | None = None
    latest_observed_at: str | None = None
    freshness_threshold_minutes: int | None = None
    lag_minutes: int | None = None
    latest_artifact_ref: str | None = None
    reason_code: str | None = None
    repair_suggestion: str | None = None
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "check_type": self.check_type,
            "status": self.status,
            "severity": self.severity,
            "observed_at": self.observed_at,
            "expected_at": self.expected_at,
            "latest_observed_at": self.latest_observed_at,
            "freshness_threshold_minutes": self.freshness_threshold_minutes,
            "lag_minutes": self.lag_minutes,
            "latest_artifact_ref": self.latest_artifact_ref,
            "source_refs": self.source_refs,
            "artifact_refs": self.artifact_refs,
            "reason_code": self.reason_code,
            "message": self.message,
            "repair_suggestion": self.repair_suggestion,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class MonitoringArtifacts:
    source_health_path: str
    data_quality_report_path: str
    downstream_readiness_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_health": self.source_health_path,
            "data_quality_report": self.data_quality_report_path,
            "downstream_readiness": self.downstream_readiness_path,
        }
