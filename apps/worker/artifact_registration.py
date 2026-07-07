from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.runtime.artifact_registry import register_step_artifacts

_ARTIFACT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".json": "application/json",
    ".html": "text/html",
    ".pdf": "application/pdf",
}


def register_runner_step_artifacts(
    db: DBSession,
    *,
    run_id: str,
    step: Any,
    summary: dict[str, object] | None,
) -> None:
    if not isinstance(summary, dict) and not step.output_ref:
        return
    output_refs = summary.get("output_refs") if isinstance(summary, dict) else None
    artifact_refs = summary.get("artifact_refs") if isinstance(summary, dict) else None
    register_step_artifacts(
        db,
        run_id=run_id,
        step=step,
        output_refs=output_refs if isinstance(output_refs, list) else None,
        artifact_refs=artifact_refs if isinstance(artifact_refs, list) else None,
        output_ref=step.output_ref,
        source_refs=coerce_lineage_source_refs(summary.get("source_refs")) if isinstance(summary, dict) else None,
        input_snapshot_ids=coerce_lineage_input_snapshot_ids(summary.get("input_snapshot_ids"))
        if isinstance(summary, dict)
        else None,
    )


def register_composite_output_artifacts(
    db: DBSession,
    *,
    run_id: str,
    steps: list[Any],
    composite_outputs: dict[str, Any],
    analysis_snapshot: dict[str, Any] | None = None,
) -> None:
    report_step = next((step for step in steps if step.name == "report_render"), None)
    if report_step is None:
        return

    report_result = composite_outputs.get("report_result") if isinstance(composite_outputs, dict) else None
    card_result = composite_outputs.get("card_result") if isinstance(composite_outputs, dict) else None
    card = composite_outputs.get("strategy_card") if isinstance(composite_outputs, dict) else None

    artifacts: list[dict[str, Any]] = []
    if isinstance(report_result, dict):
        report_paths = report_result.get("paths")
        if isinstance(report_paths, list):
            for index, path in enumerate(report_paths):
                if not isinstance(path, str):
                    continue
                artifacts.append(
                    enrich_runner_artifact_metadata(
                        {
                            "artifact_id": f"{run_id}:final_report:{index}",
                            "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                            "file_path": path,
                        }
                    )
                )
    if isinstance(card_result, dict):
        card_paths = card_result.get("paths")
        if isinstance(card_paths, list):
            for index, path in enumerate(card_paths):
                if not isinstance(path, str):
                    continue
                artifacts.append(
                    enrich_runner_artifact_metadata(
                        {
                            "artifact_id": f"{run_id}:strategy_card:{index}",
                            "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                            "file_path": path,
                        }
                    )
                )
    if not artifacts:
        return

    source_refs = merge_lineage_source_refs(
        analysis_snapshot.get("source_refs") if isinstance(analysis_snapshot, dict) else None,
        list(getattr(card, "source_refs", []) or []) if card is not None else None,
    )
    input_snapshot_ids = merge_lineage_input_snapshot_ids(
        analysis_snapshot.get("input_snapshot_ids") if isinstance(analysis_snapshot, dict) else None,
        dict(getattr(card, "input_snapshot_ids", {}) or {}) if card is not None else None,
    )

    register_step_artifacts(
        db,
        run_id=run_id,
        step=report_step,
        output_refs=artifacts,
        artifact_refs=None,
        output_ref=None,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )


def register_run_support_artifacts(
    db: DBSession,
    *,
    run_id: str,
    steps: list[Any],
    artifacts: list[dict[str, Any]],
    source_refs: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
) -> None:
    """Register run support files without introducing a separate storage backend."""
    if not artifacts:
        return
    enriched_artifacts = [enrich_runner_artifact_metadata(artifact) for artifact in artifacts]
    step = next((item for item in steps if item.name == "report_render"), None)
    if step is None and steps:
        step = steps[-1]
    if step is None:
        return
    register_step_artifacts(
        db,
        run_id=run_id,
        step=step,
        output_refs=enriched_artifacts,
        artifact_refs=None,
        output_ref=None,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )


def enrich_runner_artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(artifact)
    file_path = enriched.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return enriched

    path = Path(file_path)
    try:
        stat_result = path.stat()
    except OSError:
        return enriched

    suffix = path.suffix.lower()
    enriched.setdefault("content_type", _ARTIFACT_CONTENT_TYPES.get(suffix, "application/octet-stream"))
    enriched.setdefault("byte_size", stat_result.st_size)
    enriched.setdefault("generated_at", datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat())
    return enriched


def coerce_lineage_source_refs(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        identity = _first_lineage_ref_value(normalized, ("source_ref", "source_id", "source_name", "source", "source_key"))
        trace_detail = _first_lineage_ref_value(
            normalized,
            (
                "article_id",
                "captured_at",
                "data_date",
                "endpoint",
                "file_path",
                "raw_path",
                "ref",
                "report_date",
                "sha256",
                "snapshot_id",
                "source_ref",
                "source_type",
                "source_url",
                "status",
                "symbol",
                "url",
            ),
        )
        if identity is not None and trace_detail is None:
            normalized["source_ref"] = identity
        dedupe_key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        refs.append(normalized)
    return refs or None


def coerce_lineage_input_snapshot_ids(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    normalized = {str(key): value for key, value in raw.items() if str(key)}
    return normalized or None


def merge_lineage_source_refs(*raw_groups: Any) -> list[dict[str, Any]] | None:
    merged: list[dict[str, Any]] = []
    for raw in raw_groups:
        refs = coerce_lineage_source_refs(raw)
        if refs:
            merged.extend(refs)
    return coerce_lineage_source_refs(merged)


def merge_lineage_input_snapshot_ids(*raw_payloads: Any) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for raw in raw_payloads:
        payload = coerce_lineage_input_snapshot_ids(raw)
        if payload:
            merged.update(payload)
    return merged or None


def _first_lineage_ref_value(ref: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = ref.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None
