from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.agents.gold_artifacts import (
    GoldAgentArtifact,
    GoldArtifactWriteResult,
    write_gold_agent_artifact,
)
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, evaluate_quality_gate
from apps.analysis.agents.schemas import AgentStatus
from apps.analysis.agents.source_health import build_gold_v3_source_health

_AGENT_FILES = (
    ("source_health_agent", "source_health_output.json", "source_health"),
    ("event_attribution_agent", "event_attribution_output.json", "gold_event_mainlines"),
    ("transmission_chain_agent", "transmission_chain_output.json", "gold_event_mainlines"),
    ("driver_decomposition_agent", "driver_decomposition_output.json", "gold_event_mainlines"),
    ("mainline_ranking_agent", "mainline_ranking_output.json", "gold_event_mainlines"),
    ("gold_macro_overview_agent", "gold_macro_overview_output.json", "gold_macro_overview"),
    ("review_gate_agent", "review_gate_output.json", "quality_gate_result"),
)

_FORMAL_RENDER_ARTIFACT_TYPES = ("final_report", "strategy_card")
_OBSERVATION_RENDER_ARTIFACT_TYPES = ("observation_report", "observation_strategy_card")


def build_gold_runtime_gate(
    *,
    source_statuses: Any,
    overview: dict[str, Any],
    as_of: str | None = None,
) -> dict[str, dict[str, Any]]:
    source_health = build_gold_v3_source_health(
        source_statuses,
        as_of=as_of or str(overview.get("as_of") or "") or None,
        gold_macro_overview=overview,
    ).to_dict()
    return {
        "source_health": source_health,
        "review_gate": build_gold_review_gate(source_health=source_health, overview=overview),
    }


def build_gold_review_gate(
    *,
    source_health: dict[str, Any],
    overview: dict[str, Any],
) -> dict[str, Any]:
    quality_decision = evaluate_quality_gate(
        agent_outputs=[],
        gold_macro_overview=overview,
        source_health=source_health,
    )
    blocking_reasons = [str(item) for item in source_health.get("blocking_reasons") or []]
    warnings = [str(item) for item in source_health.get("warnings") or []]
    for finding in quality_decision.findings:
        target = blocking_reasons if finding.severity == "blocker" else warnings
        if finding.message not in target:
            target.append(finding.message)
    strong_conflict = any("strong conclusion" in reason.lower() for reason in blocking_reasons)
    if quality_decision.action is QualityGateAction.BLOCK_PUBLISH or strong_conflict:
        review_status = "blocked"
        reason = "QualityGate blocked publication for this GoldMacroOverview."
    elif blocking_reasons or warnings:
        review_status = "needs_review"
        reason = "QualityGate found missing, stale, fallback, or review-required evidence."
    else:
        review_status = "pass"
        reason = "QualityGate passed with no blocking reasons or warnings."
    review_gate = {
        "agent_id": "review_gate_agent",
        "dag_node_id": "review_gate",
        "review_status": review_status,
        "quality_gate_action": quality_decision.action.value,
        "publish_allowed": quality_decision.publish_allowed,
        "manual_review_required": quality_decision.manual_review_required,
        "fallback_recommended": quality_decision.fallback_recommended,
        "retry_recommended": quality_decision.retry_recommended,
        "quality_gate_decision": quality_decision.model_dump(mode="json"),
        "source_health_status": source_health.get("overall_status"),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "reason": reason,
    }
    return review_gate


