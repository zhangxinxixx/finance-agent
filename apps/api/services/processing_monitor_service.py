from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.gold_mainline_service import get_gold_mainlines_latest
from apps.contracts.gold import (
    GOLD_MAINLINE_IDS,
    GOLD_TRANSMISSION_CHAIN_IDS,
    normalize_gold_mainline_id,
    normalize_gold_transmission_chain_id,
)

TRACE_MODES = [
    "source_ref",
    "event_id",
    "input_id",
    "processing_trace_id",
    "mainline",
    "transmission_chain",
]

MAINLINES = list(GOLD_MAINLINE_IDS)
TRANSMISSION_CHAINS = list(GOLD_TRANSMISSION_CHAIN_IDS)

TRACE_PATH = [
    {"node_id": "source_health_check", "label": "Source Health", "stage": "health"},
    {"node_id": "jin10_message_raw", "label": "Jin10 Raw", "stage": "raw"},
    {"node_id": "jin10_flash_parse", "label": "Jin10 Parse", "stage": "parse"},
    {"node_id": "event_flow_feature", "label": "EventFlow", "stage": "feature"},
    {"node_id": "mainline_attribution", "label": "Mainline Attribution", "stage": "agent"},
    {"node_id": "transmission_chain_detection", "label": "Transmission Chain", "stage": "agent"},
    {"node_id": "driver_decomposition", "label": "Driver Decomposition", "stage": "agent"},
    {"node_id": "gold_macro_overview", "label": "GoldMacroOverview", "stage": "read_model"},
    {"node_id": "review_gate", "label": "ReviewGate", "stage": "quality_gate"},
    {"node_id": "dashboard", "label": "Dashboard", "stage": "frontend"},
    {"node_id": "gold_mainlines_page", "label": "GoldMainlinesPage", "stage": "frontend"},
    {"node_id": "oil_geopolitics_page", "label": "OilGeopoliticsPage", "stage": "frontend"},
    {"node_id": "reports", "label": "Reports", "stage": "frontend"},
    {"node_id": "strategy", "label": "Strategy", "stage": "frontend"},
    {"node_id": "source_trace", "label": "SourceTrace", "stage": "frontend"},
]


