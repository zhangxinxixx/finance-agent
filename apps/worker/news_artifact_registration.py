"""Explicit news producer manifests shared by worker and Dagster paths."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from apps.runtime.state_machine import transition_task_step
from apps.worker.artifact_registration import coerce_lineage_source_refs, coerce_lineage_input_snapshot_ids
from database.models.task import TaskStep, StepStatus

STAGE_KEYS = {
    "news_collect": {"collection_diagnostics"},
    "news_feature": {
        "event_candidates",
        "impact_assessments",
        "daily_analysis_triggers",
        "market_reactions",
        "official_events",
        "gold_event_mainlines",
        "report_events",
        "etf_holdings",
    },
    "news_brief": {
        "daily_market_brief",
        "gold_macro_overview",
        "source_health",
        "quality_gate_result",
        "daily_brief_input_snapshot",
        "daily_brief_json",
        "daily_brief_markdown",
    },
}


def build_news_artifact_refs(*, step_name, paths, storage_root, run_id):
    root = Path(storage_root).resolve()
    refs = []
    for name, relative in sorted(paths.items()):
        if name not in STAGE_KEYS[step_name] and not (step_name == "news_brief" and name.startswith("agent:")):
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("news_artifact_path_invalid")
        target = root / path
        resolved = target.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("news_artifact_path_escape") from None
        if target.is_symlink() or any(
            parent.is_symlink() for parent in target.parents if parent != root and root in parent.parents
        ):
            raise ValueError("news_artifact_path_escape")
        if path.parts[0] not in {"features", "analysis", "outputs"}:
            raise ValueError("news_artifact_layer_invalid")
        stat = resolved.stat()
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        refs.append(
            {
                "artifact_id": f"{run_id}:{name}",
                "artifact_type": "analysis_md"
                if path.suffix == ".md"
                else "feature_json"
                if path.parts[0] == "features"
                else "structured_json",
                "file_path": str(Path(storage_root) / path),
                "sha256": digest.hexdigest(),
                "byte_size": stat.st_size,
                "content_type": "text/markdown" if path.suffix == ".md" else "application/json",
            }
        )
    return refs


def persist_dagster_news_summary(db, *, run_id, summary, storage_root):
    """Bind real producer files to an existing lifecycle step; caller commits."""
    run_uuid = uuid.UUID(str(run_id))
    step = db.query(TaskStep).filter(TaskStep.task_run_id == run_uuid, TaskStep.name == summary["step"]).one_or_none()
    if step is None:
        raise ValueError("news_artifact_task_step_missing")
    rows = register_step_artifacts(
        db,
        run_id=str(run_uuid),
        step=step,
        artifact_refs=summary.get("artifact_refs"),
        source_refs=coerce_lineage_source_refs(summary.get("source_refs")),
        input_snapshot_ids=coerce_lineage_input_snapshot_ids(summary.get("input_snapshot_ids")),
        storage=LocalFileSystemArtifactStorage(root=Path(storage_root)),
    )
    from apps.data_layer.collection_ingestion import ingest_news_artifacts

    warehouse = ingest_news_artifacts(db, rows, storage_root=Path(storage_root), run_id=str(run_uuid))
    if warehouse:
        summary["warehouse"] = warehouse
    step.output_json = json.dumps(summary, ensure_ascii=False, default=str)
    step.artifact_refs = json.dumps(summary.get("artifact_refs") or [], ensure_ascii=False)
    transition_task_step(db, step, StepStatus.success, source="dagster", reason="news_producer_artifacts_registered")
    db.flush()
    return rows
