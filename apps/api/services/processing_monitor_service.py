from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from apps.analysis.agents.gold_artifacts import GoldAgentArtifact
from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.gold_mainline_service import get_gold_mainlines, get_gold_mainlines_latest
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

_GOLD_AGENT_ARTIFACTS = (
    ("source_health_agent", "source_health_output.json"),
    ("event_attribution_agent", "event_attribution_output.json"),
    ("transmission_chain_agent", "transmission_chain_output.json"),
    ("driver_decomposition_agent", "driver_decomposition_output.json"),
    ("mainline_ranking_agent", "mainline_ranking_output.json"),
    ("gold_macro_overview_agent", "gold_macro_overview_output.json"),
    ("review_gate_agent", "review_gate_output.json"),
    ("report_render_agent", "report_render_output.json"),
)

_GOLD_AGENT_TRACE_NODES = {
    "source_health_agent": ("source_health_check",),
    "event_attribution_agent": ("mainline_attribution",),
    "transmission_chain_agent": ("transmission_chain_detection",),
    "driver_decomposition_agent": ("driver_decomposition",),
    "mainline_ranking_agent": ("mainline_attribution",),
    "gold_macro_overview_agent": ("gold_macro_overview",),
    "review_gate_agent": ("review_gate",),
    "report_render_agent": ("reports", "strategy"),
}
_RUN_SCOPED_TRACE_NODES = frozenset(
    node_id
    for node_ids in _GOLD_AGENT_TRACE_NODES.values()
    for node_id in node_ids
) | {"event_flow_feature"}

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
    execution_summary = context["execution_summary"]
    source_health = _artifact_source_health(overview=overview)
    read_time_source_health = _dict(gold_payload.get("read_time_source_health"))

    return {
        "status": _processing_output_status(execution_summary),
        "analysis_status": str(gold_payload.get("status") or "unavailable"),
        "date": gold_payload.get("date"),
        "run_id": gold_payload.get("run_id"),
        "asset": overview.get("asset") or "XAUUSD",
        "generated_from": gold_payload.get("artifact_path"),
        "execution_summary": execution_summary,
        "trace_modes": TRACE_MODES,
        "trace_path": _trace_path(
            gold_payload=gold_payload,
            overview=overview,
            event_links=event_links,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            source_health=source_health,
            agent_artifact_refs=context["execution_summary"]["used_data"]["agent_artifact_refs"],
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


def _processing_output_status(execution_summary: dict[str, Any]) -> str:
    """Expose the persisted output state without conflating read-time health.

    Current source health remains available under ``read_time_source_health``;
    it must not retroactively relabel an already accepted/observed artifact.
    """
    if execution_summary.get("status") == "failed":
        return "failed"
    final_output = _dict(execution_summary.get("final_output"))
    mode = final_output.get("mode")
    if mode == "accepted":
        return "accepted"
    if mode == "observe":
        return "observe"
    if final_output.get("review_status") == "blocked":
        return "blocked_without_artifact"
    return "unavailable"


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
    gold_payload = _latest_completed_processing_payload(root=root)
    overview = _dict(gold_payload.get("gold_macro_overview"))
    overview["review_gate"] = _effective_review_gate(
        root=root,
        artifact_path=gold_payload.get("artifact_path"),
        overview=overview,
    )
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
    agent_envelopes = _load_agent_envelopes(
        root=root,
        artifact_path=gold_payload.get("artifact_path"),
        run_id=str(gold_payload.get("run_id") or ""),
    )
    execution_summary = _execution_summary(
        gold_payload=gold_payload,
        overview=overview,
        envelopes=agent_envelopes,
    )
    return {
        "gold_payload": gold_payload,
        "overview": overview,
        "mainlines_payload": mainlines_payload,
        "event_links": event_links,
        "source_refs": source_refs,
        "artifact_refs": artifact_refs,
        "agent_envelopes": agent_envelopes,
        "execution_summary": execution_summary,
    }


def _latest_completed_processing_payload(*, root: Path) -> dict[str, Any]:
    """Select by final Gate completion, not an intermediate overview write.

    Gold overview jobs can run independently and may write a newer preliminary
    artifact while a canonical composite run is still completing.  A monitor
    of accepted/observe outputs must anchor on the newest final Gate artifact;
    otherwise an incomplete overview can hide a just-rendered report.
    """
    base = root / "storage" / "analysis" / "gold_mainlines"
    candidates: list[tuple[int, str, str]] = []
    if base.exists():
        for date_dir in (item for item in base.iterdir() if item.is_dir()):
            for run_dir in (item for item in date_dir.iterdir() if item.is_dir()):
                overview_path = run_dir / "gold_macro_overview.json"
                completed_ns = _processing_completion_mtime_ns(run_dir)
                if completed_ns is not None and overview_path.is_file():
                    candidates.append((completed_ns, date_dir.name, run_dir.name))
    if candidates:
        _completed_ns, date, run_id = max(candidates)
        return get_gold_mainlines(date=date, run_id=run_id, project_root=root)
    return get_gold_mainlines_latest(project_root=root)


def _processing_completion_mtime_ns(run_dir: Path) -> int | None:
    """Return a durable final-output marker for a processing run.

    New composite runs persist ``quality_gate_result.json`` directly. Older
    Gold v3 runs only persisted the final report-render agent envelope, so keep
    that immutable envelope as a compatibility completion marker. An overview
    alone is deliberately insufficient because it can be a preliminary write.
    """

    gate_path = run_dir / "quality_gate_result.json"
    try:
        return gate_path.stat().st_mtime_ns
    except OSError:
        pass

    renderer_path = run_dir / "agent_outputs" / "report_render_output.json"
    renderer = _load_json_dict(renderer_path)
    if renderer is None:
        return None
    if renderer.get("agent_name") != "report_render_agent" or renderer.get("run_id") != run_dir.name:
        return None
    artifact_types = {
        str(ref.get("artifact_type") or "")
        for ref in _list_of_dicts(renderer.get("artifact_refs"))
    }
    has_report = bool(artifact_types & {"final_report", "observation_report"})
    has_strategy = bool(artifact_types & {"strategy_card", "observation_strategy_card"})
    if not (has_report and has_strategy):
        return None
    try:
        return renderer_path.stat().st_mtime_ns
    except OSError:
        return None


def _execution_summary(
    *,
    gold_payload: dict[str, Any],
    overview: dict[str, Any],
    envelopes: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_steps = [
        str(envelope["agent_name"])
        for envelope in envelopes
        if envelope.get("status") == "failed"
    ]
    input_snapshot_ids: dict[str, Any] = {}
    source_refs: list[dict[str, Any]] = []
    agent_artifact_refs: list[dict[str, Any]] = []
    report_render: dict[str, Any] | None = None
    for envelope in envelopes:
        for key, value in _dict(envelope.get("input_snapshot_ids")).items():
            input_snapshot_ids.setdefault(str(key), value)
        source_refs.extend(_list_of_dicts(envelope.get("source_refs")))
        agent_artifact_refs.append(
            {
                "agent_name": envelope["agent_name"],
                "status": envelope["status"],
                "file_path": envelope["_file_path"],
            }
        )
        if envelope["agent_name"] == "report_render_agent":
            report_render = envelope

    render_refs = _list_of_dicts(report_render.get("artifact_refs")) if report_render else []
    report_refs = [
        ref
        for ref in render_refs
        if ref.get("artifact_type") in {"final_report", "observation_report"}
    ]
    strategy_card_refs = [
        ref
        for ref in render_refs
        if ref.get("artifact_type") in {"strategy_card", "observation_strategy_card"}
    ]
    quality_gate = _quality_gate(overview=overview)
    publish_allowed = quality_gate.get("publish_allowed")
    review_status = str(quality_gate.get("review_status") or "missing")
    has_rendered_output = bool(report_refs and strategy_card_refs)
    has_observation_output = any(
        ref.get("artifact_type") in {"observation_report", "observation_strategy_card"}
        for ref in (*report_refs, *strategy_card_refs)
    )
    if has_rendered_output and (has_observation_output or publish_allowed is False or review_status == "blocked"):
        final_mode = "observe"
    elif has_rendered_output and publish_allowed is True:
        final_mode = "accepted"
    else:
        final_mode = "unavailable"

    if failed_steps:
        execution_status = "failed"
    elif review_status == "blocked":
        execution_status = "blocked"
    elif (
        len(envelopes) < len(_GOLD_AGENT_ARTIFACTS)
        or any(envelope.get("status") != "success" for envelope in envelopes)
        or str(gold_payload.get("status") or "") not in {"success", "available", "complete", "ready"}
        or final_mode == "unavailable"
    ):
        execution_status = "partial"
    else:
        execution_status = "success"

    return {
        "status": execution_status,
        "failed_steps": failed_steps,
        "used_data": {
            "input_snapshot_ids": input_snapshot_ids,
            "source_refs": _unique_refs(source_refs, key="source_ref"),
            "agent_artifact_refs": agent_artifact_refs,
        },
        "final_output": {
            "mode": final_mode,
            "publish_allowed": publish_allowed,
            "review_status": review_status,
            "report_artifact_refs": report_refs,
            "strategy_card_artifact_refs": strategy_card_refs,
        },
    }


def _load_agent_envelopes(
    *,
    root: Path,
    artifact_path: Any,
    run_id: str,
) -> list[dict[str, Any]]:
    overview_path = _resolve_project_artifact_path(root=root, value=artifact_path)
    if overview_path is None:
        return []
    agent_outputs_dir = overview_path.parent / "agent_outputs"
    envelopes: list[dict[str, Any]] = []
    for expected_agent, filename in _GOLD_AGENT_ARTIFACTS:
        path = agent_outputs_dir / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _is_valid_agent_envelope(
            payload,
            expected_agent=expected_agent,
            run_id=run_id,
        ):
            continue
        envelope = dict(payload)
        envelope["_file_path"] = path.relative_to(root).as_posix()
        envelopes.append(envelope)
    return envelopes


def _effective_review_gate(*, root: Path, artifact_path: Any, overview: dict[str, Any]) -> dict[str, Any]:
    """Prefer the run's post-Coordinator publish decision over the Gold pre-gate."""

    review_gate = _dict(overview.get("review_gate"))
    overview_path = _resolve_project_artifact_path(root=root, value=artifact_path)
    if overview_path is None:
        return review_gate
    quality_gate_result = _load_json_dict(overview_path.parent / "quality_gate_result.json")
    if quality_gate_result is None:
        return review_gate

    decision = _dict(quality_gate_result.get("quality_gate_decision"))
    agent_loop_decision = _dict(quality_gate_result.get("agent_loop_decision"))
    if decision:
        review_gate["quality_gate_decision"] = decision
        review_gate["quality_gate_action"] = decision.get("action")
        for key in (
            "manual_review_required",
            "fallback_recommended",
            "retry_recommended",
        ):
            if key in decision:
                review_gate[key] = decision[key]
    if agent_loop_decision:
        review_gate["agent_loop_decision"] = agent_loop_decision
        if "review_status" in agent_loop_decision:
            review_gate["review_status"] = agent_loop_decision["review_status"]
        if "publish_allowed" in agent_loop_decision:
            review_gate["publish_allowed"] = agent_loop_decision["publish_allowed"]
    elif "publish_allowed" in quality_gate_result:
        review_gate["publish_allowed"] = quality_gate_result["publish_allowed"]
    return review_gate


def _is_valid_agent_envelope(
    payload: Any,
    *,
    expected_agent: str,
    run_id: str,
) -> bool:
    if not isinstance(payload, dict) or not run_id:
        return False
    try:
        envelope = GoldAgentArtifact.model_validate(payload)
    except ValidationError:
        return False
    return envelope.agent_name == expected_agent and envelope.run_id == run_id


def _resolve_project_artifact_path(*, root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value)
    if relative.is_absolute():
        return None
    resolved_root = root.resolve()
    candidates = (root / relative, root / "storage" / relative)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(resolved_root) and resolved.is_file():
            return resolved
    return None


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
    trace_header = _trace_header(
        gold_payload=gold_payload,
        overview=overview,
        event=event,
        query=query,
    )
    if event is None:
        empty_detail = _empty_trace_detail()
        return {
            "status": "not_found",
            "date": gold_payload.get("date"),
            "run_id": gold_payload.get("run_id"),
            "asset": overview.get("asset") or "XAUUSD",
            "trace_header": trace_header,
            "query": query,
            "matched_event": None,
            "mainlines": [],
            "transmission_chains": [],
            "trace_path": _trace_path(
                gold_payload=gold_payload,
                overview=overview,
                event_links=[],
                source_refs=[],
                artifact_refs=context["artifact_refs"],
                source_health=source_health,
                agent_artifact_refs=context["execution_summary"]["used_data"]["agent_artifact_refs"],
                expose_stage_refs=True,
            ),
            "source_health": source_health,
            "quality_gate": _quality_gate(overview=overview),
            "read_time_source_health": read_time_source_health,
            "read_time_warnings": list(gold_payload.get("read_time_warnings") or []),
            "read_time_generated_at": gold_payload.get("read_time_generated_at") or datetime.now(timezone.utc).isoformat(),
            "source_refs": [],
            "artifact_refs": context["artifact_refs"],
            "view_bindings": _view_bindings(gold_payload=gold_payload, overview=overview, event_links=[], source_refs=[]),
            **empty_detail,
        }

    event_source_refs = _unique_refs(_list_of_dicts(event.get("source_refs")), key="source_ref")
    trace_id = str(event.get("processing_trace_id") or query.get("processing_trace_id") or event.get("event_id") or "")
    response_query = {
        "processing_trace_id": trace_id,
        "event_id": str(event.get("event_id") or query.get("event_id") or ""),
        "input_id": str(event.get("input_id") or query.get("input_id") or ""),
        "source_ref": event_source_refs[0].get("source_ref") if event_source_refs else query.get("source_ref"),
    }
    view_bindings = _view_bindings(
        gold_payload=gold_payload,
        overview=overview,
        event_links=[event],
        source_refs=event_source_refs,
    )
    trace_detail = _trace_detail(context=context, view_bindings=view_bindings)
    return {
        "status": "matched",
        "date": gold_payload.get("date"),
        "run_id": gold_payload.get("run_id"),
        "asset": overview.get("asset") or "XAUUSD",
        "trace_header": trace_header,
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
            agent_artifact_refs=context["execution_summary"]["used_data"]["agent_artifact_refs"],
            agent_envelopes=context["agent_envelopes"],
            input_snapshot_ids=context["execution_summary"]["used_data"]["input_snapshot_ids"],
            expose_stage_refs=True,
        ),
        "source_health": source_health,
        "quality_gate": _quality_gate(overview=overview),
        "read_time_source_health": read_time_source_health,
        "read_time_warnings": list(gold_payload.get("read_time_warnings") or []),
        "read_time_generated_at": gold_payload.get("read_time_generated_at") or datetime.now(timezone.utc).isoformat(),
        "source_refs": event_source_refs,
        "artifact_refs": context["artifact_refs"],
        "view_bindings": view_bindings,
        **trace_detail,
    }


def _trace_header(
    *,
    gold_payload: dict[str, Any],
    overview: dict[str, Any],
    event: dict[str, Any] | None,
    query: dict[str, str],
) -> dict[str, Any]:
    _query_type, query_value = next(iter(query.items()))
    quality_gate = _quality_gate(overview=overview)
    trace_id = (
        str(event.get("processing_trace_id") or event.get("event_id") or "")
        if event is not None
        else str(query.get("processing_trace_id") or "")
    )
    return {
        "trace_id": trace_id,
        "run_id": gold_payload.get("run_id"),
        "entity_type": "event" if event is not None else "unknown",
        "entity_id": event.get("event_id") if event is not None else query_value,
        "status": "matched" if event is not None else "not_found",
        "review_status": quality_gate.get("review_status"),
        "publish_allowed": quality_gate.get("publish_allowed"),
        "as_of": overview.get("as_of") or gold_payload.get("as_of"),
    }


def _empty_trace_detail() -> dict[str, Any]:
    return {
        "primary_output": {},
        "fallback_outputs": [],
        "accepted_output": {},
        "accepted_output_source": "none",
        "fallback_review": _fallback_review(review_gate={}),
        "agent_envelopes": [],
        "input_snapshot_ids": {},
        "evidence_refs": [],
        "evidence_items": [],
        "affected_views": [],
    }


def _trace_detail(
    *,
    context: dict[str, Any],
    view_bindings: list[dict[str, str]],
) -> dict[str, Any]:
    overview = context["overview"]
    review_gate = _dict(overview.get("review_gate"))
    agent_loop_decision = _dict(review_gate.get("agent_loop_decision"))
    envelope_projections = [
        _agent_envelope_projection(envelope)
        for envelope in context["agent_envelopes"]
    ]
    primary_output = _primary_output_projection(envelope_projections)
    fallback_outputs = _fallback_output_summaries(
        _dict(review_gate.get("fallback_outputs"))
    )
    accepted_output_source, accepted_output = _accepted_output_projection(
        review_gate=review_gate,
        agent_loop_decision=agent_loop_decision,
        execution_summary=context["execution_summary"],
        primary_output=primary_output,
        fallback_outputs=fallback_outputs,
    )
    input_snapshot_ids: dict[str, Any] = {}
    evidence_refs: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    for envelope in envelope_projections:
        for key, value in _dict(envelope.get("input_snapshot_ids")).items():
            input_snapshot_ids.setdefault(str(key), value)
        evidence_refs.extend(_list_of_dicts(envelope.get("evidence_refs")))
        evidence_items.extend(_list_of_dicts(envelope.get("evidence_items")))

    affected_views = [
        str(binding["view"])
        for binding in view_bindings
        if binding.get("status") == "bound"
    ]
    if "ProcessingMonitor" not in affected_views:
        affected_views.append("ProcessingMonitor")
    return {
        "primary_output": primary_output,
        "fallback_outputs": fallback_outputs,
        "accepted_output": accepted_output,
        "accepted_output_source": accepted_output_source,
        "fallback_review": _fallback_review(review_gate=review_gate),
        "agent_envelopes": envelope_projections,
        "input_snapshot_ids": input_snapshot_ids,
        "evidence_refs": _unique_refs(evidence_refs, key="evidence_ref"),
        "evidence_items": _unique_refs(evidence_items, key="evidence_id"),
        "affected_views": affected_views,
    }


def _agent_envelope_projection(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": "run",
        "agent_name": envelope["agent_name"],
        "run_id": envelope["run_id"],
        "snapshot_id": envelope["snapshot_id"],
        "status": envelope["status"],
        "confidence": envelope.get("confidence"),
        "created_at": envelope.get("created_at"),
        "input_snapshot_ids": _dict(envelope.get("input_snapshot_ids")),
        "source_refs": _list_of_dicts(envelope.get("source_refs")),
        "artifact_refs": _list_of_dicts(envelope.get("artifact_refs")),
        "evidence_refs": _list_of_dicts(envelope.get("evidence_refs")),
        "evidence_items": _list_of_dicts(envelope.get("evidence_items")),
        "data_quality": list(envelope.get("data_quality") or []),
        "file_path": envelope["_file_path"],
    }


def _primary_output_projection(
    envelope_projections: list[dict[str, Any]],
) -> dict[str, Any]:
    report_render = next(
        (
            envelope
            for envelope in envelope_projections
            if envelope.get("agent_name") == "report_render_agent"
        ),
        None,
    )
    if report_render is None:
        return {}
    artifact_refs = [
        ref
        for ref in _list_of_dicts(report_render.get("artifact_refs"))
        if ref.get("artifact_type")
        in {"final_report", "strategy_card", "observation_report", "observation_strategy_card"}
    ]
    artifact_types = {str(ref.get("artifact_type")) for ref in artifact_refs}
    valid_pair = artifact_types in (
        {"final_report", "strategy_card"},
        {"observation_report", "observation_strategy_card"},
    )
    if not valid_pair:
        return {}
    return {
        "scope": "run",
        "agent_name": "report_render_agent",
        "run_id": report_render.get("run_id"),
        "snapshot_id": report_render.get("snapshot_id"),
        "status": report_render.get("status"),
        "file_path": report_render.get("file_path"),
        "artifact_refs": artifact_refs,
    }


def _accepted_output_projection(
    *,
    review_gate: dict[str, Any],
    agent_loop_decision: dict[str, Any],
    execution_summary: dict[str, Any],
    primary_output: dict[str, Any],
    fallback_outputs: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if (
        review_gate.get("publish_allowed") is not True
        or agent_loop_decision.get("publish_allowed") is False
    ):
        return "none", {}

    accepted_reference = agent_loop_decision.get("accepted_output")
    if isinstance(accepted_reference, dict):
        source = str(accepted_reference.get("source") or "none")
        artifact_ref = _dict(accepted_reference.get("artifact_ref"))
        if source == "primary":
            if not primary_output or not artifact_ref:
                return "none", {}
            return "primary", primary_output
        if source == "corrective_fallback":
            return ("fallback", artifact_ref) if artifact_ref else ("none", {})
        return "none", {}

    # Legacy persisted decisions predate the typed accepted-output reference.
    # Keep them readable, but never use this inference for new decisions.
    fallback_trace = _dict(agent_loop_decision.get("fallback_trace"))
    selected = str(fallback_trace.get("accepted_output") or "")
    if selected == "primary":
        return ("primary", primary_output) if primary_output else ("none", {})
    if selected == "fallback":
        accepted_outputs = _dict(agent_loop_decision.get("accepted_outputs"))
        if accepted_outputs:
            return "fallback", accepted_outputs
        if fallback_outputs:
            return "fallback", {"outputs": fallback_outputs}
        return "none", {}
    final_output = _dict(execution_summary.get("final_output"))
    if final_output.get("mode") == "accepted" and primary_output:
        return "primary", primary_output
    return "none", {}


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
    agent_artifact_refs: list[dict[str, Any]],
    agent_envelopes: list[dict[str, Any]] | None = None,
    input_snapshot_ids: dict[str, Any] | None = None,
    expose_stage_refs: bool = False,
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
    agent_refs_by_node: dict[str, list[dict[str, Any]]] = {}
    for artifact_ref in agent_artifact_refs:
        node_ids = _GOLD_AGENT_TRACE_NODES.get(str(artifact_ref.get("agent_name") or ""))
        if node_ids is None:
            continue
        for node_id in node_ids:
            agent_refs_by_node.setdefault(node_id, []).append(artifact_ref)

    result: list[dict[str, Any]] = []
    for node in TRACE_PATH:
        node_id = node["node_id"]
        status = "missing"
        source_ref_count = 0
        artifact_ref_count = 0
        stage_source_refs, stage_artifact_refs = _trace_stage_refs(
            node_id=node_id,
            event_links=event_links,
            source_refs=source_refs,
            agent_envelopes=agent_envelopes or [],
            input_snapshot_ids=input_snapshot_ids or {},
            expose_stage_refs=expose_stage_refs,
        )

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

        if expose_stage_refs:
            source_ref_count = len(stage_source_refs)
            artifact_ref_count = len(stage_artifact_refs)

        result.append(
            {
                **node,
                "status": status,
                "source_ref_count": source_ref_count,
                "artifact_ref_count": artifact_ref_count,
                "warnings": _trace_stage_values(
                    node_id=node_id,
                    field="warnings",
                    overview=overview,
                ),
                "missing_data": _trace_stage_values(
                    node_id=node_id,
                    field="missing_data",
                    overview=overview,
                ),
                "agent_artifact_refs": _unique_refs(
                    agent_refs_by_node.get(node_id, []),
                    key="file_path",
                ),
                "source_refs": stage_source_refs,
                "artifact_refs": stage_artifact_refs,
                "scope": "run" if node_id in _RUN_SCOPED_TRACE_NODES else "event",
            }
        )
    return result


def _trace_stage_refs(
    *,
    node_id: str,
    event_links: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    agent_envelopes: list[dict[str, Any]],
    input_snapshot_ids: dict[str, Any],
    expose_stage_refs: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not expose_stage_refs or not event_links:
        return [], []

    if node_id == "jin10_message_raw":
        return (
            _trace_source_ref_links(source_refs),
            _source_path_artifact_refs(
                source_refs,
                field="raw_path",
                artifact_type="raw_input",
                expected_root="raw",
            ),
        )
    if node_id == "jin10_flash_parse":
        return (
            _trace_source_ref_links(source_refs),
            _source_path_artifact_refs(
                source_refs,
                field="parsed_path",
                artifact_type="parsed_event",
                expected_root="parsed",
            ),
        )
    if node_id == "event_flow_feature":
        return (
            _trace_source_ref_links(source_refs),
            _feature_artifact_refs(input_snapshot_ids),
        )
    if node_id == "source_trace":
        return _trace_source_ref_links(source_refs), []

    stage_agents = {agent_name for agent_name, node_ids in _GOLD_AGENT_TRACE_NODES.items() if node_id in node_ids}
    stage_envelopes = [
        envelope for envelope in agent_envelopes if str(envelope.get("agent_name") or "") in stage_agents
    ]
    stage_source_refs = _trace_source_ref_links(
        [ref for envelope in stage_envelopes for ref in _list_of_dicts(envelope.get("source_refs"))],
    )
    stage_artifact_refs = _unique_refs(
        [ref for envelope in stage_envelopes for ref in _list_of_dicts(envelope.get("artifact_refs"))],
        key="path",
    )
    if node_id == "reports":
        stage_artifact_refs = [ref for ref in stage_artifact_refs if ref.get("artifact_type") == "final_report"]
    elif node_id == "strategy":
        stage_artifact_refs = [ref for ref in stage_artifact_refs if ref.get("artifact_type") == "strategy_card"]
    return stage_source_refs, stage_artifact_refs


def _trace_source_ref_links(source_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for source_ref in source_refs:
        ref_id = source_ref.get("source_ref")
        if not isinstance(ref_id, str) or not ref_id:
            continue
        link = {"source_ref": ref_id}
        source = source_ref.get("source")
        if isinstance(source, str) and source:
            link["source"] = source
        links.append(link)
    return _unique_refs(links, key="source_ref")


def _feature_artifact_refs(input_snapshot_ids: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for snapshot_name, value in input_snapshot_ids.items():
        if not isinstance(value, str) or not value.strip():
            continue
        path = value.strip().replace("\\", "/")
        parts = path.split("/")
        if path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            continue
        feature_parts = parts[1:] if parts[:1] == ["storage"] else parts
        if not feature_parts or feature_parts[0] != "features":
            continue
        refs.append({"artifact_type": str(snapshot_name), "path": path})
    return _unique_refs(refs, key="path")


def _source_path_artifact_refs(
    source_refs: list[dict[str, Any]],
    *,
    field: str,
    artifact_type: str,
    expected_root: str,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for source_ref in source_refs:
        value = source_ref.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        path = value.strip().replace("\\", "/")
        parts = path.split("/")
        if path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            continue
        artifact_parts = parts[1:] if parts[:1] == ["storage"] else parts
        if not artifact_parts or artifact_parts[0] != expected_root:
            continue
        refs.append({"artifact_type": artifact_type, "path": path})
    return _unique_refs(refs, key="path")


def _trace_stage_values(
    *,
    node_id: str,
    field: str,
    overview: dict[str, Any],
) -> list[str]:
    if node_id == "source_health_check":
        owner = _dict(overview.get("source_health"))
    elif node_id == "gold_macro_overview":
        owner = overview
    elif node_id == "review_gate":
        owner = _dict(overview.get("review_gate"))
    else:
        return []
    values = owner.get(field)
    if not isinstance(values, list):
        return []
    return _unique_strings(item for item in values if isinstance(item, str) and item)


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
        "fallback_tasks": _list_of_dicts(agent_loop_decision.get("fallback_tasks")),
        "task_results": _list_of_dicts(review_gate.get("fallback_task_results")),
        "reasons": _unique_strings(str(item) for item in agent_loop_decision.get("reasons") or []),
        "review_items": _list_of_dicts(fallback_trace.get("review_items")),
        "fallback_quality_gate_decision": _dict(agent_loop_decision.get("fallback_quality_gate_decision")),
        "no_strong_conclusion": bool(agent_loop_decision.get("no_strong_conclusion")),
        "strategy_card_override": _dict(agent_loop_decision.get("strategy_card_override")),
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


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