def materialize_gold_runtime_agent_artifacts(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    as_of: str,
    input_snapshot_ids: dict[str, Any],
    source_refs: list[dict[str, Any]],
    canonical_paths: dict[str, str],
    source_health: dict[str, Any],
    gold_event_mainlines: dict[str, Any],
    gold_macro_overview: dict[str, Any],
    review_gate: dict[str, Any],
) -> dict[str, Any]:
    """Write lineage-only envelopes for the seven deterministic Gold stages."""

    snapshot_id = stable_gold_snapshot_id(retrieved_date=retrieved_date, run_id=run_id)
    created_at = stable_created_at(as_of)
    outputs_dir = (
        storage_root / "analysis" / "gold_mainlines" / retrieved_date / run_id / "agent_outputs"
    )
    results: dict[str, GoldArtifactWriteResult] = {}
    for agent_name, filename, artifact_type in _AGENT_FILES:
        status, confidence, data_quality = _agent_quality(
            agent_name=agent_name,
            source_health=source_health,
            gold_event_mainlines=gold_event_mainlines,
            gold_macro_overview=gold_macro_overview,
            review_gate=review_gate,
        )
        artifact = GoldAgentArtifact(
            agent_name=agent_name,
            run_id=run_id,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            source_refs=source_refs,
            artifact_refs=[
                {"artifact_type": artifact_type, "path": canonical_paths[artifact_type]}
            ],
            data_quality=data_quality,
            confidence=confidence,
            status=status,
            created_at=created_at,
        )
        results[agent_name] = write_gold_agent_artifact(
            outputs_dir / filename,
            artifact,
            storage_root=storage_root,
        )
    declared_agents = [agent_name for agent_name, _, _ in _AGENT_FILES]
    materialized_stage_envelopes = list(results)
    return {
        "snapshot_id": snapshot_id,
        "declared_agents": declared_agents,
        "materialized_stage_envelopes": materialized_stage_envelopes,
        "executed_agents": [],
        "runtime_contract_only": True,
        "artifact_paths": {
            agent_name: result.storage_relative_path for agent_name, result in results.items()
        },
        "write_results": results,
    }


def materialize_report_render_agent_artifact(
    *,
    storage_root: Path,
    trade_date: str,
    run_id: str,
    snapshot_id: str,
    created_at: datetime,
    input_snapshot_ids: dict[str, Any],
    source_refs: list[dict[str, Any]],
    report_paths: list[str],
    strategy_card_paths: list[str],
    report_artifact_type: str | None = None,
    strategy_artifact_type: str | None = None,
) -> GoldArtifactWriteResult:
    """Write the lineage-only envelope after both rendered outputs exist."""

    report_artifact_type = report_artifact_type or _artifact_type_from_paths(
        report_paths,
        allowed_types=("final_report", "observation_report"),
        artifact_label="report",
    )
    strategy_artifact_type = strategy_artifact_type or _artifact_type_from_paths(
        strategy_card_paths,
        allowed_types=("strategy_card", "observation_strategy_card"),
        artifact_label="strategy card",
    )
    _validate_render_artifact_types(
        report_artifact_type=report_artifact_type,
        strategy_artifact_type=strategy_artifact_type,
    )
    artifact_refs = [
        *[
            {
                "artifact_type": report_artifact_type,
                "path": _storage_relative(path, storage_root),
            }
            for path in report_paths
        ],
        *[
            {
                "artifact_type": strategy_artifact_type,
                "path": _storage_relative(path, storage_root),
            }
            for path in strategy_card_paths
        ],
    ]
    observation_only = report_artifact_type == "observation_report"
    artifact = GoldAgentArtifact(
        agent_name="report_render_agent",
        run_id=run_id,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        data_quality=(
            ["observation_only", "publish_not_allowed"] if observation_only else []
        ),
        confidence=0.0 if observation_only else 1.0,
        status=AgentStatus.PARTIAL if observation_only else AgentStatus.SUCCESS,
        created_at=created_at,
    )
    target = (
        storage_root
        / "analysis"
        / "gold_mainlines"
        / trade_date
        / run_id
        / "agent_outputs"
        / "report_render_output.json"
    )
    return write_gold_agent_artifact(target, artifact, storage_root=storage_root)


def _validate_render_artifact_types(
    *, report_artifact_type: str, strategy_artifact_type: str
) -> None:
    artifact_types = (report_artifact_type, strategy_artifact_type)
    if artifact_types not in {
        _FORMAL_RENDER_ARTIFACT_TYPES,
        _OBSERVATION_RENDER_ARTIFACT_TYPES,
    }:
        raise ValueError(
            "Report render artifact types must be the formal final_report/strategy_card "
            "pair or the observation_report/observation_strategy_card pair."
        )


