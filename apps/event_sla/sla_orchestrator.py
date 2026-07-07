from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.event_sla.event_watcher import discover_events
from apps.event_sla.schemas import EventSlaArtifacts, EventSnapshot
from apps.event_sla.sla_reporter import (
    EVENT_SLA_STEP_NAMES,
    build_analysis_report,
    build_notification_request,
    build_sla_trace,
    event_status,
    event_step_statuses,
    evidence_level,
)
from apps.event_sla.strategy_builder import build_trading_strategy, render_strategy_markdown
from apps.event_sla.update_detector import read_json, rel
from apps.runtime.task_recorder import record_task


class EventSlaOrchestrator:
    def __init__(self, *, storage_root: Path | str = "storage"):
        self.storage_root = Path(storage_root)

    def run(
        self,
        *,
        trade_date: str | None = None,
        observed_at: datetime | None = None,
        source_types: tuple[str, ...] = ("jin10", "cme"),
        record_task_run: bool = True,
    ) -> dict[str, Any]:
        now = _ensure_utc(observed_at or datetime.now(timezone.utc))
        day = trade_date or now.date().isoformat()
        events = discover_events(storage_root=self.storage_root, trade_date=day, observed_at=now, source_types=source_types)
        results = [self._run_event(event=event, observed_at=now, record_task_run=record_task_run) for event in events]
        return {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "created_count": len(results),
            "events": results,
        }

    def _run_event(self, *, event: EventSnapshot, observed_at: datetime, record_task_run: bool) -> dict[str, Any]:
        quality_gate = _read_quality_gate(storage_root=self.storage_root, trade_date=event.trade_date)
        status = event_status(event=event, quality_gate=quality_gate)
        level = evidence_level(event)
        strategy = build_trading_strategy(event=event, evidence_level=level)
        event_dir = self.storage_root / "event_sla" / event.trade_date / event.event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        artifacts = self._write_outputs(
            event=event,
            event_dir=event_dir,
            status=status,
            observed_at=observed_at,
            strategy=strategy,
            quality_gate=quality_gate,
        )
        task_run_id = None
        if record_task_run:
            task_run_id = _record_event_task(event=event, status=status, artifacts=artifacts)
        return {
            "event_id": event.event_id,
            "source_key": event.source_key,
            "status": status,
            "evidence_level": level,
            "artifacts": artifacts.to_dict(),
            "task_run_id": task_run_id,
        }

    def _write_outputs(
        self,
        *,
        event: EventSnapshot,
        event_dir: Path,
        status: str,
        observed_at: datetime,
        strategy: dict[str, Any],
        quality_gate: dict[str, Any] | None,
    ) -> EventSlaArtifacts:
        event_snapshot_path = event_dir / "event_snapshot.json"
        analysis_report_path = event_dir / "analysis_report.md"
        trading_strategy_path = event_dir / "trading_strategy.md"
        trading_strategy_json_path = event_dir / "trading_strategy.json"
        notification_request_path = event_dir / "notification_request.json"
        sla_trace_path = event_dir / "sla_trace.json"

        artifacts = EventSlaArtifacts(
            event_snapshot_path=rel(event_snapshot_path, self.storage_root),
            analysis_report_path=rel(analysis_report_path, self.storage_root),
            trading_strategy_path=rel(trading_strategy_path, self.storage_root),
            trading_strategy_json_path=rel(trading_strategy_json_path, self.storage_root),
            notification_request_path=rel(notification_request_path, self.storage_root),
            sla_trace_path=rel(sla_trace_path, self.storage_root),
        )
        elapsed = _elapsed_minutes(event.detected_at, observed_at)
        analysis_report = build_analysis_report(event=event, status=status, strategy=strategy, quality_gate=quality_gate)
        notification_request = build_notification_request(
            event=event,
            status=status,
            elapsed_minutes=elapsed,
            analysis_report_path=artifacts.analysis_report_path,
        )
        trace = build_sla_trace(
            event=event,
            status=status,
            observed_at=observed_at.isoformat(),
            elapsed_minutes=elapsed,
            artifacts=artifacts.to_dict(),
        )

        _write_json(event_snapshot_path, event.to_dict())
        analysis_report_path.write_text(analysis_report, encoding="utf-8")
        trading_strategy_path.write_text(render_strategy_markdown(strategy), encoding="utf-8")
        _write_json(trading_strategy_json_path, strategy)
        _write_json(notification_request_path, notification_request)
        _write_json(sla_trace_path, trace)
        return artifacts


def run_event_sla_pipeline(
    *,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    source_types: tuple[str, ...] = ("jin10", "cme"),
    record_task_run: bool = True,
) -> dict[str, Any]:
    return EventSlaOrchestrator(storage_root=storage_root).run(
        trade_date=trade_date,
        observed_at=observed_at,
        source_types=source_types,
        record_task_run=record_task_run,
    )


def _record_event_task(*, event: EventSnapshot, status: str, artifacts: EventSlaArtifacts) -> str | None:
    with record_task(task_type="event_sla_analysis", task_name="Event SLA Analysis", trade_date=event.trade_date) as recorder:
        step_statuses = event_step_statuses(status)
        for step_name in EVENT_SLA_STEP_NAMES:
            recorder.step(
                step_name,
                status=step_statuses[step_name],
                stage="event_sla",
                task_kind="event_sla_analysis",
                source_refs=[
                    {
                        "source": event.source_key,
                        "source_ref": f"event:{event.event_id}",
                        "data_date": event.trade_date,
                    }
                ],
                output_refs=_output_refs_for_step(step_name, artifacts),
            )
        return recorder.run_id()


def _output_refs_for_step(step_name: str, artifacts: EventSlaArtifacts) -> list[dict[str, str]]:
    mapping = {
        "create_event_snapshot": {"artifact_type": "event_snapshot", "path": artifacts.event_snapshot_path},
        "build_analysis_conclusion": {"artifact_type": "analysis_report", "path": artifacts.analysis_report_path},
        "build_trading_strategy": {"artifact_type": "trading_strategy", "path": artifacts.trading_strategy_path},
        "build_sla_report": {"artifact_type": "sla_trace", "path": artifacts.sla_trace_path},
        "write_notification_request": {"artifact_type": "notification_request", "path": artifacts.notification_request_path},
        "record_sla_result": {"artifact_type": "sla_trace", "path": artifacts.sla_trace_path},
    }
    item = mapping.get(step_name)
    return [item] if item else []


def _read_quality_gate(*, storage_root: Path, trade_date: str) -> dict[str, Any] | None:
    path = storage_root / "monitoring" / trade_date / "downstream_readiness.json"
    payload = read_json(path)
    return payload or None


def _elapsed_minutes(detected_at: str, observed_at: datetime) -> float:
    detected = datetime.fromisoformat(detected_at)
    if detected.tzinfo is None:
        detected = detected.replace(tzinfo=timezone.utc)
    return max(0.0, (observed_at - detected.astimezone(timezone.utc)).total_seconds() / 60)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
