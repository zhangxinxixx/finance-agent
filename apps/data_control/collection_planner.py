from __future__ import annotations

from typing import Any

from apps.data_control.schemas import PlanAction

ACTION_BY_STATE: dict[str, PlanAction] = {
    "available": "no_action",
    "waiting": "wait",
    "missing": "collect",
    "stale": "refresh",
    "blocked": "manual_review",
}


def build_collection_plan(*, availability_snapshot: dict[str, Any]) -> dict[str, Any]:
    actions = []
    for item in availability_snapshot.get("items", []):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "missing")
        action = ACTION_BY_STATE.get(state, "collect")
        actions.append(
            {
                "source_key": item.get("source_key"),
                "source_type": item.get("source_type"),
                "state": state,
                "action": action,
                "reason_code": item.get("reason_code"),
                "message": item.get("message"),
                "expected_at": item.get("expected_at"),
                "latest_artifact_ref": item.get("latest_artifact_ref"),
                "required_for": item.get("required_for") or [],
                "missing_policy": item.get("missing_policy"),
            }
        )
    return {
        "trade_date": availability_snapshot["trade_date"],
        "observed_at": availability_snapshot["observed_at"],
        "hour": availability_snapshot["hour"],
        "status": _plan_status(actions),
        "actions": actions,
        "summary": {
            "collect_count": sum(1 for item in actions if item["action"] == "collect"),
            "refresh_count": sum(1 for item in actions if item["action"] == "refresh"),
            "waiting_count": sum(1 for item in actions if item["action"] == "wait"),
            "manual_review_count": sum(1 for item in actions if item["action"] == "manual_review"),
        },
    }


def _plan_status(actions: list[dict[str, Any]]) -> str:
    states = {str(item.get("state")) for item in actions}
    if "blocked" in states:
        return "blocked"
    if "missing" in states or "stale" in states:
        return "degraded"
    if "waiting" in states:
        return "waiting"
    return "normal"
