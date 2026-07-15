from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.output.final_report import _safe_artifact_dir
from apps.renderer.contracts import WeeklyContextRevisionPayload


def write_weekly_context_revision(
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
    validated = WeeklyContextRevisionPayload.model_validate(structured_payload)
    artifact_dir = _safe_artifact_dir(
        storage_root,
        artifact_type="weekly_context_revision",
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
    )
    paths = [
        artifact_dir / "source.md",
        artifact_dir / "analysis.md",
        artifact_dir / "report_structured.json",
    ]
    if not overwrite:
        conflicts = [path for path in paths if path.exists()]
        if conflicts:
            raise FileExistsError(
                "weekly_context_revision artifacts already exist: "
                + ", ".join(str(path) for path in conflicts)
            )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(source_markdown, encoding="utf-8")
    paths[1].write_text(analysis_markdown, encoding="utf-8")
    paths[2].write_text(
        json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "artifact_type": "weekly_context_revision",
        "paths": [str(path) for path in paths],
        "skipped": False,
    }
