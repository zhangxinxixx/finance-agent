"""Read-only contract service for canonical premarket step topology."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from apps.api.services.source_service import get_data_source_status_index
from apps.premarket import (
    PREMARKET_STEP_ORDER,
    evaluate_premarket_step_readiness,
    get_premarket_pipeline_contract,
    get_premarket_step_contract,
    get_premarket_step_contracts,
)
from apps.runtime.source_controls import jin10_disabled


_JIN10_PREMARKET_SOURCE_KEYS = frozenset(
    {
        "jin10_news",
        "jin10_flash",
        "jin10_mcp_calendar",
    }
)


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
    disabled_sources: set[str] = set()
    jin10_is_disabled = jin10_disabled()

    steps: list[dict[str, Any]] = []
    for step_contract in get_premarket_step_contracts():
        step_disabled_sources = tuple(
            source_key
            for source_key in step_contract.required_sources
            if jin10_is_disabled and source_key in _JIN10_PREMARKET_SOURCE_KEYS
        )
        effective_contract = replace(
            step_contract,
            required_sources=tuple(
                source_key
                for source_key in step_contract.required_sources
                if source_key not in step_disabled_sources
            ),
        )
        readiness = evaluate_premarket_step_readiness(effective_contract, source_status_index)
        decision = readiness.decision
        gating_reason = readiness.gating_reason
        if step_disabled_sources and decision != "blocked":
            decision = "degraded_allowed"
            gating_reason = "required_source_disabled_allowed"

        decision_counts[decision] += 1
        if decision == "blocked":
            blocked_steps.append(step_contract.name)
        elif decision == "degraded_allowed":
            degraded_steps.append(step_contract.name)

        blocked_sources.update(readiness.blocked_sources)
        degraded_sources.update(readiness.degraded_sources)
        disabled_sources.update(step_disabled_sources)

        step_view = step_contract.to_dict()
        step_view["source_readiness"] = {
            "decision": decision,
            "gating_reason": gating_reason,
            "required_sources": list(step_contract.required_sources),
            "effective_required_sources": list(readiness.required_sources),
            "disabled_sources": list(step_disabled_sources),
            "degraded_sources": list(readiness.degraded_sources),
            "blocked_sources": list(readiness.blocked_sources),
        }
        steps.append(step_view)

    return {
        "step_order": list(PREMARKET_STEP_ORDER),
        "steps": steps,
        "source_readiness_summary": {
            "decision_counts": decision_counts,
            "blocked_steps": blocked_steps,
            "degraded_steps": degraded_steps,
            "blocked_sources": sorted(blocked_sources),
            "degraded_sources": sorted(degraded_sources),
            "jin10_disabled": jin10_is_disabled,
            "disabled_sources": sorted(disabled_sources),
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
