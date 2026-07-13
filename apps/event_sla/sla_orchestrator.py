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
    event_step_outcomes,
    event_step_statuses,
    evidence_level,
)
from apps.event_sla.strategy_builder import build_trading_strategy, render_strategy_markdown
from apps.event_sla.update_detector import (
    event_execution_lock,
    load_event_execution_ledger,
    read_json,
    rel,
    stable_event_hash,
    write_event_execution_ledger,
)
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
        with event_execution_lock(storage_root=self.storage_root, trade_date=day):
            return self._process_events(
                day=day,
                observed_at=now,
                events=events,
                record_task_run=record_task_run,
            )

    def _process_events(
        self,
        *,
        day: str,
        observed_at: datetime,
        events: list[EventSnapshot],
        record_task_run: bool,
    ) -> dict[str, Any]:
        ledger = load_event_execution_ledger(storage_root=self.storage_root, trade_date=day)
        ledger_events = ledger["events"]
        results: list[dict[str, Any]] = []
        created_count = 0
        reused_count = 0
        for event in events:
            previous = ledger_events.get(event.event_id)
            observation_hash = _event_observation_hash(event)
            if _can_reuse_event(
                previous=previous,
                observation_hash=observation_hash,
                storage_root=self.storage_root,
            ):
                results.append(_reused_event_result(event=event, previous=previous))
                reused_count += 1
                continue
            result = self._run_event(event=event, observed_at=observed_at, record_task_run=record_task_run)
            result["observation_hash"] = observation_hash
            results.append(result)
            created_count += 1
            history = _execution_history(previous)
            ledger_events[event.event_id] = {
                "event_id": event.event_id,
                "event_hash": event.event_hash,
                "observation_hash": observation_hash,
                "source_key": event.source_key,
                "status": result["status"],
                "artifacts": result["artifacts"],
                "task_run_id": result["task_run_id"],
                "completed_at": observed_at.isoformat(),
                "execution_count": len(history) + 1,
                "history": history,
            }
            write_event_execution_ledger(
                storage_root=self.storage_root,
                trade_date=day,
                payload={
                    "trade_date": day,
                    "updated_at": observed_at.isoformat(),
                    "events": ledger_events,
                },
            )
        return {
            "trade_date": day,
            "observed_at": observed_at.isoformat(),
            "created_count": created_count,
            "reused_count": reused_count,
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
            "event_hash": event.event_hash,
            "source_key": event.source_key,
            "status": status,
            "execution_mode": "executed",
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
        step_statuses = event_step_statuses(event=event, status=status)
        step_outcomes = event_step_outcomes(event=event, status=status)
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
                output_refs=_output_refs_for_step(
                    step_name,
                    event=event,
                    artifacts=artifacts,
                    event_status=status,
                    step_status=step_statuses[step_name],
                    execution_mode=step_outcomes[step_name]["execution_mode"],
                ),
            )
        return recorder.run_id()


def _output_refs_for_step(
    step_name: str,
    *,
    event: EventSnapshot,
    artifacts: EventSlaArtifacts,
    event_status: str,
    step_status: str,
    execution_mode: str,
) -> list[dict[str, Any]]:
    if step_name == "collect_raw":
        refs = event.raw_refs
    elif step_name == "parse_content":
        refs = event.parsed_refs
    else:
        mapping: dict[str, list[dict[str, str]]] = {
            "create_event_snapshot": [
                {"artifact_type": "structured_json", "path": artifacts.event_snapshot_path}
            ],
            "build_analysis_conclusion": [
                {"artifact_type": "analysis_md", "path": artifacts.analysis_report_path}
            ],
            "build_trading_strategy": [
                {"artifact_type": "analysis_md", "path": artifacts.trading_strategy_path},
                {"artifact_type": "structured_json", "path": artifacts.trading_strategy_json_path},
            ],
            "build_sla_report": [
                {"artifact_type": "structured_json", "path": artifacts.sla_trace_path}
            ],
            "write_notification_request": [
                {"artifact_type": "structured_json", "path": artifacts.notification_request_path}
            ],
        }
        refs = mapping.get(step_name, [])
    metadata = _artifact_usage_metadata(
        step_name=step_name,
        event=event,
        event_status=event_status,
        step_status=step_status,
        execution_mode=execution_mode,
    )
    return [{**item, **metadata} for item in refs]


def _artifact_usage_metadata(
    *,
    step_name: str,
    event: EventSnapshot,
    event_status: str,
    step_status: str,
    execution_mode: str,
) -> dict[str, Any]:
    if execution_mode == "reused_existing_artifact":
        return {
            "quality_status": "reused",
            "usable_for": ["source_evidence"],
            "blocked_for": [],
            "execution_mode": execution_mode,
        }
    if step_name == "build_trading_strategy":
        if step_status == "blocked":
            quality_status = "preview" if evidence_level(event) == "preview" else "blocked_output"
            usable_for = ["observation"]
            blocked_for = ["actionable_strategy"]
        else:
            quality_status = "success"
            usable_for = ["observation", "actionable_strategy"]
            blocked_for = []
    elif step_name == "build_analysis_conclusion" and event_status != "success":
        quality_status = "degraded" if event_status == "partial_success" else "blocked_output"
        usable_for = ["observation"]
        blocked_for = ["full_analysis"]
    elif step_name in {"build_sla_report", "record_sla_result"}:
        quality_status = "success"
        usable_for = ["audit"]
        blocked_for = []
    elif step_name == "write_notification_request":
        quality_status = "success"
        usable_for = ["notification"]
        blocked_for = []
    else:
        quality_status = "success"
        usable_for = ["observation"]
        blocked_for = []
    return {
        "quality_status": quality_status,
        "usable_for": usable_for,
        "blocked_for": blocked_for,
        "execution_mode": execution_mode,
    }


def _event_observation_hash(event: EventSnapshot) -> str:
    payload = {
        "event_hash": event.event_hash,
        "raw_refs": event.raw_refs,
        "parsed_refs": event.parsed_refs,
        "output_refs": event.output_refs,
        "content_access": event.content_access,
        "payload": event.payload,
    }
    return stable_event_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _can_reuse_event(*, previous: Any, observation_hash: str, storage_root: Path) -> bool:
    if not isinstance(previous, dict) or previous.get("observation_hash") != observation_hash:
        return False
    artifacts = previous.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return False
    return all(isinstance(path, str) and (storage_root / path).is_file() for path in artifacts.values())


def _reused_event_result(*, event: EventSnapshot, previous: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_hash": event.event_hash,
        "observation_hash": previous.get("observation_hash"),
        "source_key": event.source_key,
        "status": previous.get("status"),
        "execution_mode": "reused",
        "evidence_level": evidence_level(event),
        "artifacts": previous.get("artifacts"),
        "task_run_id": None,
        "source_task_run_id": previous.get("task_run_id"),
    }


def _execution_history(previous: Any) -> list[dict[str, Any]]:
    if not isinstance(previous, dict):
        return []
    history = previous.get("history") if isinstance(previous.get("history"), list) else []
    prior_execution = {
        key: previous.get(key)
        for key in (
            "event_hash",
            "observation_hash",
            "status",
            "artifacts",
            "task_run_id",
            "completed_at",
        )
    }
    return [*history, prior_execution]


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
