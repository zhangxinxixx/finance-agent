from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

logger = logging.getLogger(__name__)

_ARTIFACT_FILENAME = "jin10_web_flash_briefs.json"
_WRAPPER_KEY = "jin10_web_flash_briefs"


def get_jin10_web_flash_briefs_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "features" / "news"
    if not base.exists():
        return None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            artifact_path = run_dir / _ARTIFACT_FILENAME
            if artifact_path.exists():
                return _load_web_flash_briefs(
                    date=date_dir.name, run_id=run_dir.name, path=artifact_path, project_root=root
                )
    return None


def get_jin10_web_flash_briefs(
    *, date: str, run_id: str, project_root: Path | None = None
) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    artifact_path = root / "storage" / "features" / "news" / date / run_id / _ARTIFACT_FILENAME
    if not artifact_path.exists():
        return None
    return _load_web_flash_briefs(date=date, run_id=run_id, path=artifact_path, project_root=root)


def _load_web_flash_briefs(
    *, date: str, run_id: str, path: Path, project_root: Path
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(
            "Failed to load Jin10 web flash briefs artifact",
            exc_info=True,
            extra={"path": str(path)},
        )
        return None
    if not isinstance(payload, dict):
        return None

    inner = payload.get(_WRAPPER_KEY)
    if not isinstance(inner, dict):
        return None

    briefs = inner.get("briefs")
    normalized_briefs = [dict(item) for item in briefs if isinstance(item, dict)] if isinstance(briefs, list) else []
    brief_count = _coerce_brief_count(inner.get("brief_count"), default=len(normalized_briefs))
    if brief_count is None:
        return None

    inner_status = inner.get("status")
    status = inner_status if isinstance(inner_status, str) and inner_status else ("available" if normalized_briefs else "empty")

    return {
        "status": status,
        "date": date,
        "run_id": run_id,
        "retrieved_date": payload.get("retrieved_date"),
        "artifact_path": path.relative_to(project_root).as_posix(),
        "as_of": inner.get("as_of"),
        "rule_version": inner.get("rule_version"),
        "brief_count": brief_count,
        "briefs": normalized_briefs,
        "data_quality": dict(inner.get("data_quality")) if isinstance(inner.get("data_quality"), dict) else {},
        "source_refs": list(inner.get("source_refs")) if isinstance(inner.get("source_refs"), list) else [],
        "artifact_refs": list(inner.get("artifact_refs")) if isinstance(inner.get("artifact_refs"), list) else [],
        "quality_flags": dict(inner.get("quality_flags")) if isinstance(inner.get("quality_flags"), dict) else {},
    }


def _coerce_brief_count(value: Any, *, default: int) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
