from __future__ import annotations

import copy
from typing import Any

from apps.analysis.state.schemas import (
    DataCompletenessSummary,
    MarketState,
    ModuleState,
    SourceQualitySummary,
)

MARKET_STATE_VERSION = "1.0"
MARKET_STATE_MODULES = ("macro", "options", "technical", "positioning", "news", "market_odds")


def build_market_state(snapshot: dict[str, Any]) -> MarketState:
    """Build the typed decision input layer from an AnalysisSnapshot dict.

    This reducer is pure: no network calls, file reads, or LLM calls.
    Missing sections are represented as explicit unavailable module states.
    """

    module_states = {module: _module_state(snapshot, module) for module in MARKET_STATE_MODULES}
    source_refs = _source_refs(snapshot)
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    snapshot_id = _required_str(snapshot, "snapshot_id")
    input_snapshot_ids.setdefault("analysis_snapshot", snapshot_id)

    completeness = _data_completeness(module_states)
    return MarketState(
        version=MARKET_STATE_VERSION,
        asset=_required_str(snapshot, "asset"),
        trade_date=_required_str(snapshot, "trade_date"),
        run_id=_required_str(snapshot, "run_id"),
        snapshot_id=snapshot_id,
        macro=module_states["macro"],
        options=module_states["options"],
        technical=module_states["technical"],
        positioning=module_states["positioning"],
        news=module_states["news"],
        market_odds=module_states["market_odds"],
        source_quality=_source_quality(source_refs),
        data_completeness=completeness,
        unavailable_modules=list(completeness.unavailable_modules),
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )


def _module_state(snapshot: dict[str, Any], module: str) -> ModuleState:
    raw = snapshot.get(module)
    if not isinstance(raw, dict):
        return ModuleState(status="unavailable", reason="section_missing")

    status = str(raw.get("status") or "unavailable")
    data = raw.get("data")
    if isinstance(data, dict):
        state_data = copy.deepcopy(data)
    else:
        state_data = {
            str(key): copy.deepcopy(value)
            for key, value in raw.items()
            if key not in {"status", "reason"} and value is not None
        }
    reason = raw.get("reason")
    return ModuleState(
        status=status,
        data=state_data,
        reason=str(reason) if reason is not None else None,
    )


def _source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs = snapshot.get("source_refs")
    if not isinstance(refs, list):
        return []
    return [copy.deepcopy(ref) for ref in refs if isinstance(ref, dict)]


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    input_ids = snapshot.get("input_snapshot_ids")
    if not isinstance(input_ids, dict):
        return {}
    return copy.deepcopy(input_ids)


def _source_quality(source_refs: list[dict[str, Any]]) -> SourceQualitySummary:
    sources = sorted(
        {
            str(ref.get("source")).strip()
            for ref in source_refs
            if ref.get("source") is not None and str(ref.get("source")).strip()
        }
    )
    missing_source_count = sum(1 for ref in source_refs if not str(ref.get("source") or "").strip())
    return SourceQualitySummary(
        total_refs=len(source_refs),
        sources=sources,
        missing_source_count=missing_source_count,
    )


def _data_completeness(module_states: dict[str, ModuleState]) -> DataCompletenessSummary:
    available_modules = [
        module
        for module in MARKET_STATE_MODULES
        if module_states[module].status == "available"
    ]
    unavailable_modules = [
        module
        for module in MARKET_STATE_MODULES
        if module not in available_modules
    ]
    total = len(MARKET_STATE_MODULES)
    available_count = len(available_modules)
    return DataCompletenessSummary(
        total_modules=total,
        available_count=available_count,
        unavailable_count=len(unavailable_modules),
        coverage_ratio=round(available_count / total, 3),
        available_modules=available_modules,
        unavailable_modules=unavailable_modules,
    )


def _required_str(snapshot: dict[str, Any], key: str) -> str:
    value = snapshot.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"AnalysisSnapshot missing required field: {key}")
    return str(value)
