from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.data_control.availability_calendar import build_data_availability_snapshot
from apps.data_control.collection_planner import build_collection_plan
from apps.data_control.hourly_reporter import build_hourly_report, render_hourly_report_markdown
from apps.data_control.processing_planner import build_processing_plan
from apps.data_control.schemas import DataControlArtifacts
from apps.data_control.task_dispatcher import build_dispatch_plan
from apps.runtime.task_recorder import record_task


class DataControlAgent:
    def __init__(self, *, storage_root: Path | str = "storage"):
        self.storage_root = Path(storage_root)

    def run(
        self,
        *,
        trade_date: str | None = None,
        observed_at: datetime | None = None,
        record_task_run: bool = True,
    ) -> dict[str, Any]:
        now = _ensure_utc(observed_at or datetime.now(timezone.utc))
        day = trade_date or now.date().isoformat()
        hour = now.strftime("%H")
        availability = build_data_availability_snapshot(storage_root=self.storage_root, trade_date=day, observed_at=now)
        collection_plan = build_collection_plan(availability_snapshot=availability)
        processing_plan = build_processing_plan(storage_root=self.storage_root, trade_date=day, observed_at=now.isoformat())
        dispatch_plan = build_dispatch_plan(collection_plan=collection_plan, processing_plan=processing_plan)
        hourly_report = build_hourly_report(
            trade_date=day,
            observed_at=now.isoformat(),
            hour=hour,
            availability_snapshot=availability,
            collection_plan=collection_plan,
            processing_plan=processing_plan,
            dispatch_plan=dispatch_plan,
        )
        artifacts = self._write_artifacts(
            day=day,
            hour=hour,
            availability=availability,
            collection_plan=collection_plan,
            processing_plan=processing_plan,
            dispatch_plan=dispatch_plan,
            hourly_report=hourly_report,
        )
        summary = {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "hour": hour,
            "status": hourly_report["status"],
            "main_analysis_readiness": hourly_report["main_analysis_readiness"],
            "knowledge_distillation_readiness": hourly_report["knowledge_distillation_readiness"],
            "artifacts": artifacts.to_dict(),
            "notification_request": hourly_report["notification_request"],
        }
        if record_task_run:
            summary["task_run_id"] = _record_data_control_task(day=day, artifacts=artifacts, hourly_report=hourly_report)
        return summary

    def _write_artifacts(
        self,
        *,
        day: str,
        hour: str,
        availability: dict[str, Any],
        collection_plan: dict[str, Any],
        processing_plan: dict[str, Any],
        dispatch_plan: dict[str, Any],
        hourly_report: dict[str, Any],
    ) -> DataControlArtifacts:
        base = self.storage_root / "data_control" / day
        base.mkdir(parents=True, exist_ok=True)
        availability_path = base / "data_availability_snapshot.json"
        collection_path = base / f"collection_plan_{hour}.json"
        processing_path = base / f"processing_plan_{hour}.json"
        dispatch_path = base / f"dispatch_plan_{hour}.json"
        report_json_path = base / f"hourly_collection_processing_report_{hour}.json"
        report_md_path = base / f"hourly_collection_processing_report_{hour}.md"
        _write_json(availability_path, availability)
        _write_json(collection_path, collection_plan)
        _write_json(processing_path, processing_plan)
        _write_json(dispatch_path, dispatch_plan)
        _write_json(report_json_path, hourly_report)
        report_md_path.write_text(render_hourly_report_markdown(hourly_report), encoding="utf-8")
        return DataControlArtifacts(
            data_availability_snapshot_path=_rel(availability_path, self.storage_root),
            collection_plan_path=_rel(collection_path, self.storage_root),
            processing_plan_path=_rel(processing_path, self.storage_root),
            dispatch_plan_path=_rel(dispatch_path, self.storage_root),
            hourly_report_json_path=_rel(report_json_path, self.storage_root),
            hourly_report_md_path=_rel(report_md_path, self.storage_root),
        )


def run_data_control_agent(
    *,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    record_task_run: bool = True,
) -> dict[str, Any]:
    return DataControlAgent(storage_root=storage_root).run(
        trade_date=trade_date,
        observed_at=observed_at,
        record_task_run=record_task_run,
    )


def _record_data_control_task(*, day: str, artifacts: DataControlArtifacts, hourly_report: dict[str, Any]) -> str | None:
    with record_task(task_type="data_control_agent", task_name="Data Control Agent", trade_date=day) as recorder:
        recorder.step(
            "write_data_control_artifacts",
            status="success",
            stage="data_control",
            task_kind="planning",
            output_refs=[
                {"artifact_type": "data_availability_snapshot", "path": artifacts.data_availability_snapshot_path},
                {"artifact_type": "collection_plan", "path": artifacts.collection_plan_path},
                {"artifact_type": "processing_plan", "path": artifacts.processing_plan_path},
                {"artifact_type": "dispatch_plan", "path": artifacts.dispatch_plan_path},
                {"artifact_type": "hourly_report_json", "path": artifacts.hourly_report_json_path},
                {"artifact_type": "hourly_report_md", "path": artifacts.hourly_report_md_path},
            ],
            source_refs=[
                {
                    "source": "data_control_agent",
                    "source_ref": f"data-control:{day}",
                    "data_date": day,
                },
                {
                    "source": "data_quality_monitor",
                    "source_ref": f"monitoring:{day}:downstream_readiness",
                    "data_date": day,
                },
            ],
        )
        recorder.step(
            "prepare_notification_request",
            status="success",
            stage="data_control",
            task_kind="notification_request",
            output_refs=[{"artifact_type": "notification_request", "kind": "hourly_report", "severity": hourly_report["notification_request"]["severity"]}],
        )
        return recorder.run_id()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
