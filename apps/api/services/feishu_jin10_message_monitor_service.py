from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.services._storage import _PROJECT_ROOT
from database.models.task import TaskRun, TaskStep

logger = logging.getLogger(__name__)

_PARSED_MESSAGES_ROOT = Path("storage") / "parsed" / "news" / "jin10_feishu"
_FEATURE_NEWS_ROOT = Path("storage") / "features" / "news"
_JIN10_OUTPUT_ROOT = Path("storage") / "outputs" / "jin10"
_REPORT_CATEGORY_TAGS = {
    "270": "金银日报",
    "271": "外汇日报",
    "272": "原油日报",
    "274": "持仓报告",
    "301": "点位报告",
    "380": "挂单报告",
    "479": "投行说",
    "536": "黄金周报",
}


def list_feishu_jin10_message_monitor_dates(
    *,
    project_root: Path | None = None,
) -> list[str]:
    root = project_root or _PROJECT_ROOT
    parsed_root = root / _PARSED_MESSAGES_ROOT
    if not parsed_root.exists():
        return []

    return [
        child.name
        for child in sorted(
            (
                child for child in parsed_root.iterdir()
                if child.is_dir() and len(child.name) == 10 and child.name[4:5] == "-" and child.name[7:8] == "-"
            ),
            key=lambda child: child.name,
            reverse=True,
        )
        if any(child.glob("messages-*.json"))
    ]


