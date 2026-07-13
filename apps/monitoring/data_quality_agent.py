from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.api.services.source_service import get_data_source_health_latest
from apps.monitoring.completeness_checker import build_artifact_completeness_checks, jin10_report_access_checks
from apps.monitoring.freshness_rules import MONITORED_JIN10_SOURCES, build_source_freshness_checks
from apps.monitoring.schemas import DATA_QUALITY_CAPABILITIES, DataHealthCheck, MonitoringArtifacts
from apps.runtime.task_recorder import record_task


class DataQualityMonitorAgent:
    def __init__(self, *, storage_root: Path | str = "storage"):
        self.storage_root = Path(storage_root)

    def run(
        self,
        *,
        trade_date: str | None = None,
        observed_at: datetime | None = None,
        record_task_run: bool = True,
    ) -> dict[str, Any]:
        now = observed_at or datetime.now(timezone.utc)
        day = trade_date or now.date().isoformat()
        source_snapshot = get_data_source_health_latest(date=day)
        freshness_checks = build_source_freshness_checks(health_snapshot=source_snapshot, observed_at=now)
        completeness_checks = build_artifact_completeness_checks(storage_root=self.storage_root, trade_date=day, observed_at=now)
        permission_checks = jin10_report_access_checks(storage_root=self.storage_root, trade_date=day, observed_at=now)
        all_checks = [*freshness_checks, *completeness_checks, *permission_checks]
        source_health = _source_health_report(day=day, observed_at=now, source_snapshot=source_snapshot, freshness_checks=freshness_checks)
        data_quality = _data_quality_report(
            day=day,
            observed_at=now,
            checks=all_checks,
            completeness_checks=completeness_checks,
            permission_checks=permission_checks,
        )
        downstream = _downstream_readiness(day=day, observed_at=now, checks=all_checks)
        artifacts = self._write_reports(day=day, source_health=source_health, data_quality=data_quality, downstream=downstream)
        summary = {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "source_health": source_health,
            "data_quality_report": data_quality,
            "downstream_readiness": downstream,
            "artifacts": artifacts.to_dict(),
        }
        if record_task_run:
            summary["task_run_id"] = _record_monitor_task(day=day, artifacts=artifacts, checks=all_checks)
        return summary

    def _write_reports(
        self,
        *,
        day: str,
        source_health: dict[str, Any],
        data_quality: dict[str, Any],
        downstream: dict[str, Any],
    ) -> MonitoringArtifacts:
        base = self.storage_root / "monitoring" / day
        base.mkdir(parents=True, exist_ok=True)
        source_path = base / "source_health.json"
        quality_path = base / "data_quality_report.json"
        readiness_path = base / "downstream_readiness.json"
        _write_json(source_path, source_health)
        _write_json(quality_path, data_quality)
        _write_json(readiness_path, downstream)
        return MonitoringArtifacts(
            source_health_path=_rel(source_path, self.storage_root),
            data_quality_report_path=_rel(quality_path, self.storage_root),
            downstream_readiness_path=_rel(readiness_path, self.storage_root),
        )


def run_data_quality_monitor(
    *,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    record_task_run: bool = True,
) -> dict[str, Any]:
    return DataQualityMonitorAgent(storage_root=storage_root).run(
        trade_date=trade_date,
        observed_at=observed_at,
        record_task_run=record_task_run,
    )


def _source_health_report(
    *,
    day: str,
    observed_at: datetime,
    source_snapshot: dict[str, Any],
    freshness_checks: list[DataHealthCheck],
) -> dict[str, Any]:
    return {
        "trade_date": day,
        "observed_at": observed_at.isoformat(),
        "source": "data_source_health_read_model",
        "overall_status": _overall_status(freshness_checks),
        "monitored_sources": list(MONITORED_JIN10_SOURCES),
        "checks": [check.to_dict() for check in freshness_checks],
        "upstream_snapshot": {
            "snapshot_date": source_snapshot.get("snapshot_date"),
            "as_of": source_snapshot.get("as_of"),
            "overall_status": source_snapshot.get("overall_status"),
            "counts": source_snapshot.get("counts"),
        },
    }


def _data_quality_report(
    *,
    day: str,
    observed_at: datetime,
    checks: list[DataHealthCheck],
    completeness_checks: list[DataHealthCheck],
    permission_checks: list[DataHealthCheck],
) -> dict[str, Any]:
    problem_checks = [check for check in checks if check.status != "ok"]
    return {
        "trade_date": day,
        "observed_at": observed_at.isoformat(),
        "overall_status": _overall_status(checks),
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "total_checks": len(checks),
            "problem_count": len(problem_checks),
            "freshness_problem_count": sum(1 for check in checks if check.check_type == "freshness" and check.status != "ok"),
            "completeness_problem_count": sum(1 for check in completeness_checks if check.status != "ok"),
            "permission_problem_count": sum(1 for check in permission_checks if check.status != "ok"),
        },
        "blocking_issues": [_issue(check) for check in problem_checks if check.blocked_capabilities],
        "degraded_issues": [_issue(check) for check in problem_checks if check.degraded_capabilities],
    }


