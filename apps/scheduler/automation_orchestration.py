"""Business execution wrappers launched by Dagster or explicit manual calls."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
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
    run_id: str | None = None,
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
        run_id=run_id,
    )
    return {**orchestration_result, "data_control": data_control_result, "data_quality": data_quality_result}


def run_pre_analysis_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    send_notifications: bool = True,
    record_task_run: bool = True,
    run_id: str | None = None,
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
        run_id=run_id,
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
    run_id: str | None = None,
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
        run_id=run_id,
    )
    return {**orchestration_result, "event_sla": event_sla_result}


def run_incident_orchestration(
    *,
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    storage_root: Path = Path("./storage"),
    send_notifications: bool = True,
    record_task_run: bool = True,
    run_id: str | None = None,
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
        run_id=run_id,
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
    outbox_items = _load_retryable_outbox(storage_root=storage_root, trade_date=day)
    if outbox_items:
        return _retry_outbox_items(
            storage_root=storage_root,
            trade_date=day,
            observed_at=now,
            outbox_items=outbox_items,
            notification_agent=notification_agent,
        )
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


def _load_retryable_outbox(*, storage_root: Path, trade_date: str) -> list[tuple[Path, dict[str, Any]]]:
    outbox_root = storage_root / "orchestration" / "outbox"
    items: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(outbox_root.glob("*.json")):
        payload = _read_json(path)
        if payload.get("trade_date") != trade_date or payload.get("status") != "pending_retry":
            continue
        if not isinstance(payload.get("request"), dict):
            continue
        items.append((path, payload))
    return items


def _retry_outbox_items(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
    outbox_items: list[tuple[Path, dict[str, Any]]],
    notification_agent: Any | None,
) -> dict[str, Any]:
    agent = notification_agent or FeishuNotificationAgent()
    processed: list[dict[str, Any]] = []
    remaining_count = 0
    for path, item in outbox_items:
        if not _retry_item_due(item, observed_at):
            remaining_count += 1
            continue
        request_payload = item["request"]
        request = _notification_request_from_dict(request_payload)
        try:
            result = agent.send(request)
            result_payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        except Exception as exc:  # pragma: no cover - external sender boundary
            result_payload = {"ok": False, "status": "failed", "kind": request.kind, "error": str(exc)}
        attempt_count = int(item.get("attempt_count") or 0) + 1
        result_payload.update(
            {
                "notification_id": item.get("notification_id"),
                "dedupe_key": item.get("dedupe_key"),
                "retried_at": observed_at.isoformat(),
                "attempt_count": attempt_count,
            }
        )
        processed.append(result_payload)
        ok = bool(result_payload.get("ok")) or result_payload.get("status") in {"sent", "dry_run", "disabled"}
        if ok:
            status = str(result_payload.get("status") or "sent")
            next_retry_at = None
            last_error = None
        else:
            status = "pending_retry"
            remaining_count += 1
            backoff_seconds = min(3600, 60 * (2 ** max(attempt_count - 1, 0)))
            next_retry_at = (observed_at + timedelta(seconds=backoff_seconds)).isoformat()
            last_error = result_payload.get("error")
        attempts = item.get("attempts") if isinstance(item.get("attempts"), list) else []
        _write_json_atomic(
            path,
            {
                **item,
                "status": status,
                "attempt_count": attempt_count,
                "next_retry_at": next_retry_at,
                "last_error": last_error,
                "attempts": [
                    *attempts,
                    {
                        "attempted_at": observed_at.isoformat(),
                        "attempt_count": attempt_count,
                        "status": result_payload.get("status"),
                        "ok": ok,
                        "error": result_payload.get("error"),
                    },
                ],
                "updated_at": observed_at.isoformat(),
            },
        )

    base = storage_root / "orchestration" / trade_date
    base.mkdir(parents=True, exist_ok=True)
    results_path = base / "notification_retry_results.json"
    previous_results = _read_json(results_path)
    existing_results = previous_results.get("results") if isinstance(previous_results.get("results"), list) else []
    _write_json(results_path, {"trade_date": trade_date, "results": [*existing_results, *processed]})
    _append_delivery_log(base=base, trade_date=trade_date, observed_at=observed_at.isoformat(), results=processed)
    return {
        "trade_date": trade_date,
        "observed_at": observed_at.isoformat(),
        "processed_count": len(processed),
        "remaining_count": remaining_count,
        "results_path": _rel(results_path, storage_root),
        "retry_queue_path": "orchestration/outbox",
    }


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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_json(temporary, payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
