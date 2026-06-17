from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.services.daily_analysis_trigger_service import (
    get_daily_analysis_triggers,
    get_daily_analysis_triggers_latest,
)
from apps.api.services.jin10_article_brief_service import (
    get_jin10_article_briefs,
    get_jin10_article_briefs_latest,
)

_TRIGGER_ACTION = "run_jin10_daily_analysis"
_ARTICLE_BRIEF_ACTION = "queue_daily_analysis"


def get_daily_analysis_followups_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    trigger_payload = get_daily_analysis_triggers_latest(project_root=project_root)
    if trigger_payload is not None:
        article_brief_payload = get_jin10_article_briefs(
            date=str(trigger_payload.get("date") or ""),
            run_id=str(trigger_payload.get("run_id") or ""),
            project_root=project_root,
        )
        return _build_followup_payload(trigger_payload=trigger_payload, article_brief_payload=article_brief_payload)

    article_brief_payload = get_jin10_article_briefs_latest(project_root=project_root)
    if article_brief_payload is None:
        return None
    return _build_followup_payload(trigger_payload=None, article_brief_payload=article_brief_payload)


def get_daily_analysis_followups(*, date: str, run_id: str, project_root: Path | None = None) -> dict[str, Any] | None:
    trigger_payload = get_daily_analysis_triggers(date=date, run_id=run_id, project_root=project_root)
    article_brief_payload = get_jin10_article_briefs(date=date, run_id=run_id, project_root=project_root)
    if trigger_payload is None and article_brief_payload is None:
        return None
    return _build_followup_payload(trigger_payload=trigger_payload, article_brief_payload=article_brief_payload)


def _build_followup_payload(
    *,
    trigger_payload: dict[str, Any] | None,
    article_brief_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    triggers = trigger_payload.get("triggers") if isinstance(trigger_payload, dict) else None
    normalized_triggers = [dict(item) for item in triggers if isinstance(item, dict)] if isinstance(triggers, list) else []
    briefs = article_brief_payload.get("briefs") if isinstance(article_brief_payload, dict) else None
    normalized_briefs = [dict(item) for item in briefs if isinstance(item, dict)] if isinstance(briefs, list) else []

    trigger_followups = [
        {
            "followup_id": str(trigger.get("trigger_id") or ""),
            "queue_type": "jin10_daily_analysis",
            "priority": str(trigger.get("priority") or "medium"),
            "status": "queued",
            "title": str(trigger.get("source_title") or trigger.get("event_type") or "未命名触发器"),
            "source_title": trigger.get("source_title"),
            "source_url": trigger.get("source_url"),
            "source_key": trigger.get("source_key"),
            "source_event_id": trigger.get("source_event_id"),
            "event_type": trigger.get("event_type"),
            "evidence_text": trigger.get("evidence_text"),
            "impact_path": trigger.get("impact_path"),
            "gold_impact": trigger.get("gold_impact"),
            "action": _TRIGGER_ACTION,
            "source_artifact": "daily_analysis_triggers",
            "asset_tags": list(trigger.get("asset_tags") or []),
            "topic_tags": list(trigger.get("topic_tags") or []),
            "reason_codes": list(trigger.get("reason_codes") or []),
            "created_at": trigger.get("created_at"),
            "source_refs": list(trigger.get("source_refs") or []),
            "data_quality": dict(trigger.get("data_quality") or {}),
        }
        for trigger in normalized_triggers
        if _TRIGGER_ACTION in list(trigger.get("suggested_actions") or [])
    ]
    brief_followups = [
        {
            "followup_id": str(brief.get("brief_id") or ""),
            "queue_type": "jin10_daily_analysis",
            "priority": "medium",
            "status": "queued",
            "title": str(brief.get("headline") or "未命名文章跟进"),
            "source_title": brief.get("headline"),
            "headline": brief.get("headline"),
            "summary": brief.get("analysis_summary") or brief.get("original_excerpt"),
            "evidence_text": brief.get("original_excerpt"),
            "key_points": list(brief.get("key_points") or []),
            "source_url": brief.get("source_url"),
            "source_key": "jin10_article_briefs",
            "source_event_id": None,
            "event_type": str(brief.get("article_class") or "market_reference"),
            "action": _ARTICLE_BRIEF_ACTION,
            "source_artifact": "jin10_article_briefs",
            "asset_tags": list(brief.get("asset_tags") or []),
            "topic_tags": list(brief.get("topic_tags") or []),
            "reason_codes": [str(brief.get("article_class") or "market_reference")],
            "created_at": brief.get("created_at"),
            "source_refs": list(brief.get("source_refs") or []),
            "data_quality": dict(brief.get("data_quality") or {}),
        }
        for brief in normalized_briefs
        if _ARTICLE_BRIEF_ACTION in list(brief.get("suggested_actions") or [])
    ]
    followups = [*trigger_followups, *brief_followups]

    high_priority_count = sum(1 for item in followups if item["priority"] == "high")
    if trigger_payload is not None and article_brief_payload is not None:
        source_artifact = "mixed"
    elif trigger_payload is not None:
        source_artifact = "daily_analysis_triggers"
    else:
        source_artifact = "jin10_article_briefs"

    artifact_paths = {
        key: value
        for key, value in {
            "daily_analysis_triggers": trigger_payload.get("artifact_path") if isinstance(trigger_payload, dict) else None,
            "jin10_article_briefs": article_brief_payload.get("artifact_path") if isinstance(article_brief_payload, dict) else None,
        }.items()
        if value
    }

    primary_payload = trigger_payload or article_brief_payload or {}
    return {
        "status": "available" if followups else "empty",
        "date": primary_payload.get("date"),
        "run_id": primary_payload.get("run_id"),
        "artifact_path": primary_payload.get("artifact_path"),
        "artifact_paths": artifact_paths,
        "as_of": primary_payload.get("as_of"),
        "rule_version": primary_payload.get("rule_version"),
        "source_artifact": source_artifact,
        "queue_count": len(followups),
        "high_priority_count": high_priority_count,
        "followups": followups,
        "data_quality": {
            "trigger_count": trigger_payload.get("trigger_count", 0) if isinstance(trigger_payload, dict) else 0,
            "brief_count": article_brief_payload.get("brief_count", 0) if isinstance(article_brief_payload, dict) else 0,
            "actionable_trigger_count": len(followups),
            "source_key_counts": dict(trigger_payload.get("source_key_counts") or {}) if isinstance(trigger_payload, dict) else {},
            "priority_counts": dict(trigger_payload.get("priority_counts") or {}) if isinstance(trigger_payload, dict) else {},
        },
    }
