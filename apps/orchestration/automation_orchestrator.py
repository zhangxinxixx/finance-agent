from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apps.notifications.notification_agent import FeishuNotificationAgent
from apps.notifications.schemas import NotificationRequest
from apps.orchestration.agent_registry import load_agent_registry
from apps.orchestration.notification_policy import build_notification_plan
from apps.orchestration.schemas import OrchestrationArtifacts
from apps.orchestration.trigger_router import resolve_trigger
from apps.runtime.task_recorder import record_task


class AutomationOrchestrator:
    def __init__(self, *, storage_root: Path | str = "storage", notification_agent: Any | None = None):
        self.storage_root = Path(storage_root)
        self.notification_agent = notification_agent

    def run(
        self,
        *,
        trade_date: str | None = None,
        observed_at: datetime | None = None,
        trigger: str = "hourly",
        hour: str | None = None,
        run_id: str | None = None,
        record_task_run: bool = True,
        send_notifications: bool = False,
    ) -> dict[str, Any]:
        now = _ensure_utc(observed_at or datetime.now(timezone.utc))
        day = trade_date or now.date().isoformat()
        run_hour = hour or now.strftime("%H")
        resolved_run_id = _resolve_run_id(run_id)
        registry = load_agent_registry()
        inputs = _resolve_inputs(storage_root=self.storage_root, trade_date=day, hour=run_hour)
        steps = resolve_trigger(trigger=trigger, registry=registry)
        orchestration_plan = {
            "trade_date": day,
            "run_id": resolved_run_id,
            "observed_at": now.isoformat(),
            "trigger": {"type": trigger, "hour": run_hour},
            "agent_registry": registry,
            "inputs": inputs,
            "steps": steps,
        }
        notification_plan = build_notification_plan(
            storage_root=self.storage_root,
            trade_date=day,
            hour=run_hour,
            trigger=trigger,
            inputs=inputs,
            observed_at=now.isoformat(),
        )
        notification_plan = self._persist_notification_outbox(
            notification_plan=notification_plan,
            trade_date=day,
            run_id=resolved_run_id,
            observed_at=now.isoformat(),
            send_notifications=send_notifications,
        )
        notification_results = (
            self._dispatch_notifications(notification_plan=notification_plan, trade_date=day, observed_at=now.isoformat()) if send_notifications else []
        )
        self._finalize_notification_outbox(
            notification_plan=notification_plan,
            notification_results=notification_results,
            observed_at=now.isoformat(),
        )
        retry_queue = _build_retry_queue(notification_results, notification_plan=notification_plan)
        pre_analysis_gate = (
            _build_pre_analysis_gate(storage_root=self.storage_root, trade_date=day, observed_at=now.isoformat(), inputs=inputs)
            if trigger == "pre_analysis"
            else None
        )
        status = _summary_status(notification_plan)
        workflow_runs = _build_workflow_runs(
            trade_date=day,
            run_id=resolved_run_id,
            observed_at=now.isoformat(),
            trigger=trigger,
            hour=run_hour,
            status=status,
            steps=steps,
            inputs=inputs,
            notification_plan=notification_plan,
            notification_results=notification_results,
            pre_analysis_gate=pre_analysis_gate,
            retry_queue=retry_queue,
        )
        automation_summary = {
            "trade_date": day,
            "run_id": resolved_run_id,
            "observed_at": now.isoformat(),
            "trigger": trigger,
            "hour": run_hour,
            "status": status,
            "send_notifications": send_notifications,
            "notification_request_count": notification_plan["request_count"],
            "notification_results": notification_results,
            "retry_queue": retry_queue,
            "inputs": inputs,
            "workflow_run_count": len(workflow_runs["workflow_runs"]),
        }
        if pre_analysis_gate is not None:
            automation_summary["pre_analysis_gate"] = pre_analysis_gate
        artifacts = self._write_artifacts(
            day=day,
            run_id=resolved_run_id,
            trigger=trigger,
            observed_at=now.isoformat(),
            orchestration_plan=orchestration_plan,
            notification_plan=notification_plan,
            automation_summary=automation_summary,
            workflow_runs=workflow_runs,
            pre_analysis_gate=pre_analysis_gate,
            retry_queue=retry_queue,
        )
        summary = {
            "trade_date": day,
            "run_id": resolved_run_id,
            "observed_at": now.isoformat(),
            "trigger": trigger,
            "status": status,
            "artifacts": artifacts.to_dict(),
            "notification_results": notification_results,
        }
        if record_task_run:
            summary["task_run_id"] = _record_orchestrator_task(day=day, artifacts=artifacts, trigger=trigger, notification_count=notification_plan["request_count"])
        return summary

    def _persist_notification_outbox(
        self,
        *,
        notification_plan: dict[str, Any],
        trade_date: str,
        run_id: str,
        observed_at: str,
        send_notifications: bool,
    ) -> dict[str, Any]:
        requests: list[dict[str, Any]] = []
        outbox_root = self.storage_root / "orchestration" / "outbox"
        outbox_root.mkdir(parents=True, exist_ok=True)
        for index, payload in enumerate(notification_plan.get("requests", [])):
            if not isinstance(payload, dict):
                continue
            notification_id = _notification_id(run_id=run_id, index=index, dedupe_key=payload.get("dedupe_key"))
            outbox_path = outbox_root / f"{notification_id}.json"
            request_payload = _notification_request_payload(payload)
            if not send_notifications:
                status = "planned"
            elif payload.get("eligible_to_send") is False:
                status = "skipped"
            else:
                status = "pending_delivery"
            _write_json_atomic(
                outbox_path,
                {
                    "notification_id": notification_id,
                    "source_run_id": run_id,
                    "trade_date": trade_date,
                    "status": status,
                    "dedupe_key": payload.get("dedupe_key"),
                    "request": request_payload,
                    "attempt_count": 0,
                    "next_retry_at": None,
                    "last_error": None,
                    "attempts": [],
                    "created_at": observed_at,
                    "updated_at": observed_at,
                },
            )
            requests.append(
                {
                    **payload,
                    "notification_id": notification_id,
                    "outbox_ref": _rel(outbox_path, self.storage_root),
                }
            )
        return {**notification_plan, "requests": requests, "request_count": len(requests)}

    def _finalize_notification_outbox(
        self,
        *,
        notification_plan: dict[str, Any],
        notification_results: list[dict[str, Any]],
        observed_at: str,
    ) -> None:
        results_by_id = {
            str(result.get("notification_id")): result
            for result in notification_results
            if isinstance(result, dict) and result.get("notification_id")
        }
        for payload in notification_plan.get("requests", []):
            if not isinstance(payload, dict) or not payload.get("notification_id") or not payload.get("outbox_ref"):
                continue
            result = results_by_id.get(str(payload["notification_id"]))
            if result is None:
                continue
            outbox_path = self.storage_root / str(payload["outbox_ref"])
            outbox_item = _read_json(outbox_path)
            if not outbox_item:
                continue
            result_status = str(result.get("status") or "failed")
            attempt_count = int(result.get("attempts") or 0)
            attempt = {
                "attempted_at": observed_at,
                "attempt_count": attempt_count,
                "status": result_status,
                "ok": bool(result.get("ok")),
                "error": result.get("error"),
            }
            _write_json_atomic(
                outbox_path,
                {
                    **outbox_item,
                    "status": "pending_retry" if result_status == "failed" else result_status,
                    "attempt_count": attempt_count,
                    "next_retry_at": result.get("next_retry_at"),
                    "last_error": result.get("error"),
                    "attempts": [*(outbox_item.get("attempts") or []), attempt],
                    "updated_at": observed_at,
                },
            )

    def _dispatch_notifications(self, *, notification_plan: dict[str, Any], trade_date: str, observed_at: str) -> list[dict[str, Any]]:
        agent = self.notification_agent or FeishuNotificationAgent()
        results = []
        for payload in notification_plan.get("requests", []):
            if not isinstance(payload, dict):
                continue
            if payload.get("eligible_to_send") is False:
                results.append(
                    {
                        "ok": True,
                        "status": "skipped",
                        "kind": payload.get("kind"),
                        "dedupe_key": payload.get("dedupe_key"),
                        "skipped_reason": payload.get("skipped_reason"),
                        "attempts": 0,
                        "notification_id": payload.get("notification_id"),
                    }
                )
                continue
            request = _notification_request_from_dict(payload)
            results.append(_send_with_retry(agent=agent, request=request, payload=payload, max_attempts=3, observed_at=observed_at))
        _append_delivery_log(storage_root=self.storage_root, trade_date=trade_date, observed_at=observed_at, results=results)
        return results

    def _write_artifacts(
        self,
        *,
        day: str,
        run_id: str,
        trigger: str,
        observed_at: str,
        orchestration_plan: dict[str, Any],
        notification_plan: dict[str, Any],
        automation_summary: dict[str, Any],
        workflow_runs: dict[str, Any],
        pre_analysis_gate: dict[str, Any] | None = None,
        retry_queue: list[dict[str, Any]] | None = None,
    ) -> OrchestrationArtifacts:
        date_root = self.storage_root / "orchestration" / day
        base = date_root / run_id
        base.mkdir(parents=True, exist_ok=True)
        orchestration_path = base / "orchestration_plan.json"
        notification_path = base / "notification_plan.json"
        summary_path = base / "automation_summary.json"
        workflow_runs_path = base / "workflow_runs.json"
        retry_queue_path = base / "retry_queue.json"
        pre_analysis_gate_path = base / "pre_analysis_gate.json"
        _write_json(orchestration_path, orchestration_plan)
        _write_json(notification_path, notification_plan)
        _write_json(summary_path, automation_summary)
        _write_json(workflow_runs_path, workflow_runs)
        _write_json(retry_queue_path, {"trade_date": day, "count": len(retry_queue or []), "items": retry_queue or []})
        if pre_analysis_gate is not None:
            _write_json(pre_analysis_gate_path, pre_analysis_gate)
        latest_path = date_root / "latest.json"
        artifacts = OrchestrationArtifacts(
            run_id=run_id,
            orchestration_plan_path=_rel(orchestration_path, self.storage_root),
            notification_plan_path=_rel(notification_path, self.storage_root),
            automation_summary_path=_rel(summary_path, self.storage_root),
            workflow_runs_path=_rel(workflow_runs_path, self.storage_root),
            retry_queue_path=_rel(retry_queue_path, self.storage_root),
            latest_pointer_path=_rel(latest_path, self.storage_root),
            pre_analysis_gate_path=_rel(pre_analysis_gate_path, self.storage_root) if pre_analysis_gate is not None else None,
        )
        _write_json_atomic(
            latest_path,
            {
                "trade_date": day,
                "run_id": run_id,
                "trigger": trigger,
                "observed_at": observed_at,
                "artifacts": artifacts.to_dict(),
            },
        )
        return artifacts


