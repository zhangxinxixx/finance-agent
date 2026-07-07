from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.governance.artifact_io import read_json_object, update_json_atomically

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STORAGE_ROOT = _PROJECT_ROOT / "storage"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROPOSAL_ACTIONS = {"approve", "reject", "link_issue", "link_pr", "mark_implemented", "mark_rolled_back"}
_STATUS_ACTIONS = {
    "approve": "approved",
    "reject": "rejected",
    "mark_implemented": "implemented",
    "mark_rolled_back": "rolled_back",
}
_ALLOWED_TRANSITIONS = {
    "pending_review": {"approved", "rejected"},
    "approved": {"implemented", "rejected"},
    "implemented": {"rolled_back"},
    "rejected": set(),
    "rolled_back": set(),
}


def get_system_evolution_latest(*, storage_root: Path | str = _STORAGE_ROOT, date: str | None = None) -> dict[str, Any]:
    root = Path(storage_root)
    trade_date = date or _latest_date(root)
    base = _artifact_dir(root, trade_date)
    findings = _read_json(base / "findings.json")
    proposals = _read_json(base / "improvement_proposals.json")
    review = _read_json(base / "system_evolution_review.json")
    proposal_actions = _proposal_actions(root, trade_date)
    return {
        "trade_date": trade_date,
        "artifacts": _artifact_refs(root, trade_date),
        "review": review,
        "findings": _default_items(findings, "findings"),
        "proposals": _proposal_items_with_actions(proposals, proposal_actions),
        "proposal_actions": _default_proposal_actions(proposal_actions, trade_date),
    }


def create_system_evolution_proposal_action(
    *,
    storage_root: Path | str = _STORAGE_ROOT,
    date: str,
    proposal_id: str,
    action: str,
    actor: str,
    note: str | None = None,
    issue_url: str | None = None,
    pr_url: str | None = None,
    test_result: str | None = None,
    manual_confirmation: str | None = None,
    rollback_reason: str | None = None,
) -> dict[str, Any]:
    _validate_trade_date(date)
    if action not in _PROPOSAL_ACTIONS:
        raise ValueError(f"unsupported system evolution proposal action: {action}")
    if action == "link_issue" and not issue_url:
        raise ValueError("link_issue action requires issue_url")
    if action == "link_pr" and not pr_url:
        raise ValueError("link_pr action requires pr_url")
    if action == "mark_implemented" and not (test_result or manual_confirmation):
        raise ValueError("mark_implemented action requires test_result or manual_confirmation")
    if action == "mark_rolled_back" and not rollback_reason:
        raise ValueError("mark_rolled_back action requires rollback_reason")
    if not proposal_id:
        raise ValueError("proposal_id is required")
    if not actor:
        raise ValueError("actor is required")

    root = Path(storage_root)
    proposals = _read_json(_artifact_dir(root, date) / "improvement_proposals.json")
    proposal = _find_proposal(proposals, proposal_id)
    if proposal is None:
        raise ValueError(f"proposal not found: {proposal_id}")

    path = _artifact_dir(root, date) / "proposal_actions.json"
    item = {
        "proposal_id": proposal_id,
        "action": action,
        "actor": actor,
        "note": note,
        "issue_url": issue_url,
        "pr_url": pr_url,
        "test_result": test_result,
        "manual_confirmation": manual_confirmation,
        "rollback_reason": rollback_reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    def append_action(existing: dict[str, Any]) -> dict[str, Any]:
        actions = existing.get("actions") if isinstance(existing.get("actions"), list) else []
        proposal_actions = [entry for entry in actions if isinstance(entry, dict) and entry.get("proposal_id") == proposal_id]
        current = _merge_proposal_action_state(proposal, proposal_actions)
        _validate_status_transition(str(current.get("status") or "pending_review"), action)
        return {"trade_date": date, "actions": [*actions, item]}

    update_json_atomically(path, append_action)
    return {"status": "recorded", "trade_date": date, "action": item}


def _artifact_refs(storage_root: Path, trade_date: str) -> dict[str, str | None]:
    refs = {}
    for key, filename in (
        ("findings", "findings.json"),
        ("improvement_proposals", "improvement_proposals.json"),
        ("review", "system_evolution_review.json"),
        ("proposal_actions", "proposal_actions.json"),
    ):
        path = _artifact_dir(storage_root, trade_date) / filename
        refs[key] = _rel(path, storage_root) if path.is_file() else None
    return refs


def _default_items(payload: dict[str, Any], key: str) -> dict[str, Any]:
    items = payload.get(key) if isinstance(payload.get(key), list) else []
    return {"count": len(items), "items": items}


def _proposal_items_with_actions(payload: dict[str, Any], actions_payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
    actions_by_proposal = _actions_by_proposal(actions_payload)
    merged = [_merge_proposal_action_state(item, actions_by_proposal.get(str(item.get("proposal_id")), [])) for item in items]
    return {"count": len(merged), "items": merged}


def _merge_proposal_action_state(proposal: Any, actions: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(proposal) if isinstance(proposal, dict) else {}
    if not actions:
        return item

    latest_action = actions[-1]
    status = item.get("status")
    for action in actions:
        action_name = action.get("action")
        if action_name in _STATUS_ACTIONS:
            status = _STATUS_ACTIONS[str(action_name)]
            if action.get("test_result"):
                item["test_result"] = action.get("test_result")
            if action.get("manual_confirmation"):
                item["manual_confirmation"] = action.get("manual_confirmation")
            if action.get("rollback_reason"):
                item["rollback_reason"] = action.get("rollback_reason")
        elif action_name == "link_issue" and action.get("issue_url"):
            item["linked_issue"] = action.get("issue_url")
        elif action_name == "link_pr" and action.get("pr_url"):
            item["linked_pr"] = action.get("pr_url")

    item["status"] = status
    item["review_action_status"] = status
    item["review_actor"] = latest_action.get("actor")
    item["review_note"] = latest_action.get("note")
    item["review_recorded_at"] = latest_action.get("recorded_at")
    return item


def _actions_by_proposal(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    result: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        if isinstance(action, dict) and action.get("proposal_id"):
            result.setdefault(str(action["proposal_id"]), []).append(action)
    return result


def _find_proposal(payload: dict[str, Any], proposal_id: str) -> dict[str, Any] | None:
    proposals = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
    for proposal in proposals:
        if isinstance(proposal, dict) and proposal.get("proposal_id") == proposal_id:
            return proposal
    return None


def _validate_status_transition(current_status: str, action: str) -> None:
    target_status = _STATUS_ACTIONS.get(action)
    if target_status is None:
        return
    if target_status not in _ALLOWED_TRANSITIONS.get(current_status, set()):
        raise ValueError(f"invalid proposal status transition: {current_status} -> {target_status}")


def _default_proposal_actions(payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    return {"trade_date": trade_date, "count": len(actions), "actions": actions}


def _proposal_actions(storage_root: Path, trade_date: str) -> dict[str, Any]:
    return _read_json(_artifact_dir(storage_root, trade_date) / "proposal_actions.json")


def _artifact_dir(storage_root: Path, trade_date: str) -> Path:
    return storage_root / "governance" / "system_evolution" / trade_date


def _latest_date(storage_root: Path) -> str:
    root = storage_root / "governance" / "system_evolution"
    if not root.exists():
        return ""
    dates = sorted(path.name for path in root.iterdir() if path.is_dir())
    return dates[-1] if dates else ""


def _read_json(path: Path) -> dict[str, Any]:
    return read_json_object(path)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()


def _validate_trade_date(date: str) -> None:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("date must use YYYY-MM-DD")
