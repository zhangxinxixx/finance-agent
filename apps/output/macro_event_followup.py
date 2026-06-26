from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.output.final_report import _safe_artifact_dir
from apps.renderer.contracts import MacroEventFollowupStructuredPayload


def write_macro_event_followup(
    *,
    storage_root: Path | str,
    asset: str,
    trade_date: str,
    run_id: str,
    source_markdown: str,
    analysis_markdown: str,
    structured_payload: dict[str, Any],
    overwrite: bool = False,
) -> dict[str, Any]:
    validated_payload = MacroEventFollowupStructuredPayload.model_validate(structured_payload)
    artifact_dir = _safe_artifact_dir(
        storage_root,
        artifact_type="macro_event_followup",
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
    )

    source_path = artifact_dir / "source.md"
    analysis_path = artifact_dir / "analysis.md"
    structured_path = artifact_dir / "report_structured.json"

    if not overwrite:
        conflicts = [path for path in (source_path, analysis_path, structured_path) if path.exists()]
        if conflicts:
            raise FileExistsError(
                "macro_event_followup artifacts already exist: "
                + ", ".join(str(path) for path in conflicts)
            )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source_markdown, encoding="utf-8")
    analysis_path.write_text(analysis_markdown, encoding="utf-8")
    structured_path.write_text(
        json.dumps(validated_payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "artifact_type": "macro_event_followup",
        "paths": [str(source_path), str(analysis_path), str(structured_path)],
        "skipped": False,
    }