def run_automation_orchestrator(
    *,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    trigger: str = "hourly",
    hour: str | None = None,
    run_id: str | None = None,
    record_task_run: bool = True,
    send_notifications: bool = False,
    notification_agent: Any | None = None,
) -> dict[str, Any]:
    return AutomationOrchestrator(storage_root=storage_root, notification_agent=notification_agent).run(
        trade_date=trade_date,
        observed_at=observed_at,
        trigger=trigger,
        hour=hour,
        run_id=run_id,
        record_task_run=record_task_run,
        send_notifications=send_notifications,
    )


def _resolve_inputs(*, storage_root: Path, trade_date: str, hour: str) -> dict[str, str | None]:
    return {
        "collection_plan": _existing(storage_root, f"data_control/{trade_date}/collection_plan_{hour}.json"),
        "processing_plan": _existing(storage_root, f"data_control/{trade_date}/processing_plan_{hour}.json"),
        "hourly_report": _existing(storage_root, f"data_control/{trade_date}/hourly_collection_processing_report_{hour}.json"),
        "downstream_readiness": _existing(storage_root, f"monitoring/{trade_date}/downstream_readiness.json"),
        "event_sla_root": f"event_sla/{trade_date}" if (storage_root / "event_sla" / trade_date).exists() else None,
    }


