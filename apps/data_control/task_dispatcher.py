from __future__ import annotations

from typing import Any


COLLECTION_TASKS_BY_SOURCE: dict[str, tuple[str, ...]] = {
    "jin10_mcp_market": ("jin10_quotes_refresh", "jin10_kline_refresh"),
    "jin10_mcp_flash": ("jin10_flash_refresh",),
    "jin10_xnews_public": ("jin10_web_article_analysis_refresh",),
}


def build_dispatch_plan(
    *,
    collection_plan: dict[str, Any],
    processing_plan: dict[str, Any],
) -> dict[str, Any]:
    trade_date = str(collection_plan["trade_date"])
    hour = str(collection_plan["hour"])
    observed_at = str(collection_plan["observed_at"])
    requests: list[dict[str, Any]] = []
    for item in collection_plan.get("actions", []):
        if not isinstance(item, dict) or not item.get("source_key"):
            continue
        requests.extend(_collection_requests(item=item, trade_date=trade_date, hour=hour))
    for step_name in processing_plan.get("ready_steps", []):
        requests.append(
            {
                "request_id": _request_id(trade_date, hour, "processing", str(step_name)),
                "owner": "worker",
                "dispatch_mode": "worker_task",
                "status": "planned",
                "task_key": str(step_name),
                "source_key": "processing_pipeline",
                "action": "process",
                "reason_code": "processing_input_ready",
                "input_refs": [],
            }
        )
    counts = {
        status: sum(1 for request in requests if request["status"] == status)
        for status in ("ready", "planned", "waiting", "skipped", "manual_required", "unsupported")
    }
    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "hour": hour,
        "status": _dispatch_status(collection_plan=collection_plan, processing_plan=processing_plan, counts=counts),
        "execution_owner": "automation_orchestrator",
        "auto_execute": False,
        "requests": requests,
        "summary": {**counts, "request_count": len(requests)},
        "blocked_steps": _compact_blocked_steps(processing_plan.get("blocked_steps") or []),
    }


def _collection_requests(*, item: dict[str, Any], trade_date: str, hour: str) -> list[dict[str, Any]]:
    source_key = str(item["source_key"])
    action = str(item.get("action") or "collect")
    task_keys = COLLECTION_TASKS_BY_SOURCE.get(source_key, ())
    if action == "no_action":
        return [_collection_request(item=item, trade_date=trade_date, hour=hour, task_key=source_key, status="skipped")]
    if action == "wait":
        return [_collection_request(item=item, trade_date=trade_date, hour=hour, task_key=source_key, status="waiting")]
    if action == "manual_review":
        return [
            _collection_request(item=item, trade_date=trade_date, hour=hour, task_key=source_key, status="manual_required")
        ]
    if not task_keys:
        return [_collection_request(item=item, trade_date=trade_date, hour=hour, task_key=source_key, status="unsupported")]
    return [
        _collection_request(item=item, trade_date=trade_date, hour=hour, task_key=task_key, status="ready")
        for task_key in task_keys
    ]


def _collection_request(
    *,
    item: dict[str, Any],
    trade_date: str,
    hour: str,
    task_key: str,
    status: str,
) -> dict[str, Any]:
    source_key = str(item["source_key"])
    return {
        "request_id": _request_id(trade_date, hour, source_key, task_key),
        "owner": "automation_orchestrator",
        "dispatch_mode": "scheduled_job",
        "status": status,
        "task_key": task_key,
        "source_key": source_key,
        "action": item.get("action"),
        "reason_code": item.get("reason_code"),
        "input_refs": [item["latest_artifact_ref"]] if item.get("latest_artifact_ref") else [],
        "required_for": item.get("required_for") or [],
    }


def _request_id(trade_date: str, hour: str, source_key: str, task_key: str) -> str:
    return f"data-control:{trade_date}:{hour}:{source_key}:{task_key}"


def _dispatch_status(
    *,
    collection_plan: dict[str, Any],
    processing_plan: dict[str, Any],
    counts: dict[str, int],
) -> str:
    if processing_plan.get("status") == "blocked" or collection_plan.get("status") == "blocked":
        return "blocked"
    if counts["manual_required"] or counts["unsupported"]:
        return "partial"
    if counts["ready"] or counts["planned"]:
        return "ready"
    if counts["waiting"]:
        return "waiting"
    return "idle"


def _compact_blocked_steps(blocked_steps: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in blocked_steps:
        if not isinstance(item, dict):
            continue
        issue_refs: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for issue in item.get("blocking_issues") or []:
            if not isinstance(issue, dict):
                continue
            key = (
                str(issue.get("source_key") or ""),
                str(issue.get("check_type") or ""),
                str(issue.get("status") or ""),
                str(issue.get("reason_code") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            issue_refs.append(
                {
                    "source_key": key[0],
                    "check_type": key[1] or None,
                    "status": key[2] or None,
                    "reason_code": key[3] or None,
                }
            )
        compact.append(
            {
                "step": item.get("step"),
                "capability": item.get("capability"),
                "reason_code": item.get("reason_code"),
                "issue_refs": issue_refs,
            }
        )
    return compact
