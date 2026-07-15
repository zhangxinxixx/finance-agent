from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_DOWNSTREAM_READINESS_AGE_MINUTES = 60


def build_processing_plan(*, storage_root: Path, trade_date: str, observed_at: str) -> dict[str, Any]:
    readiness = _read_downstream_readiness(storage_root=storage_root, trade_date=trade_date)
    quality_gate_evaluation = _evaluate_quality_gate(readiness=readiness, observed_at=observed_at, trade_date=trade_date)
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

    capabilities = (
        readiness.get("capabilities")
        if quality_gate_evaluation["status"] == "current" and readiness and isinstance(readiness.get("capabilities"), dict)
        else None
    )
    full_analysis_blocked = False
    if quality_gate_evaluation["status"] != "current":
        blocked_steps.append(
            {
                "step": "refresh_data_quality_monitor",
                "reason_code": quality_gate_evaluation["reason_code"],
                "quality_gate_evaluation": quality_gate_evaluation,
            }
        )
        full_analysis_blocked = True
    elif capabilities is not None:
        capability_steps = {
            "full_daily_analysis": "run_full_analysis",
            "research_report_interpretation": "run_research_report_interpretation",
            "knowledge_distillation": "run_knowledge_distillation",
            "technical_trigger_confirmation": "run_technical_trigger_confirmation",
            "options_structure_analysis": "run_options_structure_analysis",
        }
        for capability, step_name in capability_steps.items():
            if capabilities.get(capability) != "blocked":
                continue
            blocked_steps.append(
                {
                    "step": step_name,
                    "capability": capability,
                    "reason_code": "downstream_capability_blocked",
                    "blocking_issues": readiness.get("blocking_issues") or [],
                }
            )
        full_analysis_blocked = capabilities.get("full_daily_analysis") == "blocked"
    elif readiness and readiness.get("readiness") == "blocked":
        blocked_steps.append(
            {
                "step": "run_full_analysis_or_distillation",
                "reason_code": "downstream_quality_gate_blocked",
                "blocked_outputs": readiness.get("blocked_outputs") or [],
                "blocking_issues": readiness.get("blocking_issues") or [],
            }
        )
        full_analysis_blocked = True

    has_degraded_capability = bool(capabilities) and any(state == "degraded" for state in capabilities.values())
    if full_analysis_blocked:
        status = "blocked"
    elif blocked_steps or missing_artifacts or has_degraded_capability:
        status = "partial"
    else:
        status = "ready"

    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "status": status,
        "ready_steps": ready_steps,
        "missing_artifacts": missing_artifacts,
        "blocked_steps": blocked_steps,
        "quality_gate": readiness or {"readiness": "unknown", "blocked_outputs": []},
        "quality_gate_evaluation": quality_gate_evaluation,
    }


def _read_downstream_readiness(*, storage_root: Path, trade_date: str) -> dict[str, Any] | None:
    path = storage_root / "monitoring" / trade_date / "downstream_readiness.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _evaluate_quality_gate(*, readiness: dict[str, Any] | None, observed_at: str, trade_date: str) -> dict[str, Any]:
    source_ref = f"monitoring/{trade_date}/downstream_readiness.json"
    if readiness is None:
        return {
            "status": "missing",
            "reason_code": "downstream_readiness_missing",
            "source_ref": source_ref,
            "observed_at": None,
            "age_minutes": None,
            "max_age_minutes": MAX_DOWNSTREAM_READINESS_AGE_MINUTES,
        }
    readiness_trade_date = str(readiness.get("trade_date") or "")
    if readiness_trade_date != trade_date:
        return {
            "status": "trade_date_mismatch",
            "reason_code": "downstream_readiness_trade_date_mismatch",
            "source_ref": source_ref,
            "trade_date": readiness_trade_date or None,
            "observed_at": readiness.get("observed_at"),
            "age_minutes": None,
            "max_age_minutes": MAX_DOWNSTREAM_READINESS_AGE_MINUTES,
        }
    current = _parse_datetime(observed_at)
    gate_observed_at = _parse_datetime(readiness.get("observed_at"))
    if current is None or gate_observed_at is None:
        return {
            "status": "missing_timestamp",
            "reason_code": "downstream_readiness_timestamp_missing",
            "source_ref": source_ref,
            "observed_at": readiness.get("observed_at"),
            "age_minutes": None,
            "max_age_minutes": MAX_DOWNSTREAM_READINESS_AGE_MINUTES,
        }
    age_minutes = int((current - gate_observed_at).total_seconds() // 60)
    if age_minutes < -5:
        status = "future"
        reason_code = "downstream_readiness_from_future"
    elif age_minutes > MAX_DOWNSTREAM_READINESS_AGE_MINUTES:
        status = "stale"
        reason_code = "downstream_readiness_stale"
    else:
        status = "current"
        reason_code = None
    return {
        "status": status,
        "reason_code": reason_code,
        "source_ref": source_ref,
        "observed_at": gate_observed_at.isoformat(),
        "age_minutes": age_minutes,
        "max_age_minutes": MAX_DOWNSTREAM_READINESS_AGE_MINUTES,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