def _build_pre_analysis_gate(*, storage_root: Path, trade_date: str, observed_at: str, inputs: dict[str, str | None]) -> dict[str, Any]:
    source_ref = inputs.get("downstream_readiness")
    readiness = _read_json(storage_root / source_ref) if source_ref else {}
    if not readiness:
        return {
            "trade_date": trade_date,
            "observed_at": observed_at,
            "decision": "block",
            "status": "unavailable",
            "can_run_full_analysis": False,
            "can_run_research_distillation": False,
            "capabilities": {},
            "allowed_outputs": [],
            "blocked_outputs": ["full analysis", "knowledge distillation"],
            "issues": [{"reason_code": "downstream_readiness_missing"}],
            "source_ref": source_ref,
        }

    capabilities = readiness.get("capabilities") if isinstance(readiness.get("capabilities"), dict) else None
    if capabilities is not None:
        full_analysis_state = str(capabilities.get("full_daily_analysis") or "blocked")
        distillation_state = str(capabilities.get("knowledge_distillation") or "blocked")
        can_run_full_analysis = full_analysis_state != "blocked"
        can_run_research_distillation = distillation_state != "blocked"
    else:
        full_analysis_state = "allowed" if readiness.get("can_run_full_analysis") else "blocked"
        distillation_state = "allowed" if readiness.get("can_run_research_distillation") else "blocked"
        can_run_full_analysis = bool(readiness.get("can_run_full_analysis"))
        can_run_research_distillation = bool(readiness.get("can_run_research_distillation"))
    status = str(readiness.get("readiness") or "unknown")
    if full_analysis_state == "blocked":
        decision = "block"
    elif full_analysis_state == "degraded" or distillation_state != "allowed":
        decision = "limited"
    else:
        decision = "allow"
    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "decision": decision,
        "status": status,
        "can_run_full_analysis": can_run_full_analysis,
        "can_run_research_distillation": can_run_research_distillation,
        "capabilities": capabilities or {},
        "allowed_outputs": readiness.get("allowed_outputs") if isinstance(readiness.get("allowed_outputs"), list) else [],
        "blocked_outputs": readiness.get("blocked_outputs") if isinstance(readiness.get("blocked_outputs"), list) else [],
        "issues": readiness.get("blocking_issues") if isinstance(readiness.get("blocking_issues"), list) else [],
        "source_ref": source_ref,
    }


