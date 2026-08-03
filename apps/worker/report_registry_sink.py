from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from apps.runtime.artifact_storage import get_artifact_storage
from apps.worker.artifact_registration import (
    coerce_lineage_source_refs,
    enrich_runner_artifact_metadata,
    merge_lineage_input_snapshot_ids,
    merge_lineage_source_refs,
)
from database.queries.report import upsert_report_artifact, upsert_report_item


def register_composite_report_registry_entries(
    db: DBSession,
    *,
    run_id: str,
    composite_outputs: dict[str, Any],
    analysis_snapshot: dict[str, Any] | None = None,
) -> None:
    agent_loop_decision = composite_outputs.get("agent_loop_decision") if isinstance(composite_outputs, dict) else None
    if not bool(getattr(agent_loop_decision, "publish_allowed", False)):
        return

    report_result = composite_outputs.get("report_result") if isinstance(composite_outputs, dict) else None
    card_result = composite_outputs.get("card_result") if isinstance(composite_outputs, dict) else None
    card = composite_outputs.get("strategy_card") if isinstance(composite_outputs, dict) else None

    snapshot_id = analysis_snapshot.get("snapshot_id") if isinstance(analysis_snapshot, dict) else None
    trade_date = analysis_snapshot.get("trade_date") if isinstance(analysis_snapshot, dict) else None
    asset = analysis_snapshot.get("asset", "XAUUSD") if isinstance(analysis_snapshot, dict) else "XAUUSD"
    source_refs = (
        merge_lineage_source_refs(
            analysis_snapshot.get("source_refs") if isinstance(analysis_snapshot, dict) else None,
            list(getattr(card, "source_refs", []) or []) if card is not None else None,
        )
        or []
    )
    input_snapshot_ids = (
        merge_lineage_input_snapshot_ids(
            analysis_snapshot.get("input_snapshot_ids") if isinstance(analysis_snapshot, dict) else None,
            dict(getattr(card, "input_snapshot_ids", {}) or {}) if card is not None else None,
        )
        or {}
    )

    report_specs = [
        {
            "report_id": f"final_report:{run_id}",
            "family": "final_report_markdown",
            "report_type": "final_report",
            "title": f"{asset} 综合报告（{trade_date}）" if trade_date else f"{asset} 综合报告",
            "paths": report_result.get("paths") if isinstance(report_result, dict) else None,
            "primary_name": "final_report.md",
            "metadata": {
                "input_snapshot_ids": input_snapshot_ids,
                "writer": "run_premarket",
                "publish_allowed": True,
                "review_status": getattr(agent_loop_decision, "review_status", "pass"),
                "output_mode": "accepted",
            },
        },
        {
            "report_id": f"strategy_card:{run_id}",
            "family": "strategy_card",
            "report_type": "strategy_card",
            "title": f"{asset} 策略卡片（{trade_date}）" if trade_date else f"{asset} 策略卡片",
            "paths": card_result.get("paths") if isinstance(card_result, dict) else None,
            "primary_name": "strategy_card.json",
            "metadata": {
                "input_snapshot_ids": input_snapshot_ids,
                "writer": "run_premarket",
                "strategy_card_id": getattr(card, "strategy_card_id", None),
                "publish_allowed": True,
                "review_status": getattr(agent_loop_decision, "review_status", "pass"),
                "output_mode": "accepted",
            },
        },
    ]

    with db.begin_nested():
        for spec in report_specs:
            raw_paths = spec.get("paths")
            if not isinstance(raw_paths, list):
                continue
            existing_paths = [Path(path) for path in raw_paths if isinstance(path, str) and path]
            existing_paths = [path for path in existing_paths if path.exists()]
            if not existing_paths:
                continue

            upsert_report_item(
                db,
                {
                    "report_id": spec["report_id"],
                    "family": spec["family"],
                    "report_type": spec["report_type"],
                    "title": spec["title"],
                    "asset": asset,
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "data_status": "live",
                    "lifecycle_status": "generated",
                    "source_refs": source_refs,
                    "metadata": spec["metadata"],
                },
            )

            for index, path in enumerate(existing_paths):
                artifact = enrich_runner_artifact_metadata(
                    {
                        "artifact_id": f"{spec['report_id']}:{index}",
                        "artifact_type": "analysis_md" if path.suffix.lower() == ".md" else "structured_json",
                        "file_path": str(path),
                    }
                )
                artifact["sha256"] = get_artifact_storage().compute_sha256(str(path))
                artifact["storage_backend"] = "local_fs"
                artifact["report_id"] = spec["report_id"]
                artifact["source_refs"] = source_refs
                artifact["metadata"] = {
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "input_snapshot_ids": input_snapshot_ids,
                }
                artifact["is_primary"] = path.name == spec["primary_name"]
                upsert_report_artifact(db, artifact)
        db.flush()


