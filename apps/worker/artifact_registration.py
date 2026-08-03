from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from apps.runtime.artifact_registry import register_artifact, register_step_artifacts
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from apps.output.context_bundle import load_context_bundle
from database.models.execution import RunArtifact

logger = logging.getLogger(__name__)

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
    storage_root: Path | None = None,
) -> None:
    report_step = next((step for step in steps if step.name == "report_render"), None)
    if report_step is None:
        return

    bundle_descriptor = composite_outputs.get("context_bundle_registry_artifact")
    if isinstance(bundle_descriptor, dict):
        try:
            transaction = db.begin_nested() if callable(getattr(db, "begin_nested", None)) else nullcontext()
            with transaction:
                row = register_context_bundle_artifact(
                    db,
                    run_id=run_id,
                    step=report_step,
                    descriptor=bundle_descriptor,
                    storage_root=storage_root,
                )
            composite_outputs["context_bundle_registry_status"] = {
                "status": "registered" if row is not None else "skipped_unavailable",
                "bundle_id": (bundle_descriptor.get("metadata") or {}).get("bundle_id"),
            }
        except Exception as exc:
            logger.exception("ContextBundle registry failed; continuing legacy report/card registration")
            composite_outputs["context_bundle_registry_status"] = {
                "status": "failed",
                "bundle_id": (bundle_descriptor.get("metadata") or {}).get("bundle_id"),
                "reason": f"{type(exc).__name__}:{str(exc)[:200]}",
            }

    report_result = composite_outputs.get("report_result") if isinstance(composite_outputs, dict) else None
    card_result = composite_outputs.get("card_result") if isinstance(composite_outputs, dict) else None
    card = composite_outputs.get("strategy_card") if isinstance(composite_outputs, dict) else None
    report_agent_result = (
        composite_outputs.get("report_render_agent_result") if isinstance(composite_outputs, dict) else None
    )
    agent_loop_decision = composite_outputs.get("agent_loop_decision") if isinstance(composite_outputs, dict) else None
    publish_allowed = bool(getattr(agent_loop_decision, "publish_allowed", False))
    output_mode = "accepted" if publish_allowed else "observe"
    report_artifact_label = "final_report" if publish_allowed else "observation_report"
    card_artifact_label = "strategy_card" if publish_allowed else "observation_strategy_card"

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
                            "artifact_id": f"{run_id}:{report_artifact_label}:{index}",
                            "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                            "file_path": path,
                            "publish_allowed": publish_allowed,
                            "output_mode": output_mode,
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
                            "artifact_id": f"{run_id}:{card_artifact_label}:{index}",
                            "artifact_type": "analysis_md" if path.endswith(".md") else "structured_json",
                            "file_path": path,
                            "publish_allowed": publish_allowed,
                            "output_mode": output_mode,
                        }
                    )
                )
    report_agent_path = getattr(report_agent_result, "target_path", None)
    if isinstance(report_agent_path, str) and report_agent_path:
        artifacts.append(
            enrich_runner_artifact_metadata(
                {
                    "artifact_id": f"{run_id}:report_render_agent",
                    "artifact_type": "structured_json",
                    "file_path": report_agent_path,
                    "execution_mode": "agent_artifact",
                    "publish_allowed": publish_allowed,
                    "output_mode": output_mode,
                }
            )
        )
    gold_policy_execution_mode = composite_outputs.get("gold_policy_execution_mode") if isinstance(composite_outputs, dict) else None
    gold_policy_paths = composite_outputs.get("gold_policy_artifact_paths") if isinstance(composite_outputs, dict) else None
    if gold_policy_execution_mode == "shadow" and isinstance(gold_policy_paths, dict):
        for filename in sorted(gold_policy_paths):
            if not (
                filename in {"feature_snapshot.v1.json", "feature_snapshot.v2.json"}
                or filename
                in {
                    "gold_analysis_decision.v1.json",
                    "gold_analysis_decision.v2.json",
                    "gold_price_attribution.v1.json",
                    "gold_price_attribution.v2.json",
                }
            ):
                continue
            artifact_type = (
                "feature_json"
                if filename.startswith("feature_snapshot.")
                else "structured_json"
            )
            path = gold_policy_paths.get(filename)
            if not isinstance(path, str) or not path:
                continue
            artifacts.append(
                enrich_runner_artifact_metadata(
                    {
                        "artifact_id": f"{run_id}:gold_policy_shadow:{filename}",
                        "artifact_type": artifact_type,
                        "file_path": path,
                        "publish_allowed": False,
                        "output_mode": "observe",
                        "execution_mode": "shadow",
                        "gold_policy_execution_mode": "shadow",
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
        _gold_policy_input_snapshot_ids(composite_outputs),
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


def register_context_bundle_artifact(
    db: DBSession,
    *,
    run_id: str,
    step: Any,
    descriptor: dict[str, Any],
    storage_root: Path | None = None,
    allow_canary_recompute: bool = False,
) -> RunArtifact | None:
    """Register one immutable Bundle plus one explicit canary supersession.

    This writer is deliberately run-scoped.  Cross-run recovery must use the
    read selectors in ``apps.runtime.artifact_registry`` instead of guessing a
    registry row here.
    """

    if str(getattr(step, "task_run_id", "")) != str(run_id):
        raise ValueError("context bundle registry run_id does not match step.task_run_id")

    try:
        bind = db.connection()
    except Exception:
        return None
    if not inspect(bind).has_table("run_artifacts"):
        return None

    metadata = descriptor.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("artifact_family") != "analysis_context_bundle":
        raise ValueError("context bundle registry descriptor has invalid metadata")
    required = {
        "bundle_id": str(descriptor.get("artifact_id") or "").strip(),
        "content_hash": str(metadata.get("content_hash") or "").strip(),
        "run_id": str(metadata.get("run_id") or "").strip(),
        "canonical_state_id": str(metadata.get("canonical_state_id") or "").strip(),
        "schema_version": str(metadata.get("schema_version") or "").strip(),
        "asset": str(metadata.get("asset") or "").strip(),
        "state_scope": str(metadata.get("state_scope") or "").strip(),
    }
    if (
        any(not value for value in required.values())
        or required["run_id"] != run_id
        or not _is_lowercase_sha256(required["content_hash"])
    ):
        raise ValueError("context bundle registry descriptor identity is incomplete")
    if required["schema_version"] != "analysis_context_bundle.v3":
        raise ValueError("context bundle registry descriptor schema version is unsupported")
    if str(descriptor.get("artifact_type") or "") != "structured_json":
        raise ValueError("context bundle registry descriptor artifact type is invalid")
    file_path = str(descriptor.get("file_path") or "").strip()
    file_sha256 = str(descriptor.get("sha256") or "").strip()
    if not file_path or not _is_lowercase_sha256(file_sha256):
        raise ValueError("context bundle registry descriptor file identity is incomplete")
    storage = LocalFileSystemArtifactStorage(root=Path(storage_root).resolve()) if storage_root else None
    effective_storage = storage or LocalFileSystemArtifactStorage()
    actual_file_sha256 = effective_storage.compute_sha256(file_path)
    if actual_file_sha256 is None:
        raise ValueError("context bundle registry artifact file does not exist")
    if actual_file_sha256 != file_sha256:
        raise ValueError("context bundle registry descriptor sha256 does not match file")
    bundle = load_context_bundle(
        storage_root=storage_root or effective_storage.root,
        storage_relative_path=file_path,
    )
    if (
        bundle.schema_version != required["schema_version"]
        or bundle.bundle_id != required["bundle_id"]
        or bundle.content_hash != required["content_hash"]
        or bundle.run_id != required["run_id"]
        or bundle.asset != required["asset"]
        or bundle.state_scope != required["state_scope"]
        or bundle.canonical_state_id != required["canonical_state_id"]
    ):
        raise ValueError("context bundle registry descriptor payload identity conflicts")

    is_recompute = metadata.get("artifact_role") == "canary_recompute"
    if is_recompute and not allow_canary_recompute:
        raise ValueError("canary recompute Bundle requires explicit registry authority")
    if allow_canary_recompute and not is_recompute:
        raise ValueError("explicit canary recompute registration requires canary_recompute role")
    registry_identity = (
        f"finance-agent:run-context-bundle:{run_id}:canary-recompute:1"
        if is_recompute
        else f"finance-agent:run-context-bundle:{run_id}"
    )
    registry_row_id = uuid.uuid5(uuid.NAMESPACE_URL, registry_identity)
    existing_rows = db.query(RunArtifact).filter(RunArtifact.run_id == step.task_run_id).all()
    existing = [
        row
        for row in existing_rows
        if isinstance(row.artifact_metadata, dict)
        and row.artifact_metadata.get("artifact_family") == "analysis_context_bundle"
    ]
    matching = [
        row
        for row in existing
        if str((row.artifact_metadata or {}).get("bundle_id") or "") == required["bundle_id"]
    ]
    if len(matching) > 1:
        raise ValueError("TaskRun has duplicate ContextBundle registry identities")
    if matching:
        return _validate_registered_context_bundle_row(
            matching[0],
            registry_row_id=registry_row_id,
            file_path=file_path,
            file_sha256=file_sha256,
            required=required,
        )
    if is_recompute:
        _validate_canary_recompute_lineage(metadata=metadata, existing=existing)
    elif existing:
        raise ValueError("TaskRun ContextBundle identity conflicts with registered artifact")
    try:
        with db.begin_nested():
            row = register_artifact(
                db,
                run_id=run_id,
                step=step,
                artifact_id=required["bundle_id"],
                artifact_type="structured_json",
                file_path=file_path,
                sha256=file_sha256,
                content_type=str(descriptor.get("content_type") or "application/json"),
                source_refs=_context_bundle_registry_source_refs(
                    descriptor.get("source_refs"), bundle_id=required["bundle_id"]
                ),
                input_snapshot_ids={
                    "analysis_context_bundle": {
                        "bundle_id": required["bundle_id"],
                        "content_hash": required["content_hash"],
                        "canonical_state_id": required["canonical_state_id"],
                    }
                },
                metadata=dict(metadata),
                registry_artifact_id=registry_row_id,
                require_canonical_path=False,
                storage=effective_storage,
            )
            if row is None:  # pragma: no cover - table availability checked above
                raise ValueError("ContextBundle registry unexpectedly became unavailable")
            return _validate_registered_context_bundle_row(
                row,
                registry_row_id=registry_row_id,
                file_path=file_path,
                file_sha256=file_sha256,
                required=required,
            )
    except IntegrityError:
        # The deterministic primary key serializes concurrent registration for
        # one run without a schema migration. Re-read and apply the exact same
        # identity checks; a conflicting winner still fails closed.
        winner = db.get(RunArtifact, registry_row_id)
        if winner is None:
            raise
        return _validate_registered_context_bundle_row(
            winner,
            registry_row_id=registry_row_id,
            file_path=file_path,
            file_sha256=file_sha256,
            required=required,
        )


def _validate_canary_recompute_lineage(
    *,
    metadata: dict[str, Any],
    existing: list[RunArtifact],
) -> None:
    if len(existing) != 1:
        raise ValueError("canary recompute permits exactly one superseded Bundle")
    attempt = metadata.get("canary_recompute_attempt")
    if isinstance(attempt, bool) or attempt != 1:
        raise ValueError("canary recompute is limited to attempt 1")
    predecessor = existing[0].artifact_metadata
    if not isinstance(predecessor, dict):
        raise ValueError("canary recompute predecessor metadata is invalid")
    expected = {
        "supersedes_bundle_id": predecessor.get("bundle_id"),
        "supersedes_bundle_hash": predecessor.get("content_hash"),
        "supersedes_canonical_state_id": predecessor.get("canonical_state_id"),
    }
    for key, value in expected.items():
        if not value or str(metadata.get(key) or "") != str(value):
            raise ValueError(f"canary recompute {key} does not match registered predecessor")
    if str(metadata.get("canonical_state_id") or "") == str(predecessor.get("canonical_state_id") or ""):
        raise ValueError("canary recompute must use a fresh canonical state")


def _validate_registered_context_bundle_row(
    row: RunArtifact,
    *,
    registry_row_id: uuid.UUID,
    file_path: str,
    file_sha256: str,
    required: dict[str, str],
) -> RunArtifact:
    row_metadata = row.artifact_metadata or {}
    if (
        row.artifact_id != registry_row_id
        or row.file_path != file_path
        or str(row.sha256 or "").lower() != file_sha256
        or str(getattr(row.artifact_type, "value", row.artifact_type) or "") != "structured_json"
        or not isinstance(row_metadata, dict)
        or row_metadata.get("artifact_family") != "analysis_context_bundle"
        or str(row_metadata.get("bundle_id") or "") != required["bundle_id"]
        or str(row_metadata.get("content_hash") or "") != required["content_hash"]
        or str(row_metadata.get("run_id") or "") != required["run_id"]
        or str(row_metadata.get("canonical_state_id") or "") != required["canonical_state_id"]
        or str(row_metadata.get("schema_version") or "") != required["schema_version"]
        or str(row_metadata.get("asset") or "") != required["asset"]
        or str(row_metadata.get("state_scope") or "") != required["state_scope"]
    ):
        raise ValueError("TaskRun ContextBundle identity conflicts with registered artifact")
    return row


def _is_lowercase_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _context_bundle_registry_source_refs(raw_refs: Any, *, bundle_id: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for raw_ref in raw_refs if isinstance(raw_refs, list) else []:
        if not isinstance(raw_ref, dict):
            continue
        ref = dict(raw_ref)
        if not any(ref.get(key) for key in ("source", "source_name", "source_id", "source_key", "source_ref")):
            ref["source"] = "analysis_context_bundle_evidence"
        if not any(
            ref.get(key)
            for key in (
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
            )
        ):
            ref["ref"] = f"context_bundle:{bundle_id}"
        refs.append(ref)
    return refs or [{"source": "analysis_context_bundle", "ref": f"context_bundle:{bundle_id}"}]


def _gold_policy_input_snapshot_ids(composite_outputs: dict[str, Any]) -> dict[str, str] | None:
    if composite_outputs.get("gold_policy_execution_mode") != "shadow":
        return None
    feature_snapshot = composite_outputs.get("gold_feature_snapshot")
    snapshot_id = getattr(feature_snapshot, "snapshot_id", None)
    if not isinstance(snapshot_id, str) or not snapshot_id:
        return None
    result = {"gold_policy_feature_snapshot": snapshot_id}
    decision = composite_outputs.get("gold_analysis_decision")
    previous_snapshot_id = getattr(decision, "previous_snapshot_id", None)
    if (
        isinstance(previous_snapshot_id, str)
        and previous_snapshot_id
        and previous_snapshot_id != "missing"
    ):
        result["gold_policy_previous_feature_snapshot"] = previous_snapshot_id
    return result


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
        identity = _first_lineage_ref_value(
            normalized, ("source_ref", "source_id", "source_name", "source", "source_key")
        )
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