def _record_orchestrator_task(*, day: str, artifacts: OrchestrationArtifacts, trigger: str, notification_count: int) -> str | None:
    with record_task(task_type="automation_orchestrator", task_name="Automation Orchestrator", trade_date=day) as recorder:
        for step_name in (
            "load_agent_registry",
            "resolve_trigger",
            "build_orchestration_plan",
            "build_notification_plan",
            "dispatch_feishu_notification",
            "write_automation_summary",
        ):
            recorder.step(
                step_name,
                status="success",
                stage="orchestration",
                task_kind=trigger,
                output_refs=_output_refs_for_step(step_name, artifacts, notification_count),
            )
        return recorder.run_id()


def _output_refs_for_step(step_name: str, artifacts: OrchestrationArtifacts, notification_count: int) -> list[dict[str, Any]]:
    mapping = {
        "build_orchestration_plan": {"artifact_type": "orchestration_plan", "path": artifacts.orchestration_plan_path},
        "build_notification_plan": {"artifact_type": "notification_plan", "path": artifacts.notification_plan_path, "notification_count": notification_count},
        "write_automation_summary": {"artifact_type": "automation_summary", "path": artifacts.automation_summary_path},
    }
    item = mapping.get(step_name)
    return [item] if item else []


def _build_workflow_runs(
    *,
    trade_date: str,
    run_id: str,
    observed_at: str,
    trigger: str,
    hour: str,
    status: str,
    steps: list[dict[str, Any]],
    inputs: dict[str, str | None],
    notification_plan: dict[str, Any],
    notification_results: list[dict[str, Any]],
    pre_analysis_gate: dict[str, Any] | None = None,
    retry_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manual_review_required = status == "blocked" or any(
        isinstance(item, dict) and item.get("severity") == "critical" for item in notification_plan.get("requests", [])
    )
    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "workflow_runs": [
            {
                "workflow_id": run_id,
                "run_id": run_id,
                "trigger": trigger,
                "hour": hour,
                "status": status,
                "steps": steps,
                "inputs": inputs,
                "notification_request_count": notification_plan.get("request_count", 0),
                "notification_result_count": len(notification_results),
                "pre_analysis_gate": pre_analysis_gate,
                "output_refs": _workflow_output_refs(
                    trade_date=trade_date,
                    run_id=run_id,
                    trigger=trigger,
                    pre_analysis_gate=pre_analysis_gate,
                ),
                "retry_queue": retry_queue or [],
                "manual_review_required": manual_review_required,
                "manual_review": _manual_review_items(notification_plan) if manual_review_required else [],
                "retry_policy": {
                    "max_attempts": 3,
                    "retryable_statuses": ["failed"],
                    "backoff": "exponential",
                    "base_backoff_seconds": 60,
                    "max_backoff_seconds": 3600,
                },
            }
        ],
    }