def _downstream_readiness(*, day: str, observed_at: datetime, checks: list[DataHealthCheck]) -> dict[str, Any]:
    capabilities = {capability: "allowed" for capability in DATA_QUALITY_CAPABILITIES}
    for check in checks:
        if check.status == "ok":
            continue
        for capability in check.degraded_capabilities:
            if capabilities.get(capability) == "allowed":
                capabilities[capability] = "degraded"
        for capability in check.blocked_capabilities:
            capabilities[capability] = "blocked"

    blocking_checks = [check for check in checks if check.status != "ok" and check.blocked_capabilities]
    degraded_checks = [check for check in checks if check.status != "ok" and check.degraded_capabilities]
    full_analysis_state = capabilities["full_daily_analysis"]
    distillation_state = capabilities["knowledge_distillation"]
    can_run_full_analysis = full_analysis_state != "blocked"
    can_run_research_distillation = distillation_state != "blocked"
    if full_analysis_state == "blocked":
        readiness = "blocked"
    elif any(state != "allowed" for state in capabilities.values()):
        readiness = "partial"
    else:
        readiness = "ready"

    allowed_outputs: list[str] = []
    if capabilities["daily_market_snapshot"] != "blocked":
        allowed_outputs.append("market snapshot")
    if full_analysis_state == "allowed":
        allowed_outputs.append("full daily analysis")
    elif full_analysis_state == "degraded":
        allowed_outputs.append("limited daily analysis")
    if distillation_state == "allowed":
        allowed_outputs.append("knowledge distillation")
    elif distillation_state == "degraded":
        allowed_outputs.append("limited knowledge distillation")

    blocked_outputs: list[str] = []
    if full_analysis_state == "blocked":
        blocked_outputs.append("full analysis")
    if distillation_state == "blocked":
        blocked_outputs.append("knowledge distillation")
    return {
        "trade_date": day,
        "observed_at": observed_at.isoformat(),
        "readiness": readiness,
        "capabilities": capabilities,
        "can_run_daily_report": True,
        "can_run_full_analysis": can_run_full_analysis,
        "can_run_research_distillation": can_run_research_distillation,
        "allowed_outputs": allowed_outputs,
        "blocked_outputs": blocked_outputs,
        "blocking_issues": [_issue(check) for check in blocking_checks],
        "degraded_issues": [_issue(check) for check in degraded_checks],
    }


def _record_monitor_task(*, day: str, artifacts: MonitoringArtifacts, checks: list[DataHealthCheck]) -> str | None:
    with record_task(task_type="data_quality_monitor", task_name="Data Quality Monitor", trade_date=day) as recorder:
        recorder.step(
            "write_monitoring_artifacts",
            status="success",
            stage="monitoring",
            task_kind="data_quality",
            output_refs=[
                {"artifact_type": "source_health", "path": artifacts.source_health_path},
                {"artifact_type": "data_quality_report", "path": artifacts.data_quality_report_path},
                {"artifact_type": "downstream_readiness", "path": artifacts.downstream_readiness_path},
            ],
            source_refs=[
                {
                    "source": "data_source_health_read_model",
                    "source_ref": f"data-source-health:{day}",
                    "data_date": day,
                }
            ],
        )
        if any(check.status != "ok" for check in checks):
            recorder.step(
                "quality_gate_findings",
                status="success",
                stage="monitoring",
                task_kind="data_quality",
                output_refs=[{"artifact_type": "quality_findings", "problem_count": sum(1 for check in checks if check.status != "ok")}],
            )
        return recorder.run_id()


def _overall_status(checks: list[DataHealthCheck]) -> str:
    if any(check.severity == "critical" for check in checks):
        return "blocked"
    if any(check.status in {"waiting", "stale", "partial", "unavailable", "blocked", "unknown"} for check in checks):
        return "partial"
    return "ok"


def _issue(check: DataHealthCheck) -> dict[str, Any]:
    return {
        "source_key": check.source_key,
        "check_type": check.check_type,
        "status": check.status,
        "severity": check.severity,
        "reason_code": check.reason_code,
        "message": check.message,
        "repair_suggestion": check.repair_suggestion,
        "blocked_capabilities": list(check.blocked_capabilities),
        "degraded_capabilities": list(check.degraded_capabilities),
        "required_for": list(check.required_for),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
