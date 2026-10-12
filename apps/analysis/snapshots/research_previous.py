"""Resolve a completed research comparison, never a formal Gold predecessor."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from apps.runtime.premarket_snapshot_authority import _resolve_exact_run_authority
from database.models.analysis import AnalysisSnapshot
from database.models.task import TaskRun, TaskStatus


def load_previous_research(db, *, storage_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Use strictly older DB identity plus existing file/hash authority checks.

    Multiple successful reports on a date are valid research comparisons. The
    most recent completed snapshot wins; tied timestamps fail closed. This
    neither updates nor supplies the canonical Gold state predecessor.
    """
    cutoff = datetime.fromisoformat(snapshot["snapshot_time"].replace("Z", "+00:00"))
    rows = list(db.scalars(select(AnalysisSnapshot).where(
        AnalysisSnapshot.asset == snapshot["asset"],
        AnalysisSnapshot.status == "success",
        AnalysisSnapshot.snapshot_time < cutoff,
        AnalysisSnapshot.snapshot_time >= cutoff - timedelta(days=14),
        AnalysisSnapshot.run_id != snapshot["run_id"],
    ).order_by(AnalysisSnapshot.snapshot_time.desc()).limit(100)).all())
    eligible = []
    for row in rows:
        try:
            run_id = uuid.UUID(row.run_id)
        except ValueError:
            continue
        run = db.scalar(select(TaskRun).where(TaskRun.id == run_id))
        if run and run.status == TaskStatus.success and run.name == run.task_type == "premarket" and row.payload.get("daily_research"):
            eligible.append((row, run))
    if not eligible:
        return {"status": "unavailable", "reason": "no_completed_research_within_14d"}
    row, run = eligible[0]
    if len(eligible) > 1 and eligible[1][0].snapshot_time == row.snapshot_time:
        return {"status": "unavailable", "reason": "ambiguous_previous_research_time"}
    authority = _resolve_exact_run_authority(
        db, run=run, storage_root=storage_root, trade_date=str(row.trade_date),
        parsed_date=row.trade_date, asset=snapshot["asset"], found_reason="research_comparison_verified",
        research_comparison=True,
    )
    if authority.status != "found":
        return {"status": "unavailable", "reason": authority.reason_code}
    previous = json.loads(authority.snapshot_path.read_text(encoding="utf-8"))
    from apps.features.research.workflow import report_comparison_rows

    return {
        "status": "verified", "snapshot_id": previous["snapshot_id"],
        "run_id": previous["run_id"], "snapshot_time": previous["snapshot_time"],
        "passport": previous["daily_research"]["passport"],
        "comparison_rows": report_comparison_rows(previous['daily_research'], as_of=previous['snapshot_time']),
        "key_levels": previous.get("gold_workflow", {}).get("key_levels", []),
        "execution_zones": previous.get('gold_workflow', {}).get('execution_zones', {}).get('zones', []),
        "research_state": previous.get("gold_workflow", {}).get("state", {}),
        "source_refs": [{"source": "previous_research_snapshot", "artifact_ref": str(authority.snapshot_path.resolve().relative_to(storage_root.resolve())),
                         "sha256": authority.file_sha256, "snapshot_id": previous["snapshot_id"]}],
        "formal_state_authority": False,
    }
