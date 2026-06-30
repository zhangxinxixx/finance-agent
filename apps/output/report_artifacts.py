from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.output.artifacts import artifact_run_dir

STANDARD_REPORT_ARTIFACTS: tuple[dict[str, Any], ...] = (
    {
        "slot": "source",
        "artifact_type": "source_md",
        "filename": "source.md",
        "content_type": "text/markdown",
        "is_primary": True,
    },
    {
        "slot": "analysis",
        "artifact_type": "analysis_md",
        "filename": "analysis.md",
        "content_type": "text/markdown",
        "is_primary": False,
    },
    {
        "slot": "visual",
        "artifact_type": "visual_html",
        "filename": "visual.html",
        "content_type": "text/html",
        "is_primary": False,
    },
    {
        "slot": "structured",
        "artifact_type": "structured_json",
        "filename": "report_structured.json",
        "content_type": "application/json",
        "is_primary": False,
    },
)


def write_standard_report_artifacts(
    *,
    storage_root: Path | str,
    family: str,
    report_id: str,
    trade_date: str,
    run_id: str,
    source_markdown: str,
    analysis_markdown: str,
    structured_payload: dict[str, Any],
    visual_html: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write the standard report artifact bundle and return a manifest."""

    safe_report_id = _validate_path_component("report_id", report_id)
    artifact_dir = artifact_run_dir(
        Path(storage_root),
        layer="outputs",
        domain="reports",
        date=trade_date,
        run_id=safe_report_id,
    )
    payloads = {
        "source": source_markdown,
        "analysis": analysis_markdown,
        "visual": visual_html or "",
        "structured": json.dumps(structured_payload, ensure_ascii=False, indent=2),
    }
    paths = [artifact_dir / str(spec["filename"]) for spec in STANDARD_REPORT_ARTIFACTS]
    if not overwrite:
        conflicts = [path for path in paths if path.exists()]
        if conflicts:
            raise FileExistsError(
                "standard report artifacts already exist: "
                + ", ".join(str(path) for path in conflicts)
            )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for spec in STANDARD_REPORT_ARTIFACTS:
        slot = str(spec["slot"])
        path = artifact_dir / str(spec["filename"])
        path.write_text(str(payloads[slot]), encoding="utf-8")
        artifacts.append(
            {
                "artifact_id": f"{safe_report_id}:{slot}",
                "report_id": safe_report_id,
                "family": family,
                "run_id": run_id,
                "trade_date": trade_date,
                "slot": slot,
                "artifact_type": spec["artifact_type"],
                "filename": spec["filename"],
                "content_type": spec["content_type"],
                "is_primary": spec["is_primary"],
                "path": str(path),
            }
        )

    return {
        "artifact_type": "standard_report",
        "report_id": safe_report_id,
        "family": family,
        "trade_date": trade_date,
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "artifacts": artifacts,
        "skipped": False,
    }


def _validate_path_component(name: str, value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if value in {".", ".."}:
        raise ValueError(f"{name} must not be a relative path component")
    if "/" in value or "\\" in value:
        raise ValueError(f"{name} must not contain path separators")
    if Path(value).is_absolute():
        raise ValueError(f"{name} must not be an absolute path")
    return value
