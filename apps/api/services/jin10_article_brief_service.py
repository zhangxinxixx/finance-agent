from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

logger = logging.getLogger(__name__)

_ARTIFACT_FILENAME = "jin10_article_briefs.json"


def get_jin10_article_briefs_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "features" / "news"
    if not base.exists():
        return None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            artifact_path = run_dir / _ARTIFACT_FILENAME
            if artifact_path.exists():
                return _load_article_briefs(date=date_dir.name, run_id=run_dir.name, path=artifact_path, project_root=root)
    return None


def get_jin10_article_briefs(*, date: str, run_id: str, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    artifact_path = root / "storage" / "features" / "news" / date / run_id / _ARTIFACT_FILENAME
    if not artifact_path.exists():
        return None
    return _load_article_briefs(date=date, run_id=run_id, path=artifact_path, project_root=root)


def _load_article_briefs(*, date: str, run_id: str, path: Path, project_root: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load Jin10 article briefs artifact", exc_info=True, extra={"path": str(path)})
        return None
    if not isinstance(payload, dict):
        return None

    briefs = payload.get("briefs")
    data_quality = payload.get("data_quality")
    normalized_briefs = [dict(item) for item in briefs if isinstance(item, dict)] if isinstance(briefs, list) else []
    normalized_quality = dict(data_quality) if isinstance(data_quality, dict) else {}
    brief_count = int(payload.get("brief_count") or len(normalized_briefs))

    return {
        "status": "available" if normalized_briefs else "empty",
        "date": date,
        "run_id": run_id,
        "artifact_path": path.relative_to(project_root).as_posix(),
        "as_of": payload.get("as_of"),
        "rule_version": payload.get("rule_version"),
        "brief_count": brief_count,
        "display_bucket_counts": normalized_quality.get("display_bucket_counts", {}),
        "article_class_counts": normalized_quality.get("article_class_counts", {}),
        "access_status_counts": normalized_quality.get("access_status_counts", {}),
        "briefs": normalized_briefs,
        "data_quality": normalized_quality,
    }
