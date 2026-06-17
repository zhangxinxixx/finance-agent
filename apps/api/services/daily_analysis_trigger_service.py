from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

logger = logging.getLogger(__name__)

_ARTIFACT_FILENAME = "daily_analysis_triggers.json"


def get_daily_analysis_triggers_latest(*, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "features" / "news"
    if not base.exists():
        return None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            artifact_path = run_dir / _ARTIFACT_FILENAME
            if artifact_path.exists():
                return _load_daily_analysis_triggers(
                    date=date_dir.name,
                    run_id=run_dir.name,
                    path=artifact_path,
                    project_root=root,
                )
    return None


def get_daily_analysis_triggers(*, date: str, run_id: str, project_root: Path | None = None) -> dict[str, Any] | None:
    root = project_root or _PROJECT_ROOT
    artifact_path = root / "storage" / "features" / "news" / date / run_id / _ARTIFACT_FILENAME
    if not artifact_path.exists():
        return None
    return _load_daily_analysis_triggers(date=date, run_id=run_id, path=artifact_path, project_root=root)


def _load_daily_analysis_triggers(*, date: str, run_id: str, path: Path, project_root: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load daily analysis triggers artifact", exc_info=True, extra={"path": str(path)})
        return None
    if not isinstance(payload, dict):
        return None

    triggers = payload.get("triggers")
    data_quality = payload.get("data_quality")
    normalized_triggers = [dict(item) for item in triggers if isinstance(item, dict)] if isinstance(triggers, list) else []
    normalized_quality = dict(data_quality) if isinstance(data_quality, dict) else {}
    trigger_count = int(payload.get("trigger_count") or len(normalized_triggers))

    priority_counts: dict[str, int] = {}
    source_key_counts: dict[str, int] = {}
    for trigger in normalized_triggers:
        priority = str(trigger.get("priority") or "").strip()
        source_key = str(trigger.get("source_key") or "").strip()
        if priority:
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        if source_key:
            source_key_counts[source_key] = source_key_counts.get(source_key, 0) + 1

    return {
        "status": "available" if normalized_triggers else "empty",
        "date": date,
        "run_id": run_id,
        "artifact_path": path.relative_to(project_root).as_posix(),
        "as_of": payload.get("as_of"),
        "rule_version": payload.get("rule_version"),
        "trigger_count": trigger_count,
        "priority_counts": priority_counts,
        "source_key_counts": source_key_counts,
        "triggers": normalized_triggers,
        "data_quality": normalized_quality,
    }