def _artifact_type_from_paths(
    paths: list[str], *, allowed_types: tuple[str, ...], artifact_label: str
) -> str:
    """Infer legacy caller types from canonical output paths only.

    New callers must pass the writer's artifact type explicitly.  This keeps
    the existing composite caller compatible while it is upgraded, without
    allowing an observation artifact to be labelled as a formal output.
    """

    types = {
        path_parts[index + 1]
        for path in paths
        if (path_parts := Path(path).parts)
        for index, part in enumerate(path_parts[:-1])
        if part == "outputs" and path_parts[index + 1] in allowed_types
    }
    if len(types) != 1:
        raise ValueError(
            f"{artifact_label.capitalize()} artifact type must be passed explicitly "
            "when it cannot be determined from canonical output paths."
        )
    return types.pop()


def _storage_relative(path: str, storage_root: Path) -> str:
    resolved = Path(path).resolve()
    root = storage_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Rendered artifact path escapes storage root: {path}")
    return resolved.relative_to(root).as_posix()


def stable_gold_snapshot_id(*, retrieved_date: str, run_id: str) -> str:
    digest = hashlib.sha256(f"{retrieved_date}:{run_id}".encode()).hexdigest()[:20]
    return f"gold-snapshot-{digest}"


def stable_created_at(as_of: str) -> datetime:
    value = as_of.strip()
    if not value:
        raise ValueError("Gold runtime artifact as_of must not be empty")
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _agent_quality(
    *,
    agent_name: str,
    source_health: dict[str, Any],
    gold_event_mainlines: dict[str, Any],
    gold_macro_overview: dict[str, Any],
    review_gate: dict[str, Any],
) -> tuple[AgentStatus, float, list[str]]:
    if agent_name == "source_health_agent":
        health = str(source_health.get("overall_status") or "degraded")
        status = _status_from_value(health)
        confidence = {
            "ready": 1.0,
            "healthy": 1.0,
            "degraded": 0.6,
            "blocked": 0.0,
        }.get(health, 0.4)
        quality = [
            *[f"missing:{item}" for item in source_health.get("p0_missing") or []],
            *[f"warning:{item}" for item in source_health.get("warnings") or []],
        ]
        return status, confidence, quality
    if agent_name == "review_gate_agent":
        review_status = str(review_gate.get("review_status") or "needs_review")
        status = {
            "pass": AgentStatus.SUCCESS,
            "needs_review": AgentStatus.PARTIAL,
            "blocked": AgentStatus.UNAVAILABLE,
        }.get(review_status, AgentStatus.PARTIAL)
        confidence = {"pass": 1.0, "needs_review": 0.5, "blocked": 0.0}.get(review_status, 0.4)
        quality = [
            *[f"blocking:{item}" for item in review_gate.get("blocking_reasons") or []],
            *[f"warning:{item}" for item in review_gate.get("warnings") or []],
        ]
        return status, confidence, quality
    if agent_name == "gold_macro_overview_agent":
        readiness = gold_macro_overview.get("analysis_readiness") or {}
        ready = int(readiness.get("ready_count") or 0)
        total = int(readiness.get("total_count") or 0)
        confidence = ready / total if total else 0.0
        status = _status_from_value(str(gold_macro_overview.get("status") or "partial"))
        return status, round(confidence, 4), [str(item) for item in readiness.get("next_gaps") or []]

    mainlines = [
        item for item in gold_event_mainlines.get("mainlines") or [] if isinstance(item, dict)
    ]
    confidences = [
        float(item["confidence"]) for item in mainlines if item.get("confidence") is not None
    ]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    status = _status_from_value(str(gold_event_mainlines.get("status") or "partial"))
    quality = [str(item) for item in gold_event_mainlines.get("warnings") or []]
    return status, round(confidence, 4), quality


def _status_from_value(value: str) -> AgentStatus:
    if value in {"healthy", "available", "success", "ready", "pass"}:
        return AgentStatus.SUCCESS
    if value in {"blocked", "unavailable", "failed"}:
        return AgentStatus.UNAVAILABLE
    return AgentStatus.PARTIAL
