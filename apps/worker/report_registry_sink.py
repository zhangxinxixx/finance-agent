from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.runtime.artifact_storage import get_artifact_storage
from apps.worker.artifact_registration import (
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
    source_refs = merge_lineage_source_refs(
        analysis_snapshot.get("source_refs") if isinstance(analysis_snapshot, dict) else None,
        list(getattr(card, "source_refs", []) or []) if card is not None else None,
    ) or []
    input_snapshot_ids = merge_lineage_input_snapshot_ids(
        analysis_snapshot.get("input_snapshot_ids") if isinstance(analysis_snapshot, dict) else None,
        dict(getattr(card, "input_snapshot_ids", {}) or {}) if card is not None else None,
    ) or {}

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
