from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.data_control.gold_processing_context import GoldProcessingContext
from apps.runtime.source_controls import jin10_disabled

MAX_DOWNSTREAM_READINESS_AGE_MINUTES = 60


def build_processing_plan(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: str,
    gold_context: GoldProcessingContext | None = None,
) -> dict[str, Any]:
    jin10_is_disabled = jin10_disabled()
    readiness = (
        None
        if jin10_is_disabled
        else _read_downstream_readiness(storage_root=storage_root, trade_date=trade_date)
    )
    quality_gate_evaluation = _evaluate_quality_gate(readiness=readiness, observed_at=observed_at, trade_date=trade_date)
    ready_steps: list[str] = []
    blocked_steps: list[dict[str, Any]] = []
    missing_artifacts: list[dict[str, str]] = []

    if not jin10_is_disabled:
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
    if gold_context is None:
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
            blocked_steps.extend(
                _legacy_blocked_capabilities(
                    capabilities=capabilities,
                    readiness=readiness,
                )
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
        quality_gate = readiness or {"readiness": "unknown", "blocked_outputs": []}
    else:
        if quality_gate_evaluation["status"] != "current":
            blocked_steps.append(
                {
                    "step": "refresh_data_quality_monitor",
                    "capability": "knowledge_distillation",
                    "reason_code": "legacy_downstream_readiness_unknown",
                    "quality_gate_evaluation": quality_gate_evaluation,
                }
            )
        elif (
            not capabilities
            and readiness
            and readiness.get("readiness") == "blocked"
            and gold_context.analysis_readiness == "blocked"
        ):
            blocked_steps.append(
                {
                    "step": "run_full_analysis_or_distillation",
                    "reason_code": "downstream_quality_gate_blocked",
                    "blocked_outputs": readiness.get("blocked_outputs") or [],
                    "blocking_issues": readiness.get("blocking_issues") or [],
                }
            )
        elif capabilities is not None:
            blocked_steps.extend(
                item
                for item in _legacy_blocked_capabilities(capabilities=capabilities, readiness=readiness)
                if item.get("capability")
                not in {"full_daily_analysis", "technical_trigger_confirmation", "options_structure_analysis"}
            )
        quality_gate, quality_gate_evaluation = _project_gold_gate(
            context=gold_context,
            legacy_readiness=readiness,
            legacy_evaluation=quality_gate_evaluation,
            trade_date=trade_date,
            observed_at=observed_at,
        )
        blocked_steps.extend(_gold_blocked_steps(gold_context))
        full_analysis_blocked = gold_context.analysis_readiness == "blocked"

    projected_capabilities = quality_gate.get("capabilities") if isinstance(quality_gate, dict) else None
    has_degraded_capability = bool(projected_capabilities) and any(
        state == "degraded" for state in projected_capabilities.values()
    )
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
        "quality_gate": quality_gate,
        "quality_gate_evaluation": quality_gate_evaluation,
        "jin10_disabled": jin10_is_disabled,
        "disabled_sources": _disabled_sources() if jin10_is_disabled else [],
        "gold_processing_context": gold_context.to_dict() if gold_context else None,
        "gold_processing_actions": gold_context.action_suggestions() if gold_context else [],
    }


