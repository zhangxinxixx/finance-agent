from __future__ import annotations

import json
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT, _latest_date_dir, _latest_run_file


def get_macro_latest() -> dict[str, Any] | None:
    date_dir = _latest_date_dir(_PROJECT_ROOT / "storage" / "features" / "macro")
    if date_dir is None:
        return None
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_macro_report_md(date_str: str | None = None) -> str | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "macro"
    date_dir = _latest_date_dir(base) if date_str is None else base / date_str
    if date_dir is None:
        return None
    path = _latest_run_file(date_dir, "macro_snapshot.md")
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