def _workflow_output_refs(
    *,
    trade_date: str,
    run_id: str,
    trigger: str,
    pre_analysis_gate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if trigger != "pre_analysis" or pre_analysis_gate is None:
        return []
    return [
        {
            "artifact_type": "pre_analysis_gate",
            "path": f"orchestration/{trade_date}/{run_id}/pre_analysis_gate.json",
        }
    ]


def _manual_review_items(notification_plan: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for request in notification_plan.get("requests", []):
        if not isinstance(request, dict):
            continue
        if request.get("severity") == "critical":
            items.append(
                {
                    "kind": request.get("kind"),
                    "dedupe_key": request.get("dedupe_key"),
                    "reason": request.get("summary"),
                    "facts": request.get("facts") if isinstance(request.get("facts"), dict) else {},
                }
            )
    return items


def _send_with_retry(*, agent: Any, request: NotificationRequest, payload: dict[str, Any], max_attempts: int, observed_at: str) -> dict[str, Any]:
    last_result: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            result = agent.send(request)
            last_result = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        except Exception as exc:  # pragma: no cover - defensive boundary for external sender
            last_result = {"ok": False, "status": "failed", "kind": request.kind, "error": str(exc)}
        last_result.update(
            {
                "attempts": attempt,
                "max_attempts": max_attempts,
                "dedupe_key": payload.get("dedupe_key"),
                "notification_id": payload.get("notification_id"),
                "cooldown_minutes": payload.get("cooldown_minutes"),
            }
        )
        if last_result.get("ok") or last_result.get("status") in {"sent", "dry_run", "disabled", "skipped"}:
            return last_result
    backoff_seconds = _retry_backoff_seconds(int(last_result.get("attempts") or max_attempts))
    next_retry_at = _next_retry_at(observed_at=observed_at, backoff_seconds=backoff_seconds)
    last_result.update({"backoff_seconds": backoff_seconds, "next_retry_at": next_retry_at})
    return last_result


def _build_retry_queue(
    notification_results: list[dict[str, Any]],
    *,
    notification_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    requests_by_id = {
        str(payload.get("notification_id")): payload
        for payload in notification_plan.get("requests", [])
        if isinstance(payload, dict) and payload.get("notification_id")
    }
    queue = []
    for result in notification_results:
        if result.get("status") != "failed" or not result.get("next_retry_at"):
            continue
        notification_id = str(result.get("notification_id") or "")
        payload = requests_by_id.get(notification_id, {})
        attempt_count = int(result.get("attempts") or 0)
        queue.append(
            {
                "notification_id": notification_id,
                "kind": result.get("kind"),
                "dedupe_key": result.get("dedupe_key"),
                "request": _notification_request_payload(payload),
                "attempt_count": attempt_count,
                "attempts": attempt_count,
                "max_attempts": int(result.get("max_attempts") or 3),
                "next_retry_at": result.get("next_retry_at"),
                "backoff_seconds": int(result.get("backoff_seconds") or 0),
                "last_error": result.get("error"),
                "error": result.get("error"),
            }
        )
    return queue


def _retry_backoff_seconds(attempts: int) -> int:
    return min(3600, 60 * (2 ** max(attempts - 1, 0)))


def _next_retry_at(*, observed_at: str, backoff_seconds: int) -> str | None:
    observed = _parse_datetime(observed_at)
    if observed is None:
        return None
    return (observed + timedelta(seconds=backoff_seconds)).isoformat()


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


def _append_delivery_log(*, storage_root: Path, trade_date: str, observed_at: str, results: list[dict[str, Any]]) -> None:
    deliveries = []
    for result in results:
        if result.get("status") == "skipped":
            continue
        deliveries.append(
            {
                "dedupe_key": result.get("dedupe_key"),
                "kind": result.get("kind"),
                "status": result.get("status"),
                "ok": result.get("ok"),
                "attempts": result.get("attempts"),
                "sent_at": observed_at,
                "cooldown_minutes": result.get("cooldown_minutes"),
                "error": result.get("error"),
            }
        )
    if not deliveries:
        return
    path = storage_root / "orchestration" / trade_date / "notification_delivery_log.json"
    payload = _read_json(path)
    existing = payload.get("deliveries") if isinstance(payload.get("deliveries"), list) else []
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"trade_date": trade_date, "deliveries": [*existing, *deliveries]})


def _notification_request_from_dict(payload: dict[str, Any]) -> NotificationRequest:
    return NotificationRequest(
        kind=payload.get("kind", "incident"),
        title=str(payload.get("title") or "Automation notification"),
        summary=str(payload.get("summary") or ""),
        severity=payload.get("severity", "info"),
        facts=payload.get("facts") if isinstance(payload.get("facts"), dict) else {},
        sections=payload.get("sections") if isinstance(payload.get("sections"), list) else [],
        source_refs=payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else [],
        dry_run=bool(payload.get("dry_run")),
        trade_date=payload.get("trade_date"),
    )


def _notification_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = _notification_request_from_dict(payload)
    return {
        "kind": request.kind,
        "title": request.title,
        "summary": request.summary,
        "severity": request.severity,
        "facts": request.facts,
        "sections": request.sections,
        "source_refs": request.source_refs,
        "dry_run": request.dry_run,
        "trade_date": request.trade_date,
    }


def _notification_id(*, run_id: str, index: int, dedupe_key: Any) -> str:
    identity = f"{run_id}:{index}:{str(dedupe_key or '')}"
    return uuid.uuid5(uuid.NAMESPACE_URL, identity).hex


def _summary_status(notification_plan: dict[str, Any]) -> str:
    severities = {str(item.get("severity")) for item in notification_plan.get("requests", []) if isinstance(item, dict)}
    if "critical" in severities:
        return "blocked"
    if "warning" in severities:
        return "partial"
    return "normal"


def _existing(storage_root: Path, relative_path: str) -> str | None:
    return relative_path if (storage_root / relative_path).is_file() else None


def _resolve_run_id(value: str | None) -> str:
    run_id = str(value or uuid.uuid4())
    if len(run_id) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id) or ".." in run_id:
        raise ValueError(f"Invalid orchestration run_id: {run_id}")
    return run_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_json(temporary, payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
