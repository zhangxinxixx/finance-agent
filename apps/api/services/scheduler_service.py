"""调度中心聚合服务。

组合 task_runs、data_source_status、cron_jobs、analysis_snapshots 等，提供统一的调度视图。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload

from apps.api.services.source_service import get_data_source_statuses
from database.models.task import TaskRun


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _coerce_utc(value: Any) -> datetime | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── Task Category Definitions ──

TASK_CATEGORIES = {
    "data_collection": {
        "label": "数据采集",
        "color": "#3b82f6",
        "description": "数据采集器：FRED、Fed、Treasury、DXY、COT、Technical",
        "pattern": ["macro", "fred", "fed", "treasury", "dxy", "cot", "technical", "positioning", "cme", "bulletin", "jin10"],
    },
    "data_parsing": {
        "label": "数据解析",
        "color": "#8b5cf6",
        "description": "解析器：CME PDF、宏观解析、期权解析",
        "pattern": ["parse", "parser"],
    },
    "flash_analysis": {
        "label": "快讯分析",
        "color": "#f97316",
        "description": "Jin10 快讯分析：重点消息 Agent 解析",
        "pattern": ["flash_analysis"],
    },
    "analysis": {
        "label": "分析任务",
        "color": "#f59e0b",
        "description": "Agent 分析：宏观分析、期权分析、新闻整理",
        "pattern": ["analysis", "agent", "macro_analysis", "options_analysis"],
    },
    "report": {
        "label": "报告生成",
        "color": "#10b981",
        "description": "报告产出：日报、策略卡片、可视化",
        "pattern": ["report", "dashboard", "visual", "card"],
    },
    "governance": {
        "label": "治理任务",
        "color": "#64748b",
        "description": "系统维护：记忆整理、知识库同步、数据清理",
        "pattern": ["mem0", "memory", "governance", "maintenance", "cleanup"],
    },
    "other": {
        "label": "其他",
        "color": "#94a3b8",
        "description": "未归类任务",
        "pattern": [],
    },
}

_DEFAULT_SOURCE_TASK_PATTERNS: dict[str, tuple[str, ...]] = {
    "macro": ("macro_collect", "macro_feature", "report_render"),
    "cme": ("cme_download", "cme_parse", "cme_ingest", "option_wall", "options_analysis"),
    "technical": ("technical", "jin10_refresh_jin10_quotes", "jin10_refresh_jin10_kline"),
    "positioning": ("positioning",),
    "reports": ("jin10_report", "report_analysis", "report_render"),
    "news": ("news_collect", "news_feature", "news_brief", "report_analysis"),
}

_SOURCE_TASK_PATTERNS: dict[str, tuple[str, ...]] = {
    "fred": ("fred", "macro_collect", "macro_feature", "report_render"),
    "openbb_macro": ("openbb", "macro_collect", "macro_feature", "report_render"),
    "fed": ("fed", "macro_collect", "macro_feature", "report_render"),
    "treasury": ("treasury", "macro_collect", "macro_feature", "report_render"),
    "dxy": ("dxy", "macro_collect", "macro_feature", "technical"),
    "cme_daily_bulletin": ("cme_download", "cme_parse", "bulletin"),
    "cme_options": ("cme_ingest", "option_wall", "options_analysis", "cme_options"),
    "technical_yahoo": ("technical", "jin10_refresh_jin10_quotes", "jin10_refresh_jin10_kline"),
    "positioning_cot": ("positioning", "cot"),
    "jin10_news": ("news_collect", "news_feature", "news_brief", "jin10_report", "report_analysis", "flash_article_analysis"),
    "jin10_flash": ("jin10_refresh_jin10_flash", "flash_article_analysis", "news_collect"),
    "jin10_mcp_flash": ("jin10_refresh_jin10_flash", "flash_article_analysis", "news_collect"),
    "jin10_mcp_calendar": ("jin10_refresh_jin10_calendar", "news_collect", "news_feature"),
    "jin10_mcp_market": ("jin10_refresh_jin10_quotes", "jin10_refresh_jin10_kline", "technical"),
    "jin10_xnews_public": ("jin10_report", "report_analysis", "news_feature"),
    "jin10_datacenter_reports": ("jin10_report", "report_analysis", "macro_feature"),
    "jin10_svip_reports": ("jin10_report", "report_analysis", "report_render"),
    "jin10_feishu": ("feishu", "news_collect", "news_feature", "news_brief", "flash_article_analysis"),
    "fed_rss": ("news_collect", "news_feature", "news_brief"),
    "bls_calendar": ("news_collect", "news_feature"),
    "bea_calendar": ("news_collect", "news_feature"),
    "eia_energy": ("news_collect", "news_feature"),
    "gdelt_news": ("news_collect", "news_feature", "news_brief"),
    "google_news_rss": ("news_collect", "news_feature", "news_brief"),
    "reuters_public_news": ("news_collect", "news_feature", "news_brief"),
}


def _classify_task(task_type: str | None) -> str:
    """根据 task_type 分类到标准类别。"""
    if not task_type:
        return "other"
    raw = task_type.lower()
    for cat_key, cat_def in TASK_CATEGORIES.items():
        if cat_key == "other":
            continue
        for pattern in cat_def["pattern"]:
            if pattern in raw:
                return cat_key
    return "other"


def get_scheduler_overview(
    db: Session,
    days: int = 7,
    limit: int = 50,
) -> dict[str, Any]:
    """返回调度中心全景视图。"""
    now = utc_now()
    since = now - timedelta(days=days)

    # 1. 任务运行列表
    runs = (
        db.query(TaskRun)
        .options(selectinload(TaskRun.steps))
        .order_by(TaskRun.created_at.desc())
        .limit(limit)
        .all()
    )
    source_candidate_runs = (
        db.query(TaskRun)
        .options(selectinload(TaskRun.steps))
        .order_by(TaskRun.created_at.desc())
        .limit(max(limit * 8, 400))
        .all()
    )

    # 2. 统计
    stats = _build_task_stats(db, since, now)
    daily_summary = _build_daily_summary(db, since, now)

    # 3. 数据源状态
    source_status = _get_data_source_status(db)

    # 4. Cron 作业状态
    cron_jobs = _get_cron_job_status()

    # 5. 产出物摘要
    artifacts_summary = _get_artifacts_summary()

    # 6. 任务分类统计
    category_stats = _build_category_stats(runs)

    # 7. 快讯持久化统计
    flash_stats = _get_flash_stats()
    input_source_matrix = _build_input_source_matrix(source_candidate_runs)
    input_source_summary = _summarize_input_source_matrix(input_source_matrix)

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "summary": {
            "total_runs": len(runs),
            "today_runs": sum(
                1
                for r in runs
                if (
                    created_at := _coerce_utc(r.created_at)
                ) is not None and created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            ),
            "success_count": stats["success"],
            "failed_count": stats["failed"],
            "running_count": stats["running"],
            "pending_count": stats["pending"],
            "data_sources_ok": source_status.get("ok", 0),
            "data_sources_total": source_status.get("total", 0),
            "artifacts_today": artifacts_summary.get("today_count", 0),
            "flash_total": flash_stats.get("total", 0),
            "flash_key_events": flash_stats.get("key_events", 0),
            "flash_unanalyzed": flash_stats.get("unanalyzed_key_events", 0),
            "input_sources_connected": input_source_summary["connected"],
            "input_sources_data_only": input_source_summary["data_only"],
            "input_sources_waiting": input_source_summary["waiting"],
        },
        "task_runs": [_serialize_run(r) for r in runs],
        "category_stats": category_stats,
        "daily_summary": daily_summary,
        "data_source_status": source_status,
        "cron_jobs": cron_jobs,
        "artifacts_summary": artifacts_summary,
        "flash_stats": flash_stats,
        "input_source_summary": input_source_summary,
        "input_source_matrix": input_source_matrix,
    }


def _build_task_stats(db: Session, since: datetime, now: datetime) -> dict:
    try:
        result = db.execute(
            text("""
                SELECT status::text, COUNT(*) as cnt
                FROM task_runs
                WHERE created_at >= :since
                GROUP BY status::text
            """),
            {"since": since},
        ).fetchall()
    except Exception:
        return {"success": 0, "failed": 0, "running": 0, "pending": 0, "other": 0}

    stats = {"success": 0, "failed": 0, "running": 0, "pending": 0, "other": 0}
    for row in result:
        status_str = str(row[0])
        cnt = int(row[1])
        if status_str in ("success", "partial_success"):
            stats["success"] += cnt
        elif status_str in ("failed", "blocked", "stale", "degraded"):
            stats["failed"] += cnt
        elif status_str in ("running", "retrying"):
            stats["running"] += cnt
        elif status_str in ("pending", "queued"):
            stats["pending"] += cnt
        else:
            stats["other"] += cnt
    return stats


def _build_daily_summary(db: Session, since: datetime, now: datetime) -> list[dict]:
    """按日期统计任务执行情况。"""
    try:
        result = db.execute(
            text("""
                SELECT
                    to_char(created_at, 'YYYY-MM-DD') as day,
                    COUNT(*) as total,
                    COUNT(CASE WHEN status::text IN ('SUCCESS','PARTIAL_SUCCESS') THEN 1 END) as success,
                    COUNT(CASE WHEN status::text IN ('FAILED','BLOCKED','STALE','DEGRADED') THEN 1 END) as failed,
                    COUNT(CASE WHEN status::text IN ('RUNNING','RETRYING') THEN 1 END) as running
                FROM task_runs
                WHERE created_at >= :since
                GROUP BY to_char(created_at, 'YYYY-MM-DD')
                ORDER BY to_char(created_at, 'YYYY-MM-DD') DESC
            """),
            {"since": since},
        ).fetchall()
    except Exception:
        return []

    return [
        {
            "date": str(row[0]),
            "total": int(row[1]),
            "success": int(row[2]),
            "failed": int(row[3]),
            "running": int(row[4]),
        }
        for row in result
    ]


def _build_category_stats(runs: list[TaskRun]) -> dict[str, dict]:
    """按任务类别统计。"""
    cat_counts: dict[str, dict] = {}
    for cat_key, cat_def in TASK_CATEGORIES.items():
        cat_counts[cat_key] = {**cat_def, "total": 0, "success": 0, "failed": 0}

    for run in runs:
        cat = _classify_task(run.task_type)
        if cat not in cat_counts:
            cat = "other"
        cat_counts[cat]["total"] += 1
        status_val = run.status.value if hasattr(run.status, "value") else str(run.status)
        if status_val in ("success", "partial_success"):
            cat_counts[cat]["success"] += 1
        elif status_val in ("failed", "blocked", "stale", "degraded", "cancelled"):
            cat_counts[cat]["failed"] += 1

    return cat_counts


def _get_data_source_status(db: Session) -> dict:
    """从 data_source_status 表读取数据源健康度。"""
    try:
        result = db.execute(
            text("SELECT status, COUNT(*) as cnt FROM data_source_status GROUP BY status")
        ).fetchall()
        status_map = {"ok": 0, "error": 0, "not_connected": 0, "total": 0}
        for row in result:
            status_str = str(row[0]) if row[0] else "unknown"
            cnt = int(row[1])
            status_map["total"] += cnt
            if status_str == "ok":
                status_map["ok"] += cnt
            elif status_str in ("error", "failed"):
                status_map["error"] += cnt
            elif status_str in ("not_connected", "unavailable"):
                status_map["not_connected"] += cnt
        return status_map
    except Exception:
        return {"ok": 0, "error": 0, "not_connected": 0, "total": 0}


def _get_cron_job_status() -> list[dict]:
    """获取 Hermes 内部调度作业状态。"""
    try:
        from pathlib import Path
        import json
        jobs_file = Path.home() / ".hermes" / "cron" / "jobs.json"
        if not jobs_file.exists():
            return []
        with open(jobs_file) as f:
            data = json.load(f)
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        return [
            {
                "job_id": j.get("job_id", ""),
                "name": j.get("name", ""),
                "schedule": j.get("schedule", ""),
                "enabled": j.get("enabled", False),
                "last_run_at": j.get("last_run_at"),
                "last_status": j.get("last_status"),
                "next_run_at": j.get("next_run_at"),
            }
            for j in jobs
        ]
    except Exception:
        return []


def _get_artifacts_summary() -> dict:
    """获取产出物摘要。"""
    try:
        from pathlib import Path
        storage = Path("/home/zxx/workspace/finance-agent/storage")
        today = utc_now().strftime("%Y-%m-%d")

        def count_files(dirpath: Path, pattern: str) -> int:
            import glob
            return len(glob.glob(str(dirpath / pattern), recursive=True))

        return {
            "today_count": count_files(storage / "raw" / "*" / today, "**/*"),
            "recent_outputs": _list_recent_outputs(storage),
        }
    except Exception:
        return {"today_count": 0, "recent_outputs": []}


def _get_flash_stats() -> dict[str, Any]:
    """获取 Jin10 快讯持久化统计。"""
    try:
        from database.models.engine import SessionLocal
        from apps.scheduler.flash_persistence import get_flash_stats
        with SessionLocal() as session:
            return get_flash_stats(session)
    except Exception:
        return {"total": 0, "key_events": 0, "unanalyzed_key_events": 0, "latest_message_time": None}


def _list_recent_outputs(storage_dir) -> list[dict]:
    """列出最近的产出文件。"""
    import glob
    from pathlib import Path
    outputs = []
    for pattern in ["storage/outputs/**/*.md", "storage/outputs/**/*.json"]:
        files = glob.glob(str(storage_dir.parent / pattern), recursive=True)
        for f in sorted(files, reverse=True)[:10]:
            p = Path(f)
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                outputs.append({
                    "path": f.replace(str(storage_dir.parent) + "/", ""),
                    "name": p.name,
                    "updated_at": mtime.isoformat(),
                    "size": p.stat().st_size,
                })
            except OSError:
                pass
    return outputs[:20]


def _serialize_run(run: TaskRun) -> dict[str, Any]:
    """序列化 TaskRun 为前端可用的字典。"""
    return {
        "run_id": str(run.id),
        "task_name": run.name,
        "task_type": run.task_type or "unknown",
        "category": _classify_task(run.task_type),
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "current_stage": run.current_stage,
        "trade_date": run.trade_date,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "error_summary": run.error_summary,
        "progress": run.progress,
        "step_count": len(run.steps) if run.steps else 0,
        "snapshot_id": run.snapshot_id,
    }


def _task_match_text(run: TaskRun) -> str:
    parts = [
        run.task_type or "",
        run.name or "",
        run.current_stage or "",
    ]
    return " ".join(parts).lower()


def _step_match_text(run: TaskRun, step: Any) -> str:
    parts = [
        run.task_type or "",
        run.name or "",
        getattr(step, "name", "") or "",
        getattr(step, "stage", "") or "",
        getattr(step, "task_kind", "") or "",
    ]
    return " ".join(parts).lower()


def _matched_task_labels(run: TaskRun, expected_task_types: list[str]) -> list[str]:
    if not expected_task_types:
        return []

    matched_labels: list[str] = []
    run_haystack = _task_match_text(run)
    if any(pattern in run_haystack for pattern in expected_task_types):
        for candidate in (run.task_type, run.name, run.current_stage):
            label = str(candidate or "").strip()
            if label:
                matched_labels.append(label)
                break

    for step in run.steps or []:
        haystack = _step_match_text(run, step)
        if not any(pattern in haystack for pattern in expected_task_types):
            continue
        for candidate in (step.name, step.stage, step.task_kind):
            label = str(candidate or "").strip()
            if label and label not in matched_labels:
                matched_labels.append(label)
                break

    return matched_labels


def _expected_task_patterns(source: dict[str, Any]) -> tuple[str, ...]:
    source_key = str(source.get("source_key") or "")
    source_group = str(source.get("source_group") or "")
    explicit = _SOURCE_TASK_PATTERNS.get(source_key)
    if explicit:
        return explicit
    return _DEFAULT_SOURCE_TASK_PATTERNS.get(source_group, ())


def _source_latest_update_time(source: dict[str, Any]) -> str | None:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    latest_raw_ref = metadata.get("latest_raw_ref") if isinstance(metadata.get("latest_raw_ref"), dict) else {}
    candidates = [
        source.get("latest_raw_time"),
        source.get("latest_parsed_time"),
        metadata.get("latest_artifact_mtime"),
        latest_raw_ref.get("published_at"),
        metadata.get("latest_health_at"),
    ]
    parsed = [dt for dt in (_coerce_utc(value) for value in candidates) if dt is not None]
    if not parsed:
        return None
    latest = max(parsed)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest.isoformat()


def _source_latest_artifact(source: dict[str, Any]) -> str | None:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    latest_raw_ref = metadata.get("latest_raw_ref") if isinstance(metadata.get("latest_raw_ref"), dict) else {}
    for candidate in (
        latest_raw_ref.get("path"),
        latest_raw_ref.get("file_path"),
        latest_raw_ref.get("url"),
        metadata.get("latest_raw_url"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    artifact_layers = metadata.get("artifact_layers")
    if isinstance(artifact_layers, list):
        for candidate in artifact_layers:
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    return None


def _source_has_data_evidence(source: dict[str, Any], latest_update_time: str | None, latest_artifact: str | None) -> bool:
    return bool(
        source.get("raw_ingested")
        or source.get("parsed")
        or source.get("analysis_ready")
        or latest_update_time
        or latest_artifact
    )


def _build_input_source_matrix(candidate_runs: list[TaskRun]) -> list[dict[str, Any]]:
    source_payload = get_data_source_statuses()
    sources = source_payload.get("sources", [])
    matrix: list[dict[str, Any]] = []

    for source in sources:
        if not isinstance(source, dict):
            continue
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        expected_task_types = list(_expected_task_patterns(source))
        matched_runs: list[tuple[TaskRun, list[str]]] = []
        for run in candidate_runs:
            matched_labels = _matched_task_labels(run, expected_task_types)
            if matched_labels:
                matched_runs.append((run, matched_labels))
        recent_task_types: list[str] = []
        for _, labels in matched_runs:
            for label in labels:
                if label and label not in recent_task_types:
                    recent_task_types.append(label)
                if len(recent_task_types) >= 4:
                    break
            if len(recent_task_types) >= 4:
                break

        latest_task = matched_runs[0][0] if matched_runs else None
        latest_update_time = _source_latest_update_time(source)
        latest_artifact = _source_latest_artifact(source)
        has_data_evidence = _source_has_data_evidence(source, latest_update_time, latest_artifact)
        task_log_status = "connected" if latest_task else "data_only" if has_data_evidence else "waiting"

        if task_log_status == "connected":
            task_log_label = "任务与日志已接入"
        elif task_log_status == "data_only":
            task_log_label = "仅数据接入，缺任务日志"
        else:
            task_log_label = "等待接入"

        notes_parts = [
            str(source.get("gating_reason") or "").strip(),
            str(metadata.get("notes") or "").strip(),
        ]
        notes = "；".join(part for part in notes_parts if part)

        matrix.append(
            {
                "source_key": source.get("source_key"),
                "source_label": metadata.get("frontend_label") or source.get("source_name") or source.get("source_key"),
                "source_name": source.get("source_name"),
                "source_group": source.get("source_group"),
                "source_type": source.get("source_type"),
                "access_method": source.get("access_method"),
                "status": source.get("status"),
                "health_state": source.get("health_state") or metadata.get("health_state"),
                "readiness_state": source.get("readiness_state"),
                "gate_state": source.get("gate_state"),
                "gating_reason": source.get("gating_reason"),
                "configured": bool(source.get("configured")),
                "raw_ingested": bool(source.get("raw_ingested")),
                "parsed": bool(source.get("parsed")),
                "analysis_ready": bool(source.get("analysis_ready")),
                "latest_update_time": latest_update_time,
                "latest_artifact": latest_artifact,
                "expected_task_types": expected_task_types,
                "recent_task_types": recent_task_types,
                "task_log_status": task_log_status,
                "task_log_label": task_log_label,
                "latest_task_run": _serialize_run(latest_task) if latest_task else None,
                "polling_strategy": metadata.get("polling_strategy"),
                "database_tables": metadata.get("database_tables"),
                "notes": notes or None,
            }
        )

    return matrix


def _summarize_input_source_matrix(matrix: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(matrix), "connected": 0, "data_only": 0, "waiting": 0}
    for item in matrix:
        status = str(item.get("task_log_status") or "")
        if status in summary:
            summary[status] += 1
    return summary
