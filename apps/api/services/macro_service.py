from __future__ import annotations

import json
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT, _latest_date_dir, _latest_run_file, _try_db_session
from database.queries.feature_snapshots import list_feature_snapshots


def get_macro_latest() -> dict[str, Any] | None:
    db_payload = _get_macro_latest_from_db()
    if db_payload is not None:
        return db_payload

    date_dir = _latest_date_dir(_PROJECT_ROOT / "storage" / "features" / "macro")
    if date_dir is None:
        return None
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _get_macro_latest_from_db() -> dict[str, Any] | None:
    try:
        session = _try_db_session()
    except Exception:
        return None
    if session is None:
        return None

    try:
        with session:
            rows = list_feature_snapshots(
                session,
                domain="macro",
                snapshot_kind="macro_snapshot",
                asset="XAUUSD",
            )
            if not rows:
                return None
            return dict(rows[0].payload)
    except Exception:
        return None


def get_macro_report_md(date_str: str | None = None) -> str | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "macro"
    date_dir = _latest_date_dir(base) if date_str is None else base / date_str
    if date_dir is None:
        return None
    path = _latest_run_file(date_dir, "macro_full_report.md") or _latest_run_file(date_dir, "macro_snapshot.md")
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
