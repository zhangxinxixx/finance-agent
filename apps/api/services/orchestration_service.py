from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STORAGE_ROOT = _PROJECT_ROOT / "storage"


def get_orchestration_latest(*, storage_root: Path | str = _STORAGE_ROOT, date: str | None = None) -> dict[str, Any]:
    root = Path(storage_root)
    trade_date = date or _latest_date(root)
    latest = _read_json(_artifact_path(root, trade_date, "latest.json"))
    run_root = _run_artifact_root(root, trade_date)
    summary = _read_json(run_root / "automation_summary.json")
    workflow_runs = _read_json(run_root / "workflow_runs.json")
    notification_plan = get_orchestration_notification_plan(storage_root=root, date=trade_date)
    delivery_log = _read_json(_artifact_path(root, trade_date, "notification_delivery_log.json"))
    pre_analysis_gate = _read_json(run_root / "pre_analysis_gate.json")
    retry_queue = _read_json(run_root / "retry_queue.json")
    retry_results = _read_json(_artifact_path(root, trade_date, "notification_retry_results.json"))
    manual_review = _manual_review_items(workflow_runs)
    return {
        "trade_date": trade_date,
        "run_id": latest.get("run_id") or summary.get("run_id"),
        "artifacts": _artifact_refs(root, trade_date, run_root=run_root),
        "summary": summary,
        "workflow_runs": workflow_runs.get("workflow_runs", []),
        "pre_analysis_gate": pre_analysis_gate,
        "retry_queue": _default_retry_queue(retry_queue, trade_date),
        "notification_retry_results": _default_retry_results(retry_results, trade_date),
        "notification_plan": notification_plan,
        "delivery_log": _default_delivery_log(delivery_log, trade_date),
        "manual_review_count": len(manual_review),
        "manual_review": manual_review,
    }


def get_orchestration_notification_plan(*, storage_root: Path | str = _STORAGE_ROOT, date: str | None = None) -> dict[str, Any]:
    root = Path(storage_root)
    trade_date = date or _latest_date(root)
    payload = _read_json(_run_artifact_root(root, trade_date) / "notification_plan.json")
    if payload:
        return payload
    return {"trade_date": trade_date, "requests": [], "request_count": 0}


def get_orchestration_manual_review(*, storage_root: Path | str = _STORAGE_ROOT, date: str | None = None) -> dict[str, Any]:
    root = Path(storage_root)
    trade_date = date or _latest_date(root)
    workflow_runs = _read_json(_run_artifact_root(root, trade_date) / "workflow_runs.json")
    actions = _manual_review_actions(root, trade_date)
    items = _merge_manual_review_actions(_manual_review_items(workflow_runs), actions)
    return {
        "trade_date": trade_date,
        "count": len(items),
        "items": items,
    }


def create_manual_review_action(
    *,
    storage_root: Path | str = _STORAGE_ROOT,
    date: str,
    dedupe_key: str,
    action: str,
    actor: str,
    note: str | None = None,
) -> dict[str, Any]:
    root = Path(storage_root)
    path = _artifact_path(root, date, "manual_review_actions.json")
    payload = _read_json(path)
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    item = {
        "dedupe_key": dedupe_key,
        "action": action,
        "actor": actor,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, {"trade_date": date, "actions": [*actions, item]})
    return {"status": "recorded", "trade_date": date, "action": item}


def _manual_review_items(workflow_runs_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for run in workflow_runs_payload.get("workflow_runs", []):
        if not isinstance(run, dict):
            continue
        workflow_id = str(run.get("workflow_id") or "")
        trigger = run.get("trigger")
        status = run.get("status")
        for item in run.get("manual_review", []):
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "workflow_id": workflow_id,
                    "trigger": trigger,
                    "status": status,
                    "kind": item.get("kind"),
                    "dedupe_key": item.get("dedupe_key"),
                    "reason": item.get("reason"),
                    "facts": item.get("facts") if isinstance(item.get("facts"), dict) else {},
                    "action_status": "open",
                    "action_note": None,
                    "action_actor": None,
                    "action_recorded_at": None,
                }
            )
    return items


def _manual_review_actions(storage_root: Path, trade_date: str) -> dict[str, dict[str, Any]]:
    payload = _read_json(_artifact_path(storage_root, trade_date, "manual_review_actions.json"))
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    latest: dict[str, dict[str, Any]] = {}
    for item in actions:
        if isinstance(item, dict) and item.get("dedupe_key"):
            latest[str(item["dedupe_key"])] = item
    return latest


def _merge_manual_review_actions(items: list[dict[str, Any]], actions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    for item in items:
        action = actions.get(str(item.get("dedupe_key")))
        if action:
            item = {
                **item,
                "action_status": action.get("action") or "open",
                "action_note": action.get("note"),
                "action_actor": action.get("actor"),
                "action_recorded_at": action.get("recorded_at"),
            }
        merged.append(item)
    return merged


def _artifact_refs(storage_root: Path, trade_date: str, *, run_root: Path) -> dict[str, str | None]:
    refs = {}
    for key, filename in (
        ("orchestration_plan", "orchestration_plan.json"),
        ("notification_plan", "notification_plan.json"),
        ("automation_summary", "automation_summary.json"),
        ("workflow_runs", "workflow_runs.json"),
        ("pre_analysis_gate", "pre_analysis_gate.json"),
        ("retry_queue", "retry_queue.json"),
    ):
        path = run_root / filename
        refs[key] = _rel(path, storage_root) if path.is_file() else None
    for key, filename in (
        ("notification_retry_results", "notification_retry_results.json"),
        ("notification_delivery_log", "notification_delivery_log.json"),
    ):
        path = _artifact_path(storage_root, trade_date, filename)
        refs[key] = _rel(path, storage_root) if path.is_file() else None
    latest_path = _artifact_path(storage_root, trade_date, "latest.json")
    refs["latest"] = _rel(latest_path, storage_root) if latest_path.is_file() else None
    return refs


def _artifact_path(storage_root: Path, trade_date: str, filename: str) -> Path:
    return storage_root / "orchestration" / trade_date / filename


def _run_artifact_root(storage_root: Path, trade_date: str) -> Path:
    date_root = storage_root / "orchestration" / trade_date
    latest = _read_json(date_root / "latest.json")
    run_id = str(latest.get("run_id") or "")
    if run_id and Path(run_id).name == run_id and run_id not in {".", ".."}:
        run_root = date_root / run_id
        if run_root.is_dir():
            return run_root
    return date_root


def _latest_date(storage_root: Path) -> str:
    root = storage_root / "orchestration"
    if not root.exists():
        return ""
    dates = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            datetime.strptime(path.name, "%Y-%m-%d")
        except ValueError:
            continue
        dates.append(path.name)
    dates.sort()
    return dates[-1] if dates else ""


def _default_delivery_log(payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
    if payload:
        return payload
    return {"trade_date": trade_date, "deliveries": []}


def _default_retry_queue(payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
    if payload:
        return payload
    return {"trade_date": trade_date, "count": 0, "items": []}


def _default_retry_results(payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
    if payload:
        return payload
    return {"trade_date": trade_date, "results": []}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
