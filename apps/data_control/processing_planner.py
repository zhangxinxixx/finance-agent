from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_processing_plan(*, storage_root: Path, trade_date: str, observed_at: str) -> dict[str, Any]:
    readiness = _read_downstream_readiness(storage_root=storage_root, trade_date=trade_date)
    ready_steps: list[str] = []
    blocked_steps: list[dict[str, Any]] = []
    missing_artifacts: list[dict[str, str]] = []

    raw_index = storage_root / "raw" / "jin10" / trade_date / "index.json"
    parsed_index = storage_root / "parsed" / "jin10" / trade_date / "index.json"
    output_analysis = storage_root / "outputs" / "jin10" / trade_date / "analysis.json"
    agent_reports = list((storage_root / "outputs" / "jin10" / trade_date).glob("*/agent_analysis_report.json"))

    if raw_index.is_file():
        ready_steps.append("jin10_reports_raw_to_parsed")
    else:
        missing_artifacts.append({"artifact_type": "raw_index", "path": _rel(raw_index, storage_root)})
    if parsed_index.is_file():
        ready_steps.append("jin10_reports_parsed_to_outputs")
    else:
        missing_artifacts.append({"artifact_type": "parsed_index", "path": _rel(parsed_index, storage_root)})
    if output_analysis.is_file() or agent_reports:
        ready_steps.append("jin10_reports_outputs_to_agent_outputs")
    else:
        missing_artifacts.append({"artifact_type": "output_bundle", "path": _rel(output_analysis, storage_root)})

    if readiness and readiness.get("readiness") == "blocked":
        blocked_steps.append(
            {
                "step": "run_full_analysis_or_distillation",
                "reason_code": "downstream_quality_gate_blocked",
                "blocked_outputs": readiness.get("blocked_outputs") or [],
                "blocking_issues": readiness.get("blocking_issues") or [],
            }
        )

    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "status": "blocked" if blocked_steps else ("partial" if missing_artifacts else "ready"),
        "ready_steps": ready_steps,
        "missing_artifacts": missing_artifacts,
        "blocked_steps": blocked_steps,
        "quality_gate": readiness or {"readiness": "unknown", "blocked_outputs": []},
    }


def _read_downstream_readiness(*, storage_root: Path, trade_date: str) -> dict[str, Any] | None:
    path = storage_root / "monitoring" / trade_date / "downstream_readiness.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
