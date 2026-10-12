from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT, _latest_date_dir, _latest_run_file, _try_db_session
from apps.api.services.dashboard_research_service import get_dashboard_research_context
from database.queries.feature_snapshots import list_feature_snapshots
from database.numeric_source_policy import quarantine_numeric_payload


def get_macro_latest() -> dict[str, Any] | None:
    # A newer registered research report can exist without a legacy
    # FeatureSnapshot row. Keep macro pages on the same verified facts as it.
    research = get_dashboard_research_context()
    if research is not None:
        if (research.get("facts_status", research.get("status")) != "available"
                or not isinstance(research.get("macro"), dict)):
            return None
        return quarantine_numeric_payload({**research["macro"], "run_id": research["run_id"],
                "snapshot_id": research["snapshot_id"], "source": "registered_research_snapshot",
                "trade_date": research.get("trade_date"),
                "facts_status": "available", "research_status": research["status"],
                "source_refs": research["macro"].get("source_refs") or research.get("source_refs", [])})
    db_payload = _get_macro_latest_from_db()
    if db_payload is not None:
        return quarantine_numeric_payload(db_payload)

    date_dir = _latest_date_dir(_PROJECT_ROOT / "storage" / "features" / "macro")
    if date_dir is None:
        return None
    path = _latest_run_file(date_dir, "macro_snapshot.json")
    if path is None:
        return None
    return quarantine_numeric_payload(json.loads(path.read_text(encoding="utf-8")))


def get_market_macro_latest() -> dict[str, Any] | None:
    """Return the latest verified macro feature snapshot for market views.

    The report-facing ``get_macro_latest`` intentionally fails closed when a
    newer registered research report is invalid.  The market monitor needs a
    separate deterministic read model so a newly collected macro snapshot can
    be shown before a full research report is accepted.  It therefore reads
    only a registered ``FeatureSnapshot`` and verifies its identity, artifact
    location, bytes, and payload hash before returning it.

    An invalid newest row is not replaced by an older row.  This preserves the
    freshness and lineage boundary for the live page.
    """
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

            row = rows[0]
            if row.status not in {"success", "partial", "generated"}:
                return None

            expected_snapshot_id = (
                f"feature:macro:macro_snapshot:{row.trade_date.isoformat()}:{row.run_id}"
            )
            if row.snapshot_id != expected_snapshot_id:
                return None

            payload = dict(row.payload or {})
            if not isinstance(payload.get("indicators"), dict):
                return None
            if not row.payload_sha256 or payload.get("as_of") != row.trade_date.isoformat():
                return None

            artifact_value = str(row.artifact_path or "").strip()
            if not artifact_value:
                return None
            artifact = Path(artifact_value)
            if not artifact.is_absolute():
                artifact = _PROJECT_ROOT / artifact
            storage_root = (_PROJECT_ROOT / "storage").resolve()
            artifact = artifact.resolve(strict=True)
            if not artifact.is_relative_to(storage_root):
                return None

            persisted_payload = json.loads(artifact.read_text(encoding="utf-8"))
            if not isinstance(persisted_payload, dict) or persisted_payload != payload:
                return None
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if digest != row.payload_sha256:
                return None

            result = dict(payload)
            result.update(
                {
                    "source": "registered_macro_feature_snapshot",
                    "status": row.status,
                    "trade_date": row.trade_date.isoformat(),
                    "run_id": row.run_id,
                    "snapshot_id": row.snapshot_id,
                    "artifact_path": str(artifact),
                    "source_refs": list(row.source_refs or []),
                }
            )
            return quarantine_numeric_payload(result)
    except Exception:
        return None


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
