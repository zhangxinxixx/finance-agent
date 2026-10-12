"""Jin10 page report models backed only by derived output artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.features.news.report_quality import report_quality_input_id


def load_page_jin10_quality(*, project_root: Path, date: str, run_id: str,
                           agent_payload: dict, daily_payload: dict) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        return {}
    base = project_root / "storage" / "features" / "jin10_report_quality" / date / run_id
    identity = report_quality_input_id(agent_payload, daily_payload)
    paths = sorted(base.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for path in paths[:100]:
        if not path.resolve().is_relative_to((project_root / "storage" / "features").resolve()):
            continue
        payload = _read_json(path) or {}
        if payload.get("input_id") == identity:
            return payload
    return {}


def get_page_jin10_report(
    *, report_type: str, date: str, run_id: str, project_root: Path | None = None
) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "outputs" / "jin10" / date / run_id
    if (
        not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id)
        or not base.resolve().is_relative_to((root / "storage" / "outputs" / "jin10").resolve())
    ):
        return _unavailable(report_type, date=date, run_id=run_id)
    daily = _read_json(base / "daily_analysis.json")
    agent = _read_json(base / "agent_analysis_report.json")
    actual_type = _report_type(daily)
    if actual_type != report_type:
        return _unavailable(report_type, date=date, run_id=run_id)

    preferred = (
        ((base / "daily_analysis.html", "html"), (base / "agent_analysis_report.md", "markdown"))
        if report_type == "daily"
        else ((base / "agent_analysis_report.md", "markdown"), (base / "daily_analysis.html", "html"))
    )
    selected = next(((path, kind) for path, kind in preferred if path.is_file()), None)
    if selected is None:
        return _unavailable(report_type, date=date, run_id=run_id)
    path, kind = selected
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return _unavailable(report_type, date=date, run_id=run_id)
    if not content.strip():
        return _unavailable(report_type, date=date, run_id=run_id)

    metadata = agent or daily or {}
    quality = (agent or {}).get("quality_audit") or (daily or {}).get("quality_audit")
    saved_quality = load_page_jin10_quality(
        project_root=root, date=date, run_id=run_id, agent_payload=agent or {}, daily_payload=daily or {},
    )
    quality = saved_quality.get("quality_audit") or quality
    from apps.api.services.report_service import _jin10_quality_blocks_content

    if _jin10_quality_blocks_content(quality):
        result = _unavailable(report_type, date=date, run_id=run_id)
        result.update(reason="report_quality_blocked", quality_audit=quality)
        return result
    return {
        "status": "available",
        "article_id": metadata.get("article_id") or run_id,
        "run_id": run_id,
        "date": date,
        "trade_date": date,
        "title": metadata.get("title"),
        "report_type": report_type,
        "family": (daily or {}).get("family"),
        "source_url": (agent or {}).get("source_url") or (daily or {}).get("source_url"),
        "content": content,
        "format": kind,
        "asset_base_url": f"/api/jin10/report-bundle/{date}/{run_id}/asset/",
        "quality_audit": quality,
        "page_layer": "ADS",
    }


def get_page_jin10_report_latest(
    *, report_type: str, project_root: Path | None = None
) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "outputs" / "jin10"
    if base.is_dir():
        for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
            for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
                result = get_page_jin10_report(
                    report_type=report_type,
                    date=date_dir.name,
                    run_id=run_dir.name,
                    project_root=root,
                )
                if result.get("status") == "available":
                    return result
    return _unavailable(report_type)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _report_type(daily: dict[str, Any] | None) -> str | None:
    if not daily:
        return None
    report_type = str(daily.get("report_type") or "").strip().lower()
    family = str(daily.get("family") or "").strip()
    if report_type == "daily" or (not report_type and family == "jin10_daily_visual"):
        from apps.api.services.report_service import _is_jin10_daily_storage_payload

        if not _is_jin10_daily_storage_payload(daily):
            return None
    if report_type in {"daily", "weekly"}:
        return report_type
    if family == "jin10_daily_visual":
        return "daily"
    if family == "jin10_weekly_visual":
        return "weekly"
    return None


def _unavailable(report_type: str, *, date: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": f"dws_jin10_{report_type}_report_unavailable",
        "report_type": report_type,
        "date": date,
        "run_id": run_id,
        "content": None,
        "page_layer": "ADS",
    }
