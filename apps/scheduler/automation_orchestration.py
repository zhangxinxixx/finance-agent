"""Scheduler-facing wrappers for Automation Orchestrator."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.data_control import run_data_control_agent
from apps.event_sla import run_event_sla_pipeline
from apps.monitoring import run_data_quality_monitor
from apps.notifications.notification_agent import FeishuNotificationAgent
from apps.notifications.schemas import NotificationRequest
from apps.orchestration import run_automation_orchestrator

_DEFAULT_NO_PROXY = "127.0.0.1,localhost,::1"


def run_hourly_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    send_notifications: bool = True,
    record_task_run: bool = True,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _ensure_no_proxy()
    data_control_result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        record_task_run=record_task_run,
    )
    data_quality_result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        record_task_run=record_task_run,
    )
    orchestration_result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        trigger="hourly",
        hour=now.strftime("%H"),
        send_notifications=send_notifications,
        record_task_run=record_task_run,
    )
    return {**orchestration_result, "data_control": data_control_result, "data_quality": data_quality_result}


def run_pre_analysis_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    send_notifications: bool = True,
    record_task_run: bool = True,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _ensure_no_proxy()
    data_quality_result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        record_task_run=record_task_run,
    )
    orchestration_result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        trigger="pre_analysis",
        hour=now.strftime("%H"),
        send_notifications=send_notifications,
        record_task_run=record_task_run,
    )
    return {**orchestration_result, "data_quality": data_quality_result}


def run_event_sla_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    source_types: tuple[str, ...] = ("jin10", "cme"),
    send_notifications: bool = True,
    record_task_run: bool = True,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _ensure_no_proxy()
    event_sla_result = run_event_sla_pipeline(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        source_types=source_types,
        record_task_run=record_task_run,
    )
    orchestration_result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        trigger="event_sla",
        hour=now.strftime("%H"),
        send_notifications=send_notifications,
        record_task_run=record_task_run,
    )
    return {**orchestration_result, "event_sla": event_sla_result}


def run_incident_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    send_notifications: bool = True,
    record_task_run: bool = True,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _ensure_no_proxy()
    data_quality_result = run_data_quality_monitor(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        record_task_run=record_task_run,
    )
    orchestration_result = run_automation_orchestrator(
        storage_root=storage_root,
        trade_date=day,
        observed_at=now,
        trigger="incident",
        hour=now.strftime("%H"),
        send_notifications=send_notifications,
        record_task_run=record_task_run,
    )
    return {**orchestration_result, "data_quality": data_quality_result}


def run_notification_retry_queue(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    notification_agent: Any | None = None,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _ensure_no_proxy()
    base = storage_root / "orchestration" / day
    retry_queue_path = base / "retry_queue.json"
    retry_payload = _read_json(retry_queue_path)
    items = retry_payload.get("items") if isinstance(retry_payload.get("items"), list) else []
    notification_plan = _read_json(base / "notification_plan.json")
    requests = notification_plan.get("requests") if isinstance(notification_plan.get("requests"), list) else []
    requests_by_dedupe = {str(item.get("dedupe_key")): item for item in requests if isinstance(item, dict) and item.get("dedupe_key")}

    agent = notification_agent or FeishuNotificationAgent()
    processed: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _retry_item_due(item, now):
            remaining.append(item)
            continue
        payload = requests_by_dedupe.get(str(item.get("dedupe_key")))
        if payload is None:
            remaining.append({**item, "last_retry_status": "missing_notification_request"})
            continue
        request = _notification_request_from_dict(payload)
        result = agent.send(request)
        result_payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        result_payload.update({"dedupe_key": item.get("dedupe_key"), "retried_at": now.isoformat()})
        processed.append(result_payload)
        if not result_payload.get("ok") and result_payload.get("status") == "failed":
            remaining.append({**item, "last_retry_status": "failed", "error": result_payload.get("error")})

    _write_json(retry_queue_path, {"trade_date": day, "count": len(remaining), "items": remaining})
    results_path = base / "notification_retry_results.json"
    previous_results = _read_json(results_path)
    existing_results = previous_results.get("results") if isinstance(previous_results.get("results"), list) else []
    _write_json(results_path, {"trade_date": day, "results": [*existing_results, *processed]})
    _append_delivery_log(base=base, trade_date=day, observed_at=now.isoformat(), results=processed)
    return {
        "trade_date": day,
        "observed_at": now.isoformat(),
        "processed_count": len(processed),
        "remaining_count": len(remaining),
        "results_path": _rel(results_path, storage_root),
        "retry_queue_path": _rel(retry_queue_path, storage_root),
    }


def register_automation_orchestration_jobs(scheduler: Any, *, enabled: bool) -> list[str]:
    if not enabled:
        return []
    scheduler.add_job(
        run_hourly_orchestration,
        "interval",
        minutes=60,
        id="automation_orchestration_hourly",
        replace_existing=True,
    )
    scheduler.add_job(
        run_event_sla_orchestration,
        "interval",
        minutes=5,
        id="automation_orchestration_event_sla",
        replace_existing=True,
    )
    scheduler.add_job(
        run_pre_analysis_orchestration,
        "cron",
        hour=20,
        minute=0,
        id="automation_orchestration_pre_analysis",
        replace_existing=True,
    )
    scheduler.add_job(
        run_notification_retry_queue,
        "interval",
        minutes=5,
        id="automation_orchestration_retry_queue",
        replace_existing=True,
    )
    return [
        "automation_orchestration_hourly",
        "automation_orchestration_event_sla",
        "automation_orchestration_pre_analysis",
        "automation_orchestration_retry_queue",
    ]


def _notification_request_from_dict(payload: dict[str, Any]) -> NotificationRequest:
    return NotificationRequest(
        kind=payload.get("kind", "incident"),
        title=str(payload.get("title") or "Automation retry notification"),
        summary=str(payload.get("summary") or ""),
        severity=payload.get("severity", "info"),
        facts=payload.get("facts") if isinstance(payload.get("facts"), dict) else {},
        sections=payload.get("sections") if isinstance(payload.get("sections"), list) else [],
        source_refs=payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else [],
        dry_run=bool(payload.get("dry_run")),
        trade_date=payload.get("trade_date"),
    )


def _retry_item_due(item: dict[str, Any], observed_at: datetime) -> bool:
    next_retry_at = _parse_datetime(str(item.get("next_retry_at") or ""))
    return next_retry_at is not None and next_retry_at <= observed_at


def _append_delivery_log(*, base: Path, trade_date: str, observed_at: str, results: list[dict[str, Any]]) -> None:
    deliveries = []
    for result in results:
        deliveries.append(
            {
                "dedupe_key": result.get("dedupe_key"),
                "kind": result.get("kind"),
                "status": result.get("status"),
                "ok": result.get("ok"),
                "sent_at": observed_at,
                "retried_at": result.get("retried_at"),
                "error": result.get("error"),
            }
        )
    if not deliveries:
        return
    path = base / "notification_delivery_log.json"
    payload = _read_json(path)
    existing = payload.get("deliveries") if isinstance(payload.get("deliveries"), list) else []
    _write_json(path, {"trade_date": trade_date, "deliveries": [*existing, *deliveries]})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_datetime(value: str) -> datetime | None:
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()


def _ensure_no_proxy() -> None:
    os.environ.setdefault("no_proxy", _DEFAULT_NO_PROXY)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
