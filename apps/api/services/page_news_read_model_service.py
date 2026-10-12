"""ADS operations view for Jin10/Feishu, built only from news features."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.daily_analysis_trigger_service import get_daily_analysis_triggers
from apps.api.services.jin10_article_brief_service import get_jin10_article_briefs


_FEATURE_FILENAMES = {"daily_analysis_triggers.json", "jin10_article_briefs.json"}
_BLOCKING_STATUSES = {"blocked", "failed", "error", "rejected", "invalid", "unavailable"}
_NON_ACTIONABLE_STATUSES = _BLOCKING_STATUSES | {
    "unverified",
    "single_source",
    "needs_review",
    "pending",
    "unknown",
}
_ACCEPTED_STATUSES = {"accepted", "approved", "verified", "official_confirmed"}


def list_page_news_dates(*, project_root: Path | None = None) -> list[str]:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "features" / "news"
    if not base.is_dir():
        return []
    return [
        date_dir.name
        for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True)
        if any(path.name in _FEATURE_FILENAMES for path in date_dir.glob("*/*.json"))
    ]


def get_page_news_monitor_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    dates = list_page_news_dates(project_root=project_root)
    return get_page_news_monitor(date=dates[0], project_root=project_root) if dates else None


def get_page_news_monitor(*, date: str, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    date_dir = root / "storage" / "features" / "news" / date
    if not date_dir.is_dir():
        return _empty(date)

    triggers: list[dict[str, Any]] = []
    briefs: list[dict[str, Any]] = []
    as_of_values: list[str] = []
    run_ids: list[str] = []
    for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
        trigger_payload = get_daily_analysis_triggers(date=date, run_id=run_dir.name, project_root=root)
        brief_payload = get_jin10_article_briefs(date=date, run_id=run_dir.name, project_root=root)
        if trigger_payload is not None:
            triggers.extend(item for item in trigger_payload.get("triggers") or [] if isinstance(item, dict))
            if trigger_payload.get("as_of"):
                as_of_values.append(str(trigger_payload["as_of"]))
            run_ids.append(run_dir.name)
        if brief_payload is not None:
            briefs.extend(item for item in brief_payload.get("briefs") or [] if isinstance(item, dict))
            if brief_payload.get("as_of"):
                as_of_values.append(str(brief_payload["as_of"]))
            run_ids.append(run_dir.name)

    trigger_by_url: dict[str, dict[str, Any]] = {}
    brief_by_url: dict[str, dict[str, Any]] = {}
    for item in triggers:
        if item.get("source_url"):
            trigger_by_url.setdefault(str(item["source_url"]), item)
    for item in briefs:
        if item.get("source_url"):
            brief_by_url.setdefault(str(item["source_url"]), item)
    items: list[dict[str, Any]] = []
    for url in dict.fromkeys([*brief_by_url, *trigger_by_url]):
        brief = brief_by_url.get(url)
        trigger = trigger_by_url.get(url)
        decision = _decision_state(brief, trigger)
        items.append(
            {
                "message_id": (brief or {}).get("brief_id") or (trigger or {}).get("trigger_id"),
                "published_at": (brief or {}).get("created_at") or (trigger or {}).get("created_at"),
                "primary_url": url,
                "filter_status": (
                    "blocked"
                    if decision["blocked"] is True
                    else "accepted"
                    if decision["accepted"]
                    else "candidate"
                ),
                "content_kind": "article" if brief is not None else "event",
                "report_tags": list((brief or {}).get("topic_tags") or []),
                "title": (brief or {}).get("headline") or (trigger or {}).get("source_title"),
                "summary": (brief or {}).get("analysis_summary"),
                "trigger": trigger,
                "article_brief": brief,
                "task": None,
                "decision_status": decision["status"],
                "verification_status": decision["verification_status"],
                "blocked": decision["blocked"],
                "accepted": decision["accepted"],
                "actionable": decision["actionable"],
            }
        )

    return {
        "status": "available" if items else "empty",
        "date": date,
        "as_of": max(as_of_values) if as_of_values else None,
        "latest_published_at": max(
            (str(item["published_at"]) for item in items if item.get("published_at")),
            default=None,
        ),
        "message_count": len(items),
        "accepted_count": sum(1 for item in items if item["accepted"]),
        "high_value_count": sum(
            1
            for item in items
            if item["actionable"] and str((item.get("trigger") or {}).get("priority") or "") == "high"
        ),
        "triggered_count": len(trigger_by_url),
        "brief_count": len(brief_by_url),
        "task_count": 0,
        "blocked_count": sum(1 for item in items if item["blocked"] is True),
        "actionable_count": sum(1 for item in items if item["actionable"]),
        "source_refs": [],
        "messages": items,
        "data_quality": {
            "feature_run_count": len(set(run_ids)),
            "trigger_count": len(trigger_by_url),
            "brief_count": len(brief_by_url),
        },
        "page_layer": "ADS",
    }


def _decision_state(*sources: dict[str, Any] | None) -> dict[str, Any]:
    statuses: list[str] = []
    explicit_blocked: list[bool] = []
    explicit_actionable: list[bool] = []
    explicit_accepted: list[bool] = []
    verification_status: str | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        nested = source.get("data_quality") if isinstance(source.get("data_quality"), dict) else {}
        task = source.get("task") if isinstance(source.get("task"), dict) else {}
        for container in (source, nested, task):
            for key in ("decision_status", "quality_status", "review_status", "gate_status", "status"):
                value = str(container.get(key) or "").strip().lower()
                if value:
                    statuses.append(value)
            for key, target in (
                ("blocked", explicit_blocked),
                ("actionable", explicit_actionable),
                ("accepted", explicit_accepted),
            ):
                if isinstance(container.get(key), bool):
                    target.append(bool(container[key]))
        candidate_verification = source.get("verification_status") or nested.get("verification_status")
        if candidate_verification:
            verification_status = str(candidate_verification).strip().lower()
            statuses.append(verification_status)

    blocking_status = next((status for status in statuses if status in _BLOCKING_STATUSES), None)
    accepted_status = next((status for status in statuses if status in _ACCEPTED_STATUSES), None)
    non_actionable = any(status in _NON_ACTIONABLE_STATUSES for status in statuses)
    blocked = True if blocking_status or True in explicit_blocked else False if explicit_blocked else None
    accepted = bool((True in explicit_accepted or accepted_status) and blocked is not True and not non_actionable)
    if False in explicit_accepted:
        accepted = False
    actionable = bool((True in explicit_actionable or accepted) and blocked is not True and not non_actionable)
    if False in explicit_actionable:
        actionable = False
    status = blocking_status or accepted_status or (statuses[0] if statuses else "unknown")
    return {
        "status": status,
        "verification_status": verification_status or "unknown",
        "blocked": blocked,
        "accepted": accepted,
        "actionable": actionable,
    }


def _empty(date: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": "dws_news_unavailable",
        "date": date,
        "as_of": None,
        "message_count": 0,
        "accepted_count": 0,
        "high_value_count": 0,
        "triggered_count": 0,
        "brief_count": 0,
        "task_count": 0,
        "blocked_count": 0,
        "actionable_count": 0,
        "source_refs": [],
        "messages": [],
        "data_quality": {},
        "page_layer": "ADS",
    }
