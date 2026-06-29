"""Read-only contract service for canonical premarket step topology."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.api.services.source_service import get_data_source_status_index
from apps.premarket import (
    PREMARKET_STEP_ORDER,
    PremarketStepContract,
    evaluate_premarket_step_readiness,
    get_premarket_pipeline_contract,
    get_premarket_step_contract,
    get_premarket_step_contracts,
)


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _resolve_source_latest_update_time(
    source_key: str,
    source_status_index: dict[str, dict[str, Any]],
) -> datetime | None:
    """Extract the best-known latest_update_time for a source from the status index."""
    source = source_status_index.get(source_key)
    if source is None:
        return None
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    # Try the top-level latest_update_time first, then metadata alternatives
    for candidate in (
        source.get("latest_update_time"),
        source.get("latest_parsed_time"),
        source.get("latest_raw_time"),
        metadata.get("as_of"),
        metadata.get("latest_as_of"),
        metadata.get("written_at"),
        metadata.get("latest_artifact_mtime"),
    ):
        parsed = _parse_iso_datetime(candidate)
        if parsed is not None:
            return parsed
    return None


def _compute_freshness_annotation(
    contract: PremarketStepContract,
    source_status_index: dict[str, dict[str, Any]],
) -> str:
    """Compute freshness annotation for a step per issue #15 rules."""
    sla = contract.freshness_sla_seconds
    if sla is None:
        return "not_applicable"

    required_sources = tuple(contract.required_sources)
    if not required_sources:
        return "not_applicable"

    now = datetime.now(timezone.utc)
    known_timestamps: list[datetime] = []
    for source_key in required_sources:
        ts = _resolve_source_latest_update_time(source_key, source_status_index)
        if ts is not None:
            known_timestamps.append(ts)

    if not known_timestamps:
        return "unknown"

    for ts in known_timestamps:
        if (now - ts).total_seconds() > sla:
            return "stale"

    return "fresh"


def _compute_quality_score(
    steps: list[dict[str, Any]],
) -> float:
    """Compute pipeline quality score from step readiness decisions."""
    score = 1.0
    for step_view in steps:
        weight = float(step_view.get("quality_weight", 0.0))
        decision = step_view.get("source_readiness", {}).get("decision", "ready")
        if decision == "blocked":
            score -= weight
        elif decision == "degraded_allowed":
            score -= weight * 0.5
    return round(max(0.0, min(1.0, score)), 4)


def build_premarket_pipeline_source_readiness() -> dict[str, Any]:
    """Return the current source-readiness read model for the canonical premarket DAG."""
    try:
        source_status_index = get_data_source_status_index()
    except Exception:
        source_status_index = {}

    decision_counts = {
        "ready": 0,
        "degraded_allowed": 0,
        "blocked": 0,
    }
    blocked_steps: list[str] = []
    degraded_steps: list[str] = []
    blocked_sources: set[str] = set()
    degraded_sources: set[str] = set()
    critical_blocked_steps: list[str] = []
    stale_steps: list[str] = []

    steps: list[dict[str, Any]] = []
    for step_contract in get_premarket_step_contracts():
        readiness = evaluate_premarket_step_readiness(step_contract, source_status_index)
        decision_counts[readiness.decision] += 1
        if readiness.decision == "blocked":
            blocked_steps.append(step_contract.name)
        elif readiness.decision == "degraded_allowed":
            degraded_steps.append(step_contract.name)

        blocked_sources.update(readiness.blocked_sources)
        degraded_sources.update(readiness.degraded_sources)

        freshness_annotation = _compute_freshness_annotation(step_contract, source_status_index)
        if freshness_annotation == "stale":
            stale_steps.append(step_contract.name)

        step_view = step_contract.to_dict()
        step_view["source_readiness"] = {
            "decision": readiness.decision,
            "gating_reason": readiness.gating_reason,
            "required_sources": list(readiness.required_sources),
            "degraded_sources": list(readiness.degraded_sources),
            "blocked_sources": list(readiness.blocked_sources),
            "freshness_annotation": freshness_annotation,
        }
        steps.append(step_view)

    for step_view in steps:
        if (
            step_view.get("source_readiness", {}).get("decision") == "blocked"
            and step_view.get("criticality") == "critical"
        ):
            critical_blocked_steps.append(step_view["name"])

    quality_score = _compute_quality_score(steps)

    return {
        "step_order": list(PREMARKET_STEP_ORDER),
        "steps": steps,
        "source_readiness_summary": {
            "decision_counts": decision_counts,
            "blocked_steps": blocked_steps,
            "degraded_steps": degraded_steps,
            "blocked_sources": sorted(blocked_sources),
            "degraded_sources": sorted(degraded_sources),
            "quality_score": quality_score,
            "critical_blocked_steps": critical_blocked_steps,
            "stale_steps": stale_steps,
        },
    }


def build_premarket_pipeline_contract() -> dict[str, Any]:
    """Return the canonical premarket DAG contract as an API-friendly payload."""
    contract = get_premarket_pipeline_contract()
    readiness = build_premarket_pipeline_source_readiness()
    contract["steps"] = readiness["steps"]
    contract["source_readiness_summary"] = readiness["source_readiness_summary"]
    return contract


def get_premarket_step_contract_view(step_name: str) -> dict[str, Any] | None:
    """Return one canonical premarket step contract as a plain dict."""
    contract = get_premarket_step_contract(step_name)
    return None if contract is None else contract.to_dict()