class GoldPolicyReportRegistryError(RuntimeError):
    """Raised when a Gold Policy daily-close bundle cannot be registry-accepted."""


_GOLD_POLICY_REPORT_BUNDLE_FILES = (
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "report_manifest.json",
    "strategy_card.json",
    "strategy_card.md",
)
_GOLD_POLICY_REPORT_MANIFEST_SCHEMA = "gold_policy_report_manifest.v2"
_GOLD_POLICY_REPORT_STRUCTURED_SCHEMA = "gold_policy_report_structured.v2"
_GOLD_POLICY_REGISTRY_REPORT_FAMILY = "gold_policy_daily_report"
_GOLD_POLICY_REGISTRY_REPORT_TYPE = "gold_policy_daily"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_type_for_filename(filename: str) -> str:
    if filename == "source.md":
        return "source_md"
    if filename in {"analysis.md", "strategy_card.md"}:
        return "analysis_md"
    if filename == "visual.html":
        return "visual_html"
    return "structured_json"


def _content_type_for_filename(filename: str) -> str:
    if filename.endswith(".md"):
        return "text/markdown"
    if filename.endswith(".html"):
        return "text/html"
    if filename.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def _normalize_gold_policy_source_refs(raw_source_refs: Any) -> list[dict[str, Any]]:
    """Preserve v2 source_refs lineage before coerce.

    v2 evidence.json source_refs carry ``reference``/``retrieved_at`` fields
    that ``coerce_lineage_source_refs`` does not know.  Map them to
    ``source_ref``/``captured_at`` so the lineage identity and trace detail
    survive without degenerating to the bare source name.
    """

    if not isinstance(raw_source_refs, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_source_refs:
        if not isinstance(item, dict):
            continue
        ref = dict(item)
        reference = ref.get("reference")
        if isinstance(reference, str) and reference and "source_ref" not in ref:
            ref["source_ref"] = reference
        retrieved_at = ref.get("retrieved_at")
        if isinstance(retrieved_at, str) and retrieved_at and "captured_at" not in ref:
            ref["captured_at"] = retrieved_at
        normalized.append(ref)
    coerced = coerce_lineage_source_refs(normalized)
    return coerced or []


def _map_gold_policy_publication_status(publication_status: str) -> tuple[str, str]:
    """Map Gold Policy publication_status to (data_status, lifecycle_status)."""

    if publication_status == "accepted":
        return ("live", "snapshot_bound")
    if publication_status in {"observe", "degraded"}:
        return ("partial", "needs_review")
    raise GoldPolicyReportRegistryError(
        f"gold policy bundle publication_status is not accepted/observe/degraded: {publication_status}"
    )


def register_gold_policy_report_bundle(
    db: DBSession,
    *,
    storage_root: Path,
    bundle_path: Path,
) -> str:
    """Register a verified Gold Policy daily-close bundle into the registry.

    The sink fail-closes: any verification, schema, or lineage mismatch raises
    ``GoldPolicyReportRegistryError`` and never enters a DB transaction.  Only
    a fully verified v2 bundle produces exactly one ``ReportItem`` and nine
    ``ReportArtifact`` rows.  Repeated registrations of the same bundle are
    idempotent.
    """

    try:
        verification = verify_gold_daily_close_bundle(
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
    except Exception as exc:  # pragma: no cover - defensive, verifier raises within its own boundary
        raise GoldPolicyReportRegistryError(
            f"gold policy bundle verification raised: {type(exc).__name__}: {exc}"
        ) from exc

    if verification.status != "valid" or verification.receipt is None:
        raise GoldPolicyReportRegistryError(
            f"gold policy bundle verification failed: status={verification.status} reason={verification.reason_code}"
        )

    receipt = verification.receipt
    bundle_path_resolved = verification.bundle_path

    try:
        manifest = _read_json_payload(bundle_path_resolved / "report_manifest.json")
        structured = _read_json_payload(bundle_path_resolved / "report_structured.json")
        manifest_schema = manifest.get("schema_version")
        structured_schema = structured.get("schema_version")
        if (
            manifest_schema != _GOLD_POLICY_REPORT_MANIFEST_SCHEMA
            or structured_schema != _GOLD_POLICY_REPORT_STRUCTURED_SCHEMA
        ):
            raise GoldPolicyReportRegistryError(
                f"gold policy bundle schema is not v2: manifest={manifest_schema} structured={structured_schema}"
            )

        trade_date_str = manifest.get("trade_date")
        manifest_run_id = manifest.get("run_id")
        manifest_asset = manifest.get("asset")
        if (
            not isinstance(trade_date_str, str)
            or not isinstance(manifest_run_id, str)
            or not isinstance(manifest_asset, str)
        ):
            raise GoldPolicyReportRegistryError("gold policy manifest identity is incomplete")
        if manifest_asset != "XAUUSD":
            raise GoldPolicyReportRegistryError(f"gold policy bundle asset is not XAUUSD: {manifest_asset}")
        if trade_date_str != receipt.session_date.isoformat():
            raise GoldPolicyReportRegistryError(
                f"gold policy manifest trade_date={trade_date_str} does not match receipt "
                f"session_date={receipt.session_date.isoformat()}"
            )
        if manifest_run_id != receipt.run_id:
            raise GoldPolicyReportRegistryError(
                f"gold policy manifest run_id={manifest_run_id} does not match receipt run_id={receipt.run_id}"
            )

        for filename in _GOLD_POLICY_REPORT_BUNDLE_FILES:
            if not (bundle_path_resolved / filename).is_file():
                raise GoldPolicyReportRegistryError(f"gold policy bundle is missing required file: {filename}")

        evidence = _read_json_payload(bundle_path_resolved / "evidence.json")
        data_quality = _read_json_payload(bundle_path_resolved / "data_quality.json")
        raw_source_refs = evidence.get("source_refs") if isinstance(evidence, dict) else None
        source_refs = _normalize_gold_policy_source_refs(raw_source_refs)
        if not source_refs:
            raise GoldPolicyReportRegistryError("gold policy bundle has no source_refs")
        raw_input_snapshot_ids = evidence.get("input_snapshot_ids") if isinstance(evidence, dict) else None
        input_snapshot_ids = merge_lineage_input_snapshot_ids(raw_input_snapshot_ids) or {}
        if not input_snapshot_ids:
            raise GoldPolicyReportRegistryError("gold policy bundle has no input_snapshot_ids")
        artifact_refs = evidence.get("artifact_refs") if isinstance(evidence, dict) else None
        if not isinstance(artifact_refs, list):
            artifact_refs = []

        publication_status = data_quality.get("publication_status") or data_quality.get("report_status")
        if not isinstance(publication_status, str):
            raise GoldPolicyReportRegistryError("gold policy bundle publication_status is missing")
        data_status, lifecycle_status = _map_gold_policy_publication_status(publication_status)

        domain_status = data_quality.get("domain_status") if isinstance(data_quality, dict) else None
        prohibited_outputs = data_quality.get("prohibited_outputs") if isinstance(data_quality, dict) else None
        if not isinstance(prohibited_outputs, list):
            prohibited_outputs = []

        snapshot_id = manifest.get("snapshot_id") if isinstance(manifest.get("snapshot_id"), str) else None
        context_id = manifest.get("context_id") if isinstance(manifest.get("context_id"), str) else None
        render_id = manifest.get("render_id") if isinstance(manifest.get("render_id"), str) else None
        authority_result_id = manifest.get("authority_result_id")
        if not isinstance(authority_result_id, str):
            authority_result_id = None

        artifact_specs: list[dict[str, Any]] = []
        for filename in _GOLD_POLICY_REPORT_BUNDLE_FILES:
            artifact_path = bundle_path_resolved / filename
            content = artifact_path.read_bytes()
            sha256 = _sha256_bytes(content)
            artifact_metadata: dict[str, Any] = {
                "filename": filename,
                "sha256": sha256,
                "receipt_id": receipt.receipt_id,
                "receipt_revision_no": receipt.revision_no,
                "canonical_commit_action": receipt.action.value,
                "input_snapshot_ids": input_snapshot_ids,
                "artifact_refs": artifact_refs,
                "publication_status": publication_status,
                "domain_status": domain_status,
                "prohibited_outputs": prohibited_outputs,
            }
            if filename == "report_manifest.json":
                artifact_metadata["schema_version"] = manifest_schema
            elif filename == "report_structured.json":
                artifact_metadata["schema_version"] = structured_schema
            artifact_specs.append(
                {
                    "artifact_id": f"gold_policy_daily:{trade_date_str}:{manifest_run_id}:{filename}",
                    "file_path": str(artifact_path),
                    "artifact_type": _artifact_type_for_filename(filename),
                    "content_type": _content_type_for_filename(filename),
                    "byte_size": len(content),
                    "sha256": sha256,
                    "is_primary": filename == "analysis.md",
                    "metadata": artifact_metadata,
                }
            )

        re_verification = verify_gold_daily_close_bundle(
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
    except GoldPolicyReportRegistryError:
        raise
    except Exception as exc:
        raise GoldPolicyReportRegistryError(
            f"gold policy bundle read or re-verification failed: {type(exc).__name__}: {exc}"
        ) from exc

    if (
        re_verification.status != "valid"
        or re_verification.receipt is None
        or re_verification.receipt.receipt_id != receipt.receipt_id
    ):
        raise GoldPolicyReportRegistryError("gold policy bundle verification changed between read and write")

    report_id = f"gold_policy_daily:{trade_date_str}:{manifest_run_id}"
    report_title = f"XAUUSD Gold Policy Daily Report（{trade_date_str}）"
    report_metadata: dict[str, Any] = {
        "writer": "register_gold_policy_report_bundle",
        "publication_status": publication_status,
        "output_mode": "accepted" if publication_status == "accepted" else "observe",
        "input_snapshot_ids": input_snapshot_ids,
        "artifact_refs": artifact_refs,
        "domain_status": domain_status,
        "prohibited_outputs": prohibited_outputs,
        "report_context_id": context_id,
        "report_render_id": render_id,
        "authority_result_id": authority_result_id,
        "canonical_receipt_id": receipt.receipt_id,
        "canonical_receipt_revision_no": receipt.revision_no,
        "canonical_commit_action": receipt.action.value,
        "manifest_schema_version": manifest_schema,
        "structured_schema_version": structured_schema,
    }

    with db.begin_nested():
        upsert_report_item(
            db,
            {
                "report_id": report_id,
                "family": _GOLD_POLICY_REGISTRY_REPORT_FAMILY,
                "report_type": _GOLD_POLICY_REGISTRY_REPORT_TYPE,
                "title": report_title,
                "asset": manifest_asset,
                "trade_date": trade_date_str,
                "run_id": manifest_run_id,
                "snapshot_id": snapshot_id,
                "data_status": data_status,
                "lifecycle_status": lifecycle_status,
                "source_refs": source_refs,
                "metadata": report_metadata,
            },
        )
        for spec in artifact_specs:
            upsert_report_artifact(
                db,
                {
                    "artifact_id": spec["artifact_id"],
                    "report_id": report_id,
                    "artifact_type": spec["artifact_type"],
                    "file_path": spec["file_path"],
                    "storage_backend": "local_fs",
                    "sha256": spec["sha256"],
                    "content_type": spec["content_type"],
                    "byte_size": spec["byte_size"],
                    "is_primary": spec["is_primary"],
                    "source_refs": source_refs,
                    "metadata": spec["metadata"],
                },
            )
        db.flush()

    return report_id