def get_processing_overview(*, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    gold_payload = context["gold_payload"]
    overview = context["overview"]
    mainlines_payload = context["mainlines_payload"]
    event_links = context["event_links"]
    source_refs = context["source_refs"]
    artifact_refs = context["artifact_refs"]
    source_health = _artifact_source_health(overview=overview)
    read_time_source_health = _dict(gold_payload.get("read_time_source_health"))

    return {
        "status": str(gold_payload.get("status") or "unavailable"),
        "date": gold_payload.get("date"),
        "run_id": gold_payload.get("run_id"),
        "asset": overview.get("asset") or "XAUUSD",
        "generated_from": gold_payload.get("artifact_path"),
        "trace_modes": TRACE_MODES,
        "trace_path": _trace_path(
            gold_payload=gold_payload,
            overview=overview,
            event_links=event_links,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            source_health=source_health,
        ),
        "input_coverage": _input_coverage(event_links=event_links, source_refs=source_refs, artifact_refs=artifact_refs),
        "mainline_coverage": _mainline_coverage(
            overview=overview,
            mainlines_payload=mainlines_payload,
            explicit_overview_mainlines=_raw_overview_mainlines(root=root, artifact_path=gold_payload.get("artifact_path")),
        ),
        "transmission_chain_coverage": _transmission_chain_coverage(overview=overview, event_links=event_links),
        "mixed_health": _mixed_health(overview=overview),
        "source_freshness": _source_freshness(source_health=source_health),
        "source_health": source_health,
        "quality_gate": _quality_gate(overview=overview),
        "read_time_source_health": read_time_source_health,
        "read_time_warnings": list(gold_payload.get("read_time_warnings") or []),
        "read_time_generated_at": gold_payload.get("read_time_generated_at") or datetime.now(timezone.utc).isoformat(),
        "view_bindings": _view_bindings(gold_payload=gold_payload, overview=overview, event_links=event_links, source_refs=source_refs),
        "source_refs": source_refs,
        "artifact_refs": artifact_refs,
        "warnings": list(gold_payload.get("warnings") or []),
    }


def get_processing_trace(trace_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    event = _find_event_link(context["event_links"], processing_trace_id=trace_id)
    return _trace_payload(context=context, event=event, query={"processing_trace_id": trace_id})


def get_processing_trace_by_event(event_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    event = _find_event_link(context["event_links"], event_id=event_id)
    return _trace_payload(context=context, event=event, query={"event_id": event_id})


def get_processing_trace_by_input(input_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    event = _find_event_link(context["event_links"], input_id=input_id)
    return _trace_payload(context=context, event=event, query={"input_id": input_id})


def get_processing_trace_by_source_ref(source_ref: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    event = _find_event_link(context["event_links"], source_ref=source_ref)
    return _trace_payload(context=context, event=event, query={"source_ref": source_ref})


def get_processing_trace_by_mainline(mainline: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    canonical = _canonical_mainline(mainline)
    event = _find_event_link(context["event_links"], mainline=canonical)
    return _trace_payload(context=context, event=event, query={"mainline": canonical or mainline})


def get_processing_trace_by_transmission_chain(chain_id: str, *, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    context = _load_processing_context(root=root)
    canonical = _canonical_transmission_chain(chain_id)
    event = _find_event_link(context["event_links"], transmission_chain=canonical)
    return _trace_payload(context=context, event=event, query={"transmission_chain": canonical})


def _load_processing_context(*, root: Path) -> dict[str, Any]:
    gold_payload = get_gold_mainlines_latest(project_root=root)
    overview = _dict(gold_payload.get("gold_macro_overview"))
    mainlines_payload = _dict(gold_payload.get("gold_mainlines"))
    event_links = [item for item in mainlines_payload.get("event_links") or [] if isinstance(item, dict)]
    source_refs = _unique_refs(
        [
            *_list_of_dicts(gold_payload.get("source_refs")),
            *_list_of_dicts(overview.get("source_refs")),
            *_list_of_dicts(mainlines_payload.get("source_refs")),
            *[ref for item in event_links for ref in _list_of_dicts(item.get("source_refs"))],
        ],
        key="source_ref",
    )
    artifact_refs = _unique_refs(_list_of_dicts(overview.get("artifact_refs")), key="file_path")
    return {
        "gold_payload": gold_payload,
        "overview": overview,
        "mainlines_payload": mainlines_payload,
        "event_links": event_links,
        "source_refs": source_refs,
        "artifact_refs": artifact_refs,
    }


def _find_event_link(
    event_links: list[dict[str, Any]],
    *,
    processing_trace_id: str | None = None,
    event_id: str | None = None,
    input_id: str | None = None,
    source_ref: str | None = None,
    mainline: str | None = None,
    transmission_chain: str | None = None,
) -> dict[str, Any] | None:
    for event in event_links:
        if processing_trace_id and str(event.get("processing_trace_id") or "") == processing_trace_id:
            return event
        if event_id and str(event.get("event_id") or "") == event_id:
            return event
        if input_id and str(event.get("input_id") or "") == input_id:
            return event
        if source_ref and any(str(ref.get("source_ref") or "") == source_ref for ref in _list_of_dicts(event.get("source_refs"))):
            return event
        if mainline and mainline in _event_mainlines(event):
            return event
        if transmission_chain and transmission_chain in _event_transmission_chains(event):
            return event
    return None


def _trace_payload(*, context: dict[str, Any], event: dict[str, Any] | None, query: dict[str, str]) -> dict[str, Any]:
    gold_payload = context["gold_payload"]
    overview = context["overview"]
    source_health = _artifact_source_health(overview=overview)
    read_time_source_health = _dict(gold_payload.get("read_time_source_health"))
    if event is None:
        return {
            "status": "not_found",
            "date": gold_payload.get("date"),
            "run_id": gold_payload.get("run_id"),
            "query": query,
            "matched_event": None,
            "trace_path": _trace_path(
                gold_payload=gold_payload,
                overview=overview,
                event_links=[],
                source_refs=[],
                artifact_refs=context["artifact_refs"],
                source_health=source_health,
            ),
            "source_health": source_health,
            "quality_gate": _quality_gate(overview=overview),
            "read_time_source_health": read_time_source_health,
            "read_time_warnings": list(gold_payload.get("read_time_warnings") or []),
            "read_time_generated_at": gold_payload.get("read_time_generated_at") or datetime.now(timezone.utc).isoformat(),
            "source_refs": [],
            "artifact_refs": context["artifact_refs"],
            "view_bindings": _view_bindings(gold_payload=gold_payload, overview=overview, event_links=[], source_refs=[]),
        }

    event_source_refs = _unique_refs(_list_of_dicts(event.get("source_refs")), key="source_ref")
    trace_id = str(event.get("processing_trace_id") or query.get("processing_trace_id") or event.get("event_id") or "")
    response_query = {
        "processing_trace_id": trace_id,
        "event_id": str(event.get("event_id") or query.get("event_id") or ""),
        "input_id": str(event.get("input_id") or query.get("input_id") or ""),
        "source_ref": event_source_refs[0].get("source_ref") if event_source_refs else query.get("source_ref"),
    }
    return {
        "status": "matched",
        "date": gold_payload.get("date"),
        "run_id": gold_payload.get("run_id"),
        "asset": overview.get("asset") or "XAUUSD",
        "query": response_query,
        "matched_event": {
            "event_id": event.get("event_id"),
            "input_id": event.get("input_id"),
            "primary_mainline": _canonical_mainline(event.get("primary_mainline")),
            "processing_trace_id": trace_id,
        },
        "mainlines": _event_mainlines(event),
        "transmission_chains": _event_transmission_chains(event),
        "trace_path": _trace_path(
            gold_payload=gold_payload,
            overview=overview,
            event_links=[event],
            source_refs=event_source_refs,
            artifact_refs=context["artifact_refs"],
            source_health=source_health,
        ),
        "source_health": source_health,
        "quality_gate": _quality_gate(overview=overview),
        "read_time_source_health": read_time_source_health,
        "read_time_warnings": list(gold_payload.get("read_time_warnings") or []),
        "read_time_generated_at": gold_payload.get("read_time_generated_at") or datetime.now(timezone.utc).isoformat(),
        "source_refs": event_source_refs,
        "artifact_refs": context["artifact_refs"],
        "view_bindings": _view_bindings(gold_payload=gold_payload, overview=overview, event_links=[event], source_refs=event_source_refs),
    }


def _event_mainlines(event: dict[str, Any]) -> list[str]:
    return [
        mainline_id
        for mainline_id in (_canonical_mainline(item) for item in event.get("mainline_ids") or [event.get("primary_mainline")])
        if mainline_id is not None
    ]


def _event_transmission_chains(event: dict[str, Any]) -> list[str]:
    return _unique_strings(
        _canonical_transmission_chain(item)
        for item in event.get("transmission_path_ids") or event.get("transmission_chains") or []
    )


def _trace_path(
    *,
    gold_payload: dict[str, Any],
    overview: dict[str, Any],
    event_links: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    artifact_refs: list[dict[str, Any]],
    source_health: dict[str, Any],
) -> list[dict[str, Any]]:
    has_events = bool(event_links)
    has_source_refs = bool(source_refs)
    has_overview = bool(overview) and str(gold_payload.get("status") or "") != "unavailable"
    has_mainlines = any(_event_mainlines(event) for event in event_links)
    has_transmission_chains = any(_event_transmission_chains(event) for event in event_links) or bool(overview.get("war_oil_rate_chain"))
    mixed_status = str(_mixed_health(overview=overview).get("status") or "missing")
    quality_gate_status = str(_quality_gate(overview=overview).get("status") or "missing")
    binding_status = {
        item["view"]: item["status"]
        for item in _view_bindings(
            gold_payload=gold_payload,
            overview=overview,
            event_links=event_links,
            source_refs=source_refs,
        )
    }
    frontend_node_views = {
        "dashboard": "Dashboard",
        "gold_mainlines_page": "GoldMainlinesPage",
        "oil_geopolitics_page": "OilGeopoliticsPage",
        "reports": "Reports",
        "strategy": "Strategy",
        "source_trace": "SourceTrace",
    }

    result: list[dict[str, Any]] = []
    for node in TRACE_PATH:
        node_id = node["node_id"]
        status = "missing"
        source_ref_count = 0
        artifact_ref_count = 0

        if node_id == "source_health_check":
            status = _coverage_from_source_health(source_health)
        elif node_id == "jin10_message_raw":
            status = "covered" if has_source_refs else "missing"
            source_ref_count = len(source_refs)
        elif node_id == "jin10_flash_parse":
            status = "covered" if has_events else "missing"
            source_ref_count = len(source_refs)
        elif node_id == "event_flow_feature":
            status = "covered" if has_events else "missing"
            source_ref_count = len(source_refs)
        elif node_id == "mainline_attribution":
            status = "covered" if has_mainlines else "missing"
            source_ref_count = len(source_refs)
        elif node_id == "transmission_chain_detection":
            status = "covered" if has_transmission_chains else "missing"
            source_ref_count = len(source_refs)
        elif node_id == "driver_decomposition":
            status = "covered" if mixed_status == "pass" else mixed_status
            source_ref_count = len(source_refs)
        elif node_id == "gold_macro_overview":
            status = "covered" if has_overview else "missing"
            source_ref_count = len(source_refs)
            artifact_ref_count = len(artifact_refs)
        elif node_id == "review_gate":
            status = quality_gate_status
            source_ref_count = len(source_refs)
            artifact_ref_count = len(artifact_refs)
        elif node_id in frontend_node_views:
            status = "covered" if binding_status.get(frontend_node_views[node_id]) == "bound" else "missing"
            source_ref_count = len(source_refs) if node_id == "source_trace" else 0
            artifact_ref_count = len(artifact_refs)

        result.append(
            {
                **node,
                "status": status,
                "source_ref_count": source_ref_count,
                "artifact_ref_count": artifact_ref_count,
            }
        )
    return result


def _input_coverage(*, event_links: list[dict[str, Any]], source_refs: list[dict[str, Any]], artifact_refs: list[dict[str, Any]]) -> dict[str, int]:
    without_source_ref = sum(1 for item in event_links if not _list_of_dicts(item.get("source_refs")))
    return {
        "news_input_count": len(event_links),
        "report_input_count": 0,
        "followup_count": 0,
        "article_brief_count": 0,
        "source_ref_count": len(source_refs),
        "artifact_ref_count": len(artifact_refs),
        "without_source_ref_count": without_source_ref,
    }


def _mainline_coverage(
    *,
    overview: dict[str, Any],
    mainlines_payload: dict[str, Any],
    explicit_overview_mainlines: set[str],
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _list_of_dicts(overview.get("theme_rankings")) + _list_of_dicts(mainlines_payload.get("mainlines")):
        mainline_id = _canonical_mainline(row.get("mainline_id") or row.get("mainline"))
        if mainline_id is None:
            continue
        rows.setdefault(mainline_id, {}).update(row)

    coverage = []
    for mainline_id in MAINLINES:
        row = rows.get(mainline_id, {})
        missing_data = list(row.get("missing_data") or [])
        source_refs = _list_of_dicts(row.get("source_refs"))
        event_ids = list(row.get("event_ids") or row.get("related_event_ids") or [])
        explicitly_present = mainline_id in explicit_overview_mainlines
        if not row or (not explicitly_present and not source_refs and not event_ids):
            status = "missing"
        elif str(row.get("status") or "").lower() in {"stale", "degraded"}:
            status = str(row.get("status")).lower()
        elif missing_data or str(row.get("verification_status") or "").lower() in {"stale", "degraded", "unavailable"}:
            status = "degraded"
        else:
            status = "covered"
        coverage.append(
            {
                "mainline_id": mainline_id,
                "status": status,
                "event_count": len(event_ids),
                "source_ref_count": len(source_refs),
                "missing_data": missing_data,
            }
        )
    return coverage


def _transmission_chain_coverage(*, overview: dict[str, Any], event_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {
        _canonical_transmission_chain(chain)
        for item in event_links
        for chain in item.get("transmission_path_ids") or item.get("transmission_chains") or []
    }
    war_chain = _dict(overview.get("war_oil_rate_chain"))
    coverage = []
    for chain_id in TRANSMISSION_CHAINS:
        if chain_id == "war_oil_rate_chain" and war_chain:
            status = _coverage_from_status(war_chain)
            verification_needed = list(war_chain.get("verification_needed") or [])
        elif chain_id in seen:
            status = "covered"
            verification_needed = []
        else:
            status = "missing"
            verification_needed = []
        coverage.append(
            {
                "chain_id": chain_id,
                "status": status,
                "verification_needed": verification_needed,
            }
        )
    return coverage


def _mixed_health(*, overview: dict[str, Any]) -> dict[str, Any]:
    conflict = _dict(overview.get("driver_conflict"))
    is_mixed = "mixed" in str(conflict.get("status") or conflict.get("net_effect") or "").lower()
    total = 1 if is_mixed else 0
    missing_bullish = 1 if is_mixed and not conflict.get("bullish_drivers") else 0
    missing_bearish = 1 if is_mixed and not conflict.get("bearish_drivers") else 0
    missing_dominant = 1 if is_mixed and not conflict.get("dominant_driver") else 0
    missing_verification = 1 if is_mixed and not conflict.get("verification_needed") else 0
    status = "pass"
    if missing_bullish or missing_bearish or missing_dominant:
        status = "blocked"
    elif total and (missing_verification or conflict.get("verification_needed")):
        status = "needs_review"
    return {
        "status": status,
        "mixed_events_total": total,
        "mixed_without_bullish_drivers": missing_bullish,
        "mixed_without_bearish_drivers": missing_bearish,
        "mixed_without_dominant_driver": missing_dominant,
        "mixed_without_verification_needed": missing_verification,
    }


def _artifact_source_health(*, overview: dict[str, Any]) -> dict[str, Any]:
    source_health = overview.get("source_health")
    if isinstance(source_health, dict):
        return dict(source_health)
    return {
        "overall_status": "unavailable",
        "as_of": str(overview.get("as_of") or "") or None,
        "p0_missing": [],
        "p1_missing": [],
        "p2_missing": [],
        "stale_sources": [],
        "fresh_sources": [],
        "source_freshness": {},
        "mainline_impact": {},
        "can_build_gold_macro_overview": True,
        "can_emit_strong_conclusion": True,
        "blocked_mainlines": [],
        "degraded_mainlines": [],
        "blocking_reasons": [],
        "warnings": ["artifact source_health unavailable; read_time_source_health is exposed separately"],
    }


def _quality_gate(*, overview: dict[str, Any]) -> dict[str, Any]:
    review_gate = _dict(overview.get("review_gate"))
    if not review_gate:
        return {
            "status": "missing",
            "review_status": "missing",
            "quality_gate_action": None,
            "publish_allowed": None,
            "manual_review_required": None,
            "fallback_recommended": None,
            "retry_recommended": None,
            "fallback_actions": [],
            "fallback_reasons": [],
            "agent_loop_decision": {},
            "fallback_review": _fallback_review(review_gate={}),
            "blocking_reasons": [],
            "warnings": ["artifact review_gate unavailable"],
        }
    decision = _dict(review_gate.get("quality_gate_decision"))
    agent_loop_decision = _dict(review_gate.get("agent_loop_decision"))
    review_status = str(review_gate.get("review_status") or "needs_review")
    return {
        "status": _coverage_from_review_status(review_status),
        "review_status": review_status,
        "quality_gate_action": review_gate.get("quality_gate_action"),
        "publish_allowed": review_gate.get("publish_allowed"),
        "manual_review_required": review_gate.get("manual_review_required"),
        "fallback_recommended": review_gate.get("fallback_recommended"),
        "retry_recommended": review_gate.get("retry_recommended"),
        "fallback_actions": list(decision.get("fallback_actions") or agent_loop_decision.get("fallback_tasks") or []),
        "fallback_reasons": list(agent_loop_decision.get("reasons") or []),
        "agent_loop_decision": agent_loop_decision,
        "fallback_review": _fallback_review(review_gate=review_gate),
        "blocking_reasons": list(review_gate.get("blocking_reasons") or []),
        "warnings": list(review_gate.get("warnings") or []),
    }


def _fallback_review(*, review_gate: dict[str, Any]) -> dict[str, Any]:
    agent_loop_decision = _dict(review_gate.get("agent_loop_decision"))
    fallback_trace = _dict(agent_loop_decision.get("fallback_trace"))
    fallback_outputs = _dict(review_gate.get("fallback_outputs"))
    return {
        "status": str(review_gate.get("review_status") or "missing"),
        "fallback_used": bool(fallback_trace.get("fallback_used")),
        "accepted_output": fallback_trace.get("accepted_output"),
        "manual_review_required": bool(review_gate.get("manual_review_required")),
        "primary_outputs": _unique_strings(str(item) for item in agent_loop_decision.get("fallback_of") or []),
        "fallback_outputs": _fallback_output_summaries(fallback_outputs),
        "accepted_outputs": _dict(agent_loop_decision.get("accepted_outputs")),
        "task_results": _list_of_dicts(review_gate.get("fallback_task_results")),
        "reasons": _unique_strings(str(item) for item in agent_loop_decision.get("reasons") or []),
        "review_items": _list_of_dicts(fallback_trace.get("review_items")),
    }


def _fallback_output_summaries(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for agent_name, payload in outputs.items():
        if not isinstance(payload, dict):
            continue
        summary = {
            "agent_name": str(payload.get("agent_name") or agent_name),
            "snapshot_id": payload.get("snapshot_id"),
            "bias": payload.get("bias"),
            "confidence": payload.get("confidence"),
            "summary": payload.get("summary"),
        }
        summaries.append({key: value for key, value in summary.items() if value is not None})
    return summaries


def _coverage_from_review_status(review_status: str) -> str:
    status = review_status.lower()
    if status == "pass":
        return "covered"
    if status == "blocked":
        return "blocked"
    if status == "needs_review":
        return "needs_review"
    return "missing"


def _coverage_from_source_health(source_health: dict[str, Any]) -> str:
    status = str(source_health.get("overall_status") or "").lower()
    if status == "ready":
        return "covered"
    if status == "blocked":
        return "blocked"
    if status == "degraded":
        return "degraded"
    return "missing"


def _source_freshness(*, source_health: dict[str, Any]) -> dict[str, str]:
    p0_missing = len(source_health.get("p0_missing") or [])
    stale_sources = len(source_health.get("stale_sources") or [])
    return {
        "source_freshness": f"{source_health.get('overall_status') or 'unknown'}; p0_missing={p0_missing}; stale={stale_sources}",
        "feature_freshness": "derived_from_artifacts",
        "analysis_freshness": "derived_from_gold_macro_overview",
        "frontend_freshness": "derived_from_view_bindings",
    }


def _view_bindings(*, gold_payload: dict[str, Any], overview: dict[str, Any], event_links: list[dict[str, Any]], source_refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    has_overview = bool(overview) and str(gold_payload.get("status") or "") != "unavailable"
    has_events = bool(event_links)
    has_trace = bool(source_refs)
    bindings = {
        "Dashboard": has_overview,
        "GoldMainlinesPage": has_overview,
        "OilGeopoliticsPage": has_overview and bool(overview.get("war_oil_rate_chain")),
        "EventFlow": has_events,
        "Reports": has_overview,
        "Strategy": has_overview,
        "SourceTrace": has_trace,
    }
    return [{"view": view, "status": "bound" if bound else "missing"} for view, bound in bindings.items()]


def _coverage_from_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").lower()
    if status in {"active", "complete", "available", "covered", "ok", "pass"} and not row.get("verification_needed"):
        return "covered"
    if status in {"partial", "incomplete", "uncertain", "degraded", "stale"} or row.get("verification_needed"):
        return "degraded"
    return "missing"


def _canonical_mainline(value: Any) -> str | None:
    if value is None:
        return None
    normalized = normalize_gold_mainline_id(value)
    return normalized or None


def _canonical_transmission_chain(value: Any) -> str:
    return normalize_gold_transmission_chain_id(value)


def _raw_overview_mainlines(*, root: Path, artifact_path: Any) -> set[str]:
    if not isinstance(artifact_path, str) or not artifact_path:
        return set()
    path = root / artifact_path
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    result: set[str] = set()
    for row in _list_of_dicts(payload.get("theme_rankings")):
        mainline_id = _canonical_mainline(row.get("mainline_id") or row.get("mainline"))
        if mainline_id:
            result.add(mainline_id)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _unique_refs(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        ref_key = str(item.get(key) or item.get("source_ref") or item.get("file_path") or item)
        if ref_key in seen:
            continue
        seen.add(ref_key)
        result.append(item)
    return result


def _unique_strings(items: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
