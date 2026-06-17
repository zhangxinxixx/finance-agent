from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.services._storage import _PROJECT_ROOT
from database.models.task import TaskRun, TaskStep

logger = logging.getLogger(__name__)

_PARSED_MESSAGES_ROOT = Path("storage") / "parsed" / "news" / "jin10_feishu"
_FEATURE_NEWS_ROOT = Path("storage") / "features" / "news"


def get_feishu_jin10_message_monitor(
    *,
    date: str,
    project_root: Path | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    parsed_dir = root / _PARSED_MESSAGES_ROOT / date
    if not parsed_dir.exists():
        return _empty_monitor_payload(date=date)

    parsed_files = sorted(parsed_dir.glob("messages-*.json"))
    if not parsed_files:
        return _empty_monitor_payload(date=date)

    feature_dir = root / _FEATURE_NEWS_ROOT / date
    triggers = _load_feature_rows(root=root, feature_dir=feature_dir, filename="daily_analysis_triggers.json", key="triggers")
    briefs = _load_feature_rows(root=root, feature_dir=feature_dir, filename="jin10_article_briefs.json", key="briefs")
    tasks_by_url = _load_task_rows_by_url(db=db, date=date) if db is not None else {}

    message_rows_by_id: dict[str, dict[str, Any]] = {}
    accepted_by_message_id: dict[str, dict[str, Any]] = {}
    source_refs: list[dict[str, Any]] = []
    parse_warnings: list[str] = []

    for parsed_file in parsed_files:
        payload = _read_json(parsed_file)
        if not isinstance(payload, dict):
            parse_warnings.append(f"invalid parsed artifact: {parsed_file.relative_to(root).as_posix()}")
            continue
        source_refs.append({
            "source": "jin10_feishu",
            "source_ref": f"jin10_feishu_messages:{date}/{parsed_file.name}",
            "status": "ok",
            "path": parsed_file.relative_to(root).as_posix(),
        })
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                raw_payload = item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {}
                message_id = str(raw_payload.get("message_id") or "")
                if message_id:
                    accepted_by_message_id[message_id] = item
        for row in payload.get("messages") or []:
            normalized = _normalize_message_row(
                row=row,
                parsed_file=parsed_file,
                root=root,
                accepted_item=None,
                triggers_by_url=triggers,
                briefs_by_url=briefs,
                tasks_by_url=tasks_by_url,
            )
            if normalized is None:
                continue
            message_rows_by_id[normalized["message_id"]] = normalized

    for message_id, accepted in accepted_by_message_id.items():
        existing = message_rows_by_id.get(message_id)
        if existing is not None:
            message_rows_by_id[message_id] = _attach_accepted_item(existing, accepted)

    rows = sorted(message_rows_by_id.values(), key=lambda row: str(row.get("published_at") or ""), reverse=True)
    rows = [
        _attach_downstream(row, triggers_by_url=triggers, briefs_by_url=briefs, tasks_by_url=tasks_by_url)
        for row in rows
    ]

    return {
        "status": "available" if rows else "empty",
        "date": date,
        "message_count": len(rows),
        "accepted_count": sum(1 for row in rows if row.get("filter_status") in {"candidate", "high_value"}),
        "triggered_count": sum(1 for row in rows if row.get("trigger") is not None),
        "brief_count": sum(1 for row in rows if row.get("article_brief") is not None),
        "task_count": sum(1 for row in rows if row.get("task") is not None),
        "source_refs": source_refs,
        "messages": rows,
        "data_quality": {
            "parsed_artifact_count": len(parsed_files),
            "trigger_url_count": len(triggers),
            "brief_url_count": len(briefs),
            "task_url_count": len(tasks_by_url),
            "warning_count": len(parse_warnings),
            "warnings": parse_warnings,
        },
    }


def _empty_monitor_payload(*, date: str) -> dict[str, Any]:
    return {
        "status": "empty",
        "date": date,
        "message_count": 0,
        "accepted_count": 0,
        "triggered_count": 0,
        "brief_count": 0,
        "task_count": 0,
        "source_refs": [],
        "messages": [],
        "data_quality": {
            "parsed_artifact_count": 0,
            "trigger_url_count": 0,
            "brief_url_count": 0,
            "task_url_count": 0,
            "warning_count": 0,
            "warnings": [],
        },
    }


def _normalize_message_row(
    *,
    row: Any,
    parsed_file: Path,
    root: Path,
    accepted_item: dict[str, Any] | None,
    triggers_by_url: dict[str, dict[str, Any]],
    briefs_by_url: dict[str, dict[str, Any]],
    tasks_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    message_id = str(message.get("message_id") or "").strip()
    if not message_id:
        return None
    links = [str(link) for link in message.get("links") or [] if isinstance(link, str)]
    relevance = row.get("relevance_decision") if isinstance(row.get("relevance_decision"), dict) else {}
    filter_status = str(relevance.get("decision") or "unknown")
    normalized = {
        "message_id": message_id,
        "chat_id": message.get("chat_id"),
        "sender_name": message.get("sender_name"),
        "message_type": message.get("message_type"),
        "published_at": message.get("published_at"),
        "content": message.get("content"),
        "links": links,
        "primary_url": links[0] if links else None,
        "source_marker": message.get("source_marker"),
        "looks_like_jin10": bool(row.get("looks_like_jin10")),
        "filter_status": filter_status,
        "relevance": {
            "score": relevance.get("score"),
            "reasons": list(relevance.get("reasons") or []),
            "asset_tags": list(relevance.get("asset_tags") or []),
            "topic_tags": list(relevance.get("topic_tags") or []),
            "event_type_hint": relevance.get("event_type_hint"),
            "need_detail_fetch": bool(relevance.get("need_detail_fetch")),
            "need_verification": bool(relevance.get("need_verification")),
        },
        "accepted_item": None,
        "trigger": None,
        "article_brief": None,
        "task": None,
        "parsed_artifact_path": parsed_file.relative_to(root).as_posix(),
    }
    if accepted_item is not None:
        normalized = _attach_accepted_item(normalized, accepted_item)
    return _attach_downstream(normalized, triggers_by_url=triggers_by_url, briefs_by_url=briefs_by_url, tasks_by_url=tasks_by_url)


def _attach_accepted_item(row: dict[str, Any], accepted: dict[str, Any]) -> dict[str, Any]:
    next_row = dict(row)
    raw_payload = accepted.get("raw_payload") if isinstance(accepted.get("raw_payload"), dict) else {}
    relevance = raw_payload.get("relevance_decision") if isinstance(raw_payload.get("relevance_decision"), dict) else {}
    next_row["accepted_item"] = {
        "source_key": accepted.get("source_key"),
        "title": accepted.get("title"),
        "url": accepted.get("url"),
        "domain": accepted.get("domain"),
        "event_type": accepted.get("event_type"),
        "duplicate_key": accepted.get("duplicate_key"),
        "verification_status": accepted.get("verification_status"),
    }
    if relevance:
        next_row["filter_status"] = str(relevance.get("decision") or next_row.get("filter_status") or "unknown")
        next_row["relevance"] = {
            **dict(next_row.get("relevance") or {}),
            "score": relevance.get("score"),
            "reasons": list(relevance.get("reasons") or []),
            "asset_tags": list(relevance.get("asset_tags") or []),
            "topic_tags": list(relevance.get("topic_tags") or []),
            "event_type_hint": relevance.get("event_type_hint"),
            "need_detail_fetch": bool(relevance.get("need_detail_fetch")),
            "need_verification": bool(relevance.get("need_verification")),
        }
    return next_row


def _attach_downstream(
    row: dict[str, Any],
    *,
    triggers_by_url: dict[str, dict[str, Any]],
    briefs_by_url: dict[str, dict[str, Any]],
    tasks_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    next_row = dict(row)
    url = str(next_row.get("primary_url") or "")
    next_row["trigger"] = triggers_by_url.get(url)
    next_row["article_brief"] = briefs_by_url.get(url)
    next_row["task"] = tasks_by_url.get(url)
    return next_row


def _load_feature_rows(root: Path, feature_dir: Path, *, filename: str, key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not feature_dir.exists():
        return result
    for artifact_path in sorted(feature_dir.glob(f"*/{filename}")):
        payload = _read_json(artifact_path)
        if not isinstance(payload, dict):
            continue
        run_id = artifact_path.parent.name
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("source_url") or row.get("detail_url") or "").strip()
            if not url:
                continue
            result[url] = _compact_feature_row(row=row, run_id=run_id, artifact_path=artifact_path, root=root)
    return result


def _compact_feature_row(*, row: dict[str, Any], run_id: str, artifact_path: Path, root: Path) -> dict[str, Any]:
    artifact_path_value = _relative_path(artifact_path, root=root)
    if "trigger_id" in row:
        return {
            "trigger_id": row.get("trigger_id"),
            "run_id": run_id,
            "priority": row.get("priority"),
            "status": row.get("status"),
            "event_type": row.get("event_type"),
            "reason_codes": list(row.get("reason_codes") or []),
            "suggested_actions": list(row.get("suggested_actions") or []),
            "data_quality": dict(row.get("data_quality") or {}),
            "artifact_path": artifact_path_value,
        }
    return {
        "brief_id": row.get("brief_id"),
        "run_id": run_id,
        "article_class": row.get("article_class"),
        "display_bucket": row.get("display_bucket"),
        "headline": row.get("headline"),
        "access_status": row.get("access_status"),
        "final_url": row.get("final_url"),
        "analysis_summary": row.get("analysis_summary"),
        "detail_artifacts": dict(row.get("detail_artifacts") or {}),
        "data_quality": dict(row.get("data_quality") or {}),
        "artifact_path": artifact_path_value,
    }


def _load_task_rows_by_url(*, db: Session, date: str) -> dict[str, dict[str, Any]]:
    rows = (
        db.query(TaskRun, TaskStep)
        .join(TaskStep, TaskStep.task_run_id == TaskRun.id)
        .filter(TaskRun.task_type == "daily_analysis_followup")
        .filter(TaskRun.trade_date == date)
        .order_by(TaskRun.created_at.desc(), TaskStep.step_order.asc())
        .limit(500)
        .all()
    )
    result: dict[str, dict[str, Any]] = {}
    for run, step in rows:
        payload = _parse_json(step.input_json)
        output = _parse_json(step.output_json)
        source_url = _source_url_from_payload(payload) or _source_url_from_payload(output)
        if not source_url:
            continue
        existing = result.setdefault(source_url, {
            "run_id": str(run.id),
            "status": getattr(run.status, "value", str(run.status)),
            "current_stage": run.current_stage,
            "progress": run.progress,
            "error_summary": run.error_summary,
            "steps": [],
        })
        if existing["run_id"] != str(run.id):
            continue
        existing["steps"].append({
            "name": step.name,
            "status": getattr(step.status, "value", str(step.status)),
            "blocked_reason": step.blocked_reason,
            "error_type": step.error_type,
        })
    return result


def _relative_path(path: Path, *, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_url_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    source_url = payload.get("source_url")
    if isinstance(source_url, str) and source_url.startswith(("http://", "https://")):
        return source_url
    followup = payload.get("followup")
    if isinstance(followup, dict):
        source_url = followup.get("source_url")
        if isinstance(source_url, str) and source_url.startswith(("http://", "https://")):
            return source_url
    detail = payload.get("detail_fetch")
    if isinstance(detail, dict):
        source_url = detail.get("detail_url") or detail.get("final_url")
        if isinstance(source_url, str) and source_url.startswith(("http://", "https://")):
            return source_url
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read JSON artifact", exc_info=True, extra={"path": str(path)})
        return None


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