def get_feishu_jin10_message_monitor_latest(
    *,
    project_root: Path | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    parsed_root = root / _PARSED_MESSAGES_ROOT
    if not parsed_root.exists():
        return None

    date_dirs = sorted(
        (
            child for child in parsed_root.iterdir()
            if child.is_dir() and len(child.name) == 10 and child.name[4:5] == "-" and child.name[7:8] == "-"
        ),
        key=lambda child: child.name,
        reverse=True,
    )
    for date_dir in date_dirs:
        if any(date_dir.glob("messages-*.json")):
            return get_feishu_jin10_message_monitor(date=date_dir.name, project_root=root, db=db)
    return None


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
    triggers, triggers_as_of = _load_feature_rows(
        root=root,
        feature_dir=feature_dir,
        filename="daily_analysis_triggers.json",
        key="triggers",
    )
    briefs, briefs_as_of = _load_feature_rows(
        root=root,
        feature_dir=feature_dir,
        filename="jin10_article_briefs.json",
        key="briefs",
    )
    tasks_by_url = _load_task_rows_by_url(db=db, date=date) if db is not None else {}
    reports_by_url = _load_report_rows_by_url(root=root, date=date)

    message_rows_by_id: dict[str, dict[str, Any]] = {}
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
        for row in payload.get("messages") or []:
            normalized = _normalize_message_row(row=row)
            if normalized is None or not _row_should_be_visible(normalized):
                continue
            message_rows_by_id[normalized["message_id"]] = normalized

    rows = sorted(message_rows_by_id.values(), key=lambda row: str(row.get("published_at") or ""), reverse=True)
    rows = [
        _attach_downstream(
            row,
            triggers_by_url=triggers,
            briefs_by_url=briefs,
            tasks_by_url=tasks_by_url,
            reports_by_url=reports_by_url,
        )
        for row in rows
    ]
    latest_published_at = _latest_iso_string(*(str(row.get("published_at") or "") for row in rows))
    as_of = _latest_iso_string(triggers_as_of, briefs_as_of, latest_published_at)

    return {
        "status": "available" if rows else "empty",
        "date": date,
        "as_of": as_of,
        "latest_published_at": latest_published_at,
        "message_count": len(rows),
        "accepted_count": len(rows),
        "high_value_count": sum(1 for row in rows if row.get("filter_status") == "high_value"),
        "triggered_count": sum(1 for row in rows if row.get("trigger") is not None),
        "brief_count": sum(1 for row in rows if row.get("article_brief") is not None),
        "task_count": sum(1 for row in rows if row.get("task") is not None),
        "status_counts": _count_values(row.get("filter_status") for row in rows),
        "access_status_counts": _count_values(
            row.get("article_brief", {}).get("access_status")
            for row in rows
            if isinstance(row.get("article_brief"), dict)
        ),
        "task_status_counts": _count_values(
            row.get("task", {}).get("status")
            for row in rows
            if isinstance(row.get("task"), dict)
        ),
        "blocked_count": sum(1 for row in rows if row.get("blocked")),
        "actionable_count": sum(1 for row in rows if row.get("actionable")),
        "source_refs": source_refs,
        "messages": rows,
        "data_quality": {
            "parsed_artifact_count": len(parsed_files),
            "trigger_url_count": len(triggers),
            "brief_url_count": len(briefs),
            "task_url_count": len(tasks_by_url),
            "report_url_count": len(reports_by_url),
            "warning_count": len(parse_warnings),
        },
    }


def _empty_monitor_payload(*, date: str) -> dict[str, Any]:
    return {
        "status": "empty",
        "date": date,
        "as_of": None,
        "latest_published_at": None,
        "message_count": 0,
        "accepted_count": 0,
        "high_value_count": 0,
        "triggered_count": 0,
        "brief_count": 0,
        "task_count": 0,
        "status_counts": {},
        "access_status_counts": {},
        "task_status_counts": {},
        "blocked_count": 0,
        "actionable_count": 0,
        "source_refs": [],
        "messages": [],
        "data_quality": {
            "parsed_artifact_count": 0,
            "trigger_url_count": 0,
            "brief_url_count": 0,
            "task_url_count": 0,
            "report_url_count": 0,
            "warning_count": 0,
        },
    }


def _normalize_message_row(*, row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None

    message = row.get("message") if isinstance(row.get("message"), dict) else None
    source = message if message is not None else row
    message_id = str(source.get("message_id") or row.get("message_id") or "").strip()
    if not message_id:
        return None

    links = [str(link) for link in source.get("links") or row.get("links") or [] if isinstance(link, str)]
    relevance = row.get("relevance_decision") if isinstance(row.get("relevance_decision"), dict) else {}
    content = _clean_optional_text(source.get("content"))
    title = _clean_optional_text(row.get("title")) or content
    summary = _clean_optional_text(row.get("summary")) or content
    if summary == title:
        summary = None

    return {
        "message_id": message_id,
        "chat_id": source.get("chat_id"),
        "sender_name": source.get("sender_name"),
        "message_type": source.get("message_type"),
        "published_at": source.get("published_at"),
        "title": title,
        "summary": summary,
        "links": links,
        "primary_url": row.get("primary_url") or (links[0] if links else None),
        "source_marker": source.get("source_marker") or row.get("source_marker"),
        "filter_status": str(row.get("filter_status") or relevance.get("decision") or "unknown"),
        "content_kind": "unknown",
        "report_tags": [],
        "trigger": None,
        "article_brief": None,
        "task": None,
    }


def _attach_downstream(
    row: dict[str, Any],
    *,
    triggers_by_url: dict[str, dict[str, Any]],
    briefs_by_url: dict[str, dict[str, Any]],
    tasks_by_url: dict[str, dict[str, Any]],
    reports_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    next_row = dict(row)
    url = str(next_row.get("primary_url") or "")
    url_key = _normalize_source_url_key(url)
    next_row["trigger"] = triggers_by_url.get(url) or triggers_by_url.get(url_key)
    next_row["article_brief"] = briefs_by_url.get(url) or briefs_by_url.get(url_key)
    next_row["task"] = tasks_by_url.get(url) or tasks_by_url.get(url_key)
    report_row = reports_by_url.get(url) or reports_by_url.get(url_key)
    next_row["content_kind"] = _derive_content_kind(next_row, report_row=report_row)
    next_row["report_tags"] = _derive_report_tags(next_row, report_row=report_row)
    next_row["blocked"] = _row_is_blocked(next_row)
    next_row["actionable"] = _row_is_actionable(next_row)
    return next_row


def _load_feature_rows(
    root: Path,
    feature_dir: Path,
    *,
    filename: str,
    key: str,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    result: dict[str, dict[str, Any]] = {}
    latest_as_of: str | None = None
    if not feature_dir.exists():
        return result, latest_as_of
    for artifact_path in sorted(feature_dir.glob(f"*/{filename}")):
        payload = _read_json(artifact_path)
        if not isinstance(payload, dict):
            continue
        latest_as_of = _latest_iso_string(latest_as_of, payload.get("as_of"))
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
            compact_row = _compact_feature_row(row=row, run_id=run_id)
            result[url] = compact_row
            normalized_url = _normalize_source_url_key(url)
            if normalized_url != url:
                result.setdefault(normalized_url, compact_row)
    return result, latest_as_of


def _load_report_rows_by_url(*, root: Path, date: str) -> dict[str, dict[str, Any]]:
    outputs_root = root / _JIN10_OUTPUT_ROOT
    if not outputs_root.exists():
        return {}

    date_dirs = sorted((child for child in outputs_root.iterdir() if child.is_dir()), key=lambda child: child.name, reverse=True)
    prioritized: list[Path] = []
    target = next((child for child in date_dirs if child.name == date), None)
    if target is not None:
        prioritized.append(target)
    prioritized.extend(child for child in date_dirs if child != target)

    result: dict[str, dict[str, Any]] = {}
    for date_dir in prioritized[:14]:
        for artifact_path in sorted(date_dir.glob("*/raw_article_report.json")):
            payload = _read_json(artifact_path)
            compact_row = _compact_report_row(payload=payload)
            if compact_row is None:
                continue
            source_url = compact_row["source_url"]
            result.setdefault(source_url, compact_row)
            normalized_url = _normalize_source_url_key(source_url)
            if normalized_url != source_url:
                result.setdefault(normalized_url, compact_row)
    return result


def _compact_feature_row(*, row: dict[str, Any], run_id: str) -> dict[str, Any]:
    if "trigger_id" in row:
        return {
            "run_id": run_id,
            "priority": row.get("priority"),
            "status": row.get("status"),
            "event_type": row.get("event_type"),
        }
    return {
        "brief_id": row.get("brief_id"),
        "run_id": run_id,
        "headline": row.get("headline"),
        "article_class": row.get("article_class"),
        "display_bucket": row.get("display_bucket"),
        "access_status": row.get("access_status"),
        "source_url": row.get("source_url"),
        "final_url": row.get("final_url"),
        "original_excerpt": row.get("original_excerpt"),
        "key_points": list(row.get("key_points") or []),
        "analysis_summary": row.get("analysis_summary"),
        "asset_tags": list(row.get("asset_tags") or []),
        "topic_tags": list(row.get("topic_tags") or []),
        "suggested_actions": list(row.get("suggested_actions") or []),
        "source_refs": list(row.get("source_refs") or []),
        "detail_artifacts": row.get("detail_artifacts"),
        "created_at": row.get("created_at"),
    }


def _compact_report_row(*, payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    source_url = str(payload.get("source_url") or "").strip()
    if not source_url.startswith(("http://", "https://")):
        return None

    source_refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
    category_code = _report_category_code(source_url=source_url, source_refs=source_refs)
    report_type = _report_type(payload=payload, source_refs=source_refs, category_code=category_code)
    title = _clean_optional_text(payload.get("title"))
    report_tags = _report_tags_from_metadata(
        category_code=category_code,
        report_type=report_type,
        title=title,
        source_url=source_url,
    )
    return {
        "source_url": source_url,
        "category_code": category_code,
        "report_type": report_type,
        "title": title,
        "report_tags": report_tags,
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
            "blocked": False,
            "blocked_reason": None,
            "_error_summary": run.error_summary,
        })
        normalized_url = _normalize_source_url_key(source_url)
        if normalized_url != source_url:
            result.setdefault(normalized_url, existing)
        if existing["run_id"] != str(run.id):
            continue
        step_status = getattr(step.status, "value", str(step.status))
        if step_status == "blocked":
            existing["blocked"] = True
        if not existing["blocked_reason"] and step.blocked_reason:
            existing["blocked_reason"] = step.blocked_reason

    for task in result.values():
        if task["status"] == "blocked":
            task["blocked"] = True
        if task["blocked"] and not task["blocked_reason"]:
            task["blocked_reason"] = task.get("_error_summary") or None
        task.pop("_error_summary", None)
    return result


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _latest_iso_string(*values: Any) -> str | None:
    latest_value: str | None = None
    latest_dt: datetime | None = None
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if latest_dt is None or parsed > latest_dt:
            latest_dt = parsed
            latest_value = value
    return latest_value


def _row_is_blocked(row: dict[str, Any]) -> bool:
    task = row.get("task") if isinstance(row.get("task"), dict) else {}
    if not task:
        return False
    if task.get("blocked") is True:
        return True
    if str(task.get("status") or "") == "blocked":
        return True
    if task.get("blocked_reason"):
        return True
    return False


def _row_is_actionable(row: dict[str, Any]) -> bool:
    if _row_is_blocked(row):
        return False
    return str(row.get("filter_status") or "") in {"candidate", "high_value"}


def _row_should_be_visible(row: dict[str, Any]) -> bool:
    return str(row.get("filter_status") or "") in {"candidate", "high_value"}


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


def _clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    text = re.sub(r"https?://\S+", "", text)
    text = text.replace("[点击查看详情]", "").replace("点击查看详情", "")
    text = text.replace("[来自金十数据APP重要推送]", "").replace("来自金十数据APP重要推送", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_source_url_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[?#].*$", "", text)
    return text.rstrip("/")


def _derive_content_kind(row: dict[str, Any], *, report_row: dict[str, Any] | None) -> str:
    brief = row.get("article_brief") if isinstance(row.get("article_brief"), dict) else {}
    url_candidates = [
        brief.get("source_url"),
        brief.get("final_url"),
        row.get("primary_url"),
        *(row.get("links") or []),
    ]

    for candidate in url_candidates:
        normalized = _normalize_source_url_key(str(candidate or "")).lower()
        if not normalized:
            continue
        if "flash.jin10.com/" in normalized:
            return "flash"
        if any(token in normalized for token in ("xnews.jin10.com/", "svip.jin10.com/", "vip_column")):
            return "article"

    if brief:
        return "article"
    if isinstance(report_row, dict) and (
        report_row.get("report_tags") or report_row.get("report_type") or report_row.get("category_code")
    ):
        return "article"
    return "unknown"


def _report_category_code(*, source_url: str, source_refs: list[Any]) -> str | None:
    normalized = _normalize_source_url_key(source_url)
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        ref_url = _normalize_source_url_key(str(item.get("source_url") or ""))
        asset_type = str(item.get("asset_type") or "").strip().lower()
        category_code = str(item.get("category_code") or "").strip()
        if not category_code:
            continue
        if asset_type in {"meta_json", "report_md"} and ref_url == normalized:
            return category_code
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        category_code = str(item.get("category_code") or "").strip()
        if category_code:
            return category_code
    return None


def _report_type(*, payload: dict[str, Any], source_refs: list[Any], category_code: str | None) -> str | None:
    report_type = str(payload.get("report_type") or "").strip().lower()
    if report_type in {"daily", "weekly"}:
        return report_type
    title = str(payload.get("title") or "").strip()
    if category_code == "536" or "黄金周报" in title:
        return "weekly"
    for item in source_refs:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").lower()
        if "/weekly/" in path or "/黄金周报/" in path:
            return "weekly"
        if "/daily/" in path or "/金银报告/" in path or "/外汇报告/" in path or "/原油报告/" in path:
            return "daily"
    if str(payload.get("source_url") or "").startswith("https://svip.jin10.com/news/"):
        return "daily"
    return None


def _derive_report_tags(row: dict[str, Any], *, report_row: dict[str, Any] | None) -> list[str]:
    if isinstance(report_row, dict):
        tags = [str(tag).strip() for tag in report_row.get("report_tags") or [] if str(tag).strip()]
        if tags:
            return tags[:2]

    brief = row.get("article_brief") if isinstance(row.get("article_brief"), dict) else {}
    text_parts = [
        row.get("title"),
        row.get("summary"),
        brief.get("headline"),
        brief.get("display_bucket"),
        brief.get("analysis_summary"),
        brief.get("original_excerpt"),
        brief.get("article_class"),
        *(brief.get("asset_tags") or []),
        *(brief.get("topic_tags") or []),
    ]
    source_url = str(brief.get("source_url") or row.get("primary_url") or "")
    text = " ".join(str(part).strip() for part in text_parts if str(part or "").strip())
    return _report_tags_from_metadata(
        category_code=None,
        report_type=None,
        title=text,
        source_url=source_url,
    )[:2]


def _report_tags_from_metadata(
    *,
    category_code: str | None,
    report_type: str | None,
    title: str | None,
    source_url: str | None,
) -> list[str]:
    if category_code and category_code in _REPORT_CATEGORY_TAGS:
        return [_REPORT_CATEGORY_TAGS[category_code]]
    if report_type == "weekly":
        return ["黄金周报"]

    text = str(title or "")
    compact_text = text.lower()
    if any(keyword in text for keyword in ("黄金周报", "投资者周报")):
        return ["黄金周报"]
    if any(keyword in text for keyword in ("每日金银报告", "金银报告", "黄金日报", "白银日报")):
        return ["金银日报"]
    if any(keyword in text for keyword in ("每日外汇报告", "外汇报告")):
        return ["外汇日报"]
    if any(keyword in text for keyword in ("每日原油报告", "原油报告")):
        return ["原油日报"]
    if any(keyword in text for keyword in ("持仓报告", "交易者持仓报告")) or " cot" in f" {compact_text}":
        return ["持仓报告"]
    if "挂单报告" in text:
        return ["挂单报告"]
    if any(keyword in text for keyword in ("点位报告", "技术刘")):
        return ["点位报告"]
    if "投行说" in text:
        return ["投行说"]
    if any(keyword in text for keyword in ("每日市场观察", "市场参考")):
        return ["市场参考"]
    if str(source_url or "").startswith("https://svip.jin10.com/news/"):
        return ["VIP报告"]
    return []