def _legacy_blocked_capabilities(
    *,
    capabilities: dict[str, Any],
    readiness: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    capability_steps = {
        "full_daily_analysis": "run_full_analysis",
        "research_report_interpretation": "run_research_report_interpretation",
        "knowledge_distillation": "run_knowledge_distillation",
        "technical_trigger_confirmation": "run_technical_trigger_confirmation",
        "options_structure_analysis": "run_options_structure_analysis",
    }
    return [
        {
            "step": step_name,
            "capability": capability,
            "reason_code": "downstream_capability_blocked",
            "blocking_issues": (readiness or {}).get("blocking_issues") or [],
        }
        for capability, step_name in capability_steps.items()
        if capabilities.get(capability) == "blocked"
    ]


def _project_gold_gate(
    *,
    context: GoldProcessingContext,
    legacy_readiness: dict[str, Any] | None,
    legacy_evaluation: dict[str, Any],
    trade_date: str,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    legacy_current = legacy_evaluation.get("status") == "current"
    projected = dict(legacy_readiness or {}) if legacy_current else {}
    capabilities = dict(projected.get("capabilities") or {}) if legacy_current else {}
    capabilities["full_daily_analysis"] = _capability_state(context.analysis_readiness)
    capabilities["technical_trigger_confirmation"] = _capability_state(context.strategy_readiness)
    capabilities["options_structure_analysis"] = _capability_state(context.options_readiness)
    if "knowledge_distillation" not in capabilities:
        capabilities["knowledge_distillation"] = "blocked"
    projected["capabilities"] = capabilities
    projected["readiness"] = _quality_gate_readiness(context.analysis_readiness, capabilities)
    projected["can_run_full_analysis"] = context.analysis_readiness != "blocked"
    projected["can_run_research_distillation"] = capabilities["knowledge_distillation"] != "blocked"
    projected["gold_readiness"] = context.readiness_dict()
    projected["gold_authority"] = context.to_dict()["authority"]
    projected["gold_processing_limits"] = context.limits_dict()
    projected["knowledge_distillation_source"] = "legacy_downstream_readiness" if legacy_current else "unknown"

    allowed_outputs = [
        item
        for item in projected.get("allowed_outputs") or []
        if item not in {"full daily analysis", "limited daily analysis"}
    ]
    if context.analysis_readiness == "ready":
        allowed_outputs.append("full daily analysis")
    elif context.analysis_readiness == "observe":
        allowed_outputs.append("limited daily analysis")
    projected["allowed_outputs"] = _unique(allowed_outputs)

    blocked_outputs = [
        item
        for item in projected.get("blocked_outputs") or []
        if item != "full analysis" or context.analysis_readiness == "blocked"
    ]
    blocked_outputs.extend(context.prohibited_outputs)
    projected["blocked_outputs"] = _unique(blocked_outputs)
    projected["trade_date"] = trade_date
    projected["observed_at"] = observed_at

    evaluation = {
        "status": "current" if context.found else "blocked",
        "reason_code": None if context.found else context.authority_reason_code,
        "source_ref": context.source_ref.get("source_ref"),
        "observed_at": observed_at,
        "cutoff": context.cutoff.isoformat() if context.cutoff else None,
        "age_minutes": None,
        "max_age_minutes": None,
        "authority_status": context.authority_status,
        "authority_snapshot_id": context.authority_snapshot_id,
        "feature_snapshot_id": context.feature_snapshot_id,
    }
    return projected, evaluation


def _gold_blocked_steps(context: GoldProcessingContext) -> list[dict[str, Any]]:
    step_by_output = {
        "DIRECTIONAL_ANALYSIS": ("run_full_analysis", "full_daily_analysis"),
        "DIRECTIONAL_STRATEGY": ("run_directional_strategy", "full_daily_analysis"),
        "OPTIONS_CONFIRMATION": ("run_options_structure_analysis", "options_structure_analysis"),
        "TRIGGERED_STRATEGY": ("run_triggered_strategy", "technical_trigger_confirmation"),
        "CONFIRMED_EVENT_ATTRIBUTION": ("run_confirmed_event_attribution", None),
    }
    return [
        {
            "step": step_name,
            "capability": capability,
            "reason_code": "gold_readiness_blocked",
            "blocked_outputs": [output],
            "blocking_issues": [
                {
                    "source_key": "gold_premarket_authority" if not context.found else "gold_readiness",
                    "check_type": "gold_readiness",
                    "status": _gold_output_readiness(context, output),
                    "reason_code": context.authority_reason_code
                    if not context.found
                    else (context.reason_codes[0] if context.reason_codes else "gold_readiness_blocked"),
                }
            ],
        }
        for output in context.prohibited_outputs
        if output in step_by_output
        for step_name, capability in (step_by_output[output],)
    ]


def _gold_output_readiness(context: GoldProcessingContext, output: str) -> str:
    if output == "OPTIONS_CONFIRMATION":
        return context.options_readiness
    if output == "CONFIRMED_EVENT_ATTRIBUTION":
        return context.event_attribution_readiness
    if output == "TRIGGERED_STRATEGY" or output == "DIRECTIONAL_STRATEGY":
        return context.strategy_readiness
    return context.analysis_readiness


def _capability_state(readiness: str) -> str:
    return {"ready": "allowed", "observe": "degraded", "blocked": "blocked"}.get(readiness, "blocked")


def _quality_gate_readiness(analysis_readiness: str, capabilities: dict[str, Any]) -> str:
    if analysis_readiness == "blocked":
        return "blocked"
    if analysis_readiness == "observe" or any(state == "degraded" for state in capabilities.values()):
        return "partial"
    return "ready"


def _disabled_sources() -> list[str]:
    return [
        "jin10_mcp_market",
        "jin10_mcp_flash",
        "jin10_xnews_public",
        "jin10_daily_report",
        "jin10_svip_reports",
        "jin10_datacenter_reports",
    ]


def _unique(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


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
