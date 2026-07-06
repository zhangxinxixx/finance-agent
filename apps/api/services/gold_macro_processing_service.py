from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.gold_mainline_engine import (
    build_gold_macro_overview as build_engine_gold_macro_overview,
    classify_mainlines,
    decompose_mixed_drivers,
)
from apps.features.news.gold_event_mainlines import build_gold_event_mainlines
from apps.gold_mainline_contract import normalize_gold_transmission_chain_id


TRACE_STAGES = (
    "raw",
    "parsed",
    "normalized",
    "attributed",
    "validated",
    "projected",
    "rendered",
)


def build_mainline_attribution(entity: dict[str, Any]) -> dict[str, Any]:
    attribution = classify_mainlines(entity)
    entity_id = _entity_id(entity)
    return {
        "entity_id": entity_id,
        "mainlines": attribution["mainlines"],
        "primary_mainline": attribution["primary_mainline"],
        "transmission_chains": attribution["transmission_chains"],
        "bullish_drivers": attribution["bullish_drivers"],
        "bearish_drivers": attribution["bearish_drivers"],
        "dominant_driver": attribution["dominant_driver"],
        "net_effect": attribution["net_effect"],
        "verification_needed": attribution["verification_needed"],
        "processing_trace_id": _trace_id(entity_id),
        "source_refs": attribution["source_refs"],
        "event_link": attribution["event_link"],
    }


def build_transmission_chains(entity: dict[str, Any]) -> list[dict[str, Any]]:
    attribution = build_mainline_attribution(entity)
    source_refs = [dict(item) for item in attribution.get("source_refs") or [] if isinstance(item, dict)]
    chains: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path_id in attribution.get("transmission_chains") or []:
        chain_id = normalize_gold_transmission_chain_id(path_id)
        if chain_id in seen:
            continue
        seen.add(chain_id)
        chains.append(
            {
                "chain_id": chain_id,
                "path_id": str(path_id),
                "status": "covered" if source_refs else "degraded",
                "source_refs": source_refs,
                "verification_needed": attribution.get("verification_needed") or [],
            }
        )
    return chains


def build_driver_decomposition(entity: dict[str, Any]) -> dict[str, Any]:
    decomposition = decompose_mixed_drivers(entity)
    return {
        "entity_id": _entity_id(entity),
        "processing_trace_id": _trace_id(_entity_id(entity)),
        **decomposition,
    }


def build_processing_trace(
    entity_id: str,
    *,
    entity: dict[str, Any] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    payload = dict(entity or {})
    refs = _merge_source_refs([source_refs or [], payload.get("source_refs") or []])
    artifacts = [dict(item) for item in (artifact_refs or payload.get("artifact_refs") or []) if isinstance(item, dict)]
    trace_warnings = [str(item) for item in warnings or []]
    if not refs:
        trace_warnings.append("source_refs_missing")
    return {
        "trace_id": _trace_id(entity_id),
        "entity_type": str(payload.get("entity_type") or payload.get("event_type") or "event"),
        "entity_id": entity_id,
        "source_refs": refs,
        "artifact_refs": artifacts,
        "stages": [
            {
                "stage_id": stage,
                "status": "covered" if refs or stage == "raw" else "degraded",
                "started_at": None,
                "finished_at": None,
                "source_refs": refs,
                "artifact_refs": artifacts,
                "warnings": trace_warnings if stage in {"validated", "rendered"} else [],
            }
            for stage in TRACE_STAGES
        ],
        "current_status": "rendered",
        "warnings": trace_warnings,
    }


def build_view_bindings(overview: dict[str, Any]) -> list[dict[str, Any]]:
    has_overview = bool(overview)
    has_rankings = bool((overview or {}).get("theme_rankings"))
    has_chain = bool((overview or {}).get("war_oil_rate_chain"))
    has_trace = bool((overview or {}).get("processing_traces"))
    return [
        {"view": "Dashboard", "status": "bound" if has_overview else "missing", "required_fields": ["gold_macro_overview"]},
        {"view": "GoldMainlinesPage", "status": "bound" if has_rankings else "missing", "required_fields": ["theme_rankings"]},
        {"view": "OilGeopoliticsPage", "status": "bound" if has_chain else "missing", "required_fields": ["war_oil_rate_chain"]},
        {"view": "Reports", "status": "bound" if has_overview else "missing", "required_fields": ["gold_macro_overview"]},
        {"view": "ProcessingMonitor", "status": "bound" if has_trace else "missing", "required_fields": ["processing_traces"]},
        {"view": "SourceTrace", "status": "bound" if (overview or {}).get("source_refs") else "missing", "required_fields": ["source_refs"]},
    ]


def build_gold_macro_overview(
    *,
    events: list[dict[str, Any]] | None = None,
    impact_assessments: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
    asset: str = "XAUUSD",
    macro_context: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    oil_context: dict[str, Any] | None = None,
    flow_context: dict[str, Any] | None = None,
    reserve_context: dict[str, Any] | None = None,
    asia_context: dict[str, Any] | None = None,
    positioning_context: dict[str, Any] | None = None,
    policy_context: dict[str, Any] | None = None,
    geopolitical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_rows = [dict(item) for item in events or [] if isinstance(item, dict)]
    impact_rows = [dict(item) for item in impact_assessments or event_rows if isinstance(item, dict)]
    generated_at = as_of or datetime.now(timezone.utc).isoformat()
    bundle = build_gold_event_mainlines(
        event_rows,
        impact_assessments=impact_rows,
        as_of=generated_at,
        asset=asset,
    )
    overview = build_engine_gold_macro_overview(
        bundle,
        macro_context=macro_context,
        market_context=market_context,
        oil_context=oil_context,
        flow_context=flow_context,
        reserve_context=reserve_context,
        asia_context=asia_context,
        positioning_context=positioning_context,
        policy_context=policy_context,
        geopolitical_context=geopolitical_context,
    ).to_dict()
    traces = [
        build_processing_trace(
            _entity_id(event),
            entity=event,
            source_refs=[dict(item) for item in event.get("source_refs") or [] if isinstance(item, dict)],
        )
        for event in event_rows
    ]
    overview["processing_traces"] = traces
    overview["view_bindings"] = build_view_bindings(overview)
    return {
        "status": overview.get("status") or "partial",
        "asset": asset,
        "as_of": overview.get("as_of") or generated_at,
        "gold_macro_overview": overview,
        "gold_mainlines": bundle.to_dict(),
        "processing_traces": traces,
        "view_bindings": overview["view_bindings"],
        "source_refs": _merge_source_refs([overview.get("source_refs") or [], bundle.to_dict().get("source_refs") or []]),
        "warnings": [str(item) for item in overview.get("warnings") or []],
    }


def _entity_id(entity: dict[str, Any]) -> str:
    return str(entity.get("event_id") or entity.get("input_id") or entity.get("id") or "entity:unknown")


def _trace_id(entity_id: str) -> str:
    normalized = str(entity_id or "entity:unknown").replace("/", ":")
    return normalized if normalized.startswith("trace:") else f"trace:{normalized}"


def _merge_source_refs(ref_groups: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in ref_groups:
        for ref in group or []:
            if not isinstance(ref, dict):
                continue
            key = tuple(sorted((str(k), str(v)) for k, v in ref.items()))
            if key in seen:
                continue
            seen.add(key)
            refs.append(dict(ref))
    return refs
