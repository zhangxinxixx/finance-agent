from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

logger = logging.getLogger(__name__)

_ARTIFACT_FILENAME = "daily_brief.json"
_MARKDOWN_FILENAME = "daily_brief.md"


def get_daily_brief_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "outputs" / "daily_brief"
    if not base.exists():
        return None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            artifact_path = run_dir / _ARTIFACT_FILENAME
            if artifact_path.exists():
                return _load_daily_brief(
                    date=date_dir.name,
                    run_id=run_dir.name,
                    path=artifact_path,
                    project_root=root,
                )
    return None


def get_daily_brief(*, date: str, run_id: str, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    artifact_path = root / "storage" / "outputs" / "daily_brief" / date / run_id / _ARTIFACT_FILENAME
    if not artifact_path.exists():
        return None
    return _load_daily_brief(date=date, run_id=run_id, path=artifact_path, project_root=root)


def _load_daily_brief(*, date: str, run_id: str, path: Path, project_root: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load daily brief artifact", exc_info=True, extra={"path": str(path)})
        return None
    if not isinstance(payload, dict):
        return None

    markdown_path = path.with_name(_MARKDOWN_FILENAME)
    markdown = str(payload.get("markdown") or "")
    if not markdown and markdown_path.exists():
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to load daily brief markdown", exc_info=True, extra={"path": str(markdown_path)})

    structured = payload.get("structured")
    source_refs = payload.get("source_refs")
    quality_flags = payload.get("quality_flags")
    status = str(payload.get("status") or ("available" if markdown else "partial"))

    return {
        "status": status,
        "date": payload.get("date") or date,
        "run_id": payload.get("run_id") or run_id,
        "report_mode": payload.get("report_mode"),
        "artifact_path": payload.get("artifact_path") or markdown_path.relative_to(project_root).as_posix(),
        "json_path": path.relative_to(project_root).as_posix(),
        "input_snapshot_path": payload.get("input_snapshot_path"),
        "markdown": markdown,
        "structured": dict(structured) if isinstance(structured, dict) else {},
        "source_refs": [dict(item) for item in source_refs if isinstance(item, dict)] if isinstance(source_refs, list) else [],
        "quality_flags": [str(item) for item in quality_flags] if isinstance(quality_flags, list) else [],
    }
