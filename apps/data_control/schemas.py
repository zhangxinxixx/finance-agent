from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ControlState = Literal["available", "waiting", "missing", "stale", "blocked"]
PlanAction = Literal["no_action", "wait", "collect", "refresh", "manual_review"]


@dataclass(frozen=True)
class AvailabilityRule:
    source_key: str
    label: str
    source_type: str
    artifact_globs: tuple[str, ...]
    due_time_utc: str | None = None
    freshness_threshold_minutes: int | None = None
    required_for: tuple[str, ...] = ()
    missing_policy: str = "degrade"


@dataclass(frozen=True)
class AvailabilityItem:
    source_key: str
    label: str
    source_type: str
    state: ControlState
    observed_at: str
    expected_at: str | None = None
    latest_artifact_ref: str | None = None
    latest_observed_at: str | None = None
    lag_minutes: int | None = None
    reason_code: str | None = None
    message: str = ""
    required_for: tuple[str, ...] = ()
    missing_policy: str = "degrade"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "label": self.label,
            "source_type": self.source_type,
            "state": self.state,
            "observed_at": self.observed_at,
            "expected_at": self.expected_at,
            "latest_artifact_ref": self.latest_artifact_ref,
            "latest_observed_at": self.latest_observed_at,
            "lag_minutes": self.lag_minutes,
            "reason_code": self.reason_code,
            "message": self.message,
            "required_for": list(self.required_for),
            "missing_policy": self.missing_policy,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DataControlArtifacts:
    data_availability_snapshot_path: str
    collection_plan_path: str
    processing_plan_path: str
    dispatch_plan_path: str
    hourly_report_json_path: str
    hourly_report_md_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "data_availability_snapshot": self.data_availability_snapshot_path,
            "collection_plan": self.collection_plan_path,
            "processing_plan": self.processing_plan_path,
            "dispatch_plan": self.dispatch_plan_path,
            "hourly_report_json": self.hourly_report_json_path,
            "hourly_report_md": self.hourly_report_md_path,
        }
