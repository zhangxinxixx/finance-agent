"""Read models for persisted agent analysis output."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc

from apps.api.services._trace_refs import parse_source_refs
from apps.api.services.agent_output_service import (
    build_agent_output_summary,
    prompt_metadata_from_row,
)


def build_agent_analysis_response(db, target_date, run_id: str | None = None) -> dict[str, Any]:
    """Build the unified agent-analysis response from persisted output rows."""
    from database.models.analysis import AgentOutput

    query = db.query(AgentOutput).filter(AgentOutput.trade_date == target_date).order_by(desc(AgentOutput.created_at))
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)

    latest_by_agent: dict[str, Any] = {}
    for row in query.all():
        latest_by_agent.setdefault(row.agent_name, row)

    agent_outputs = [build_agent_output_summary(row) for row in latest_by_agent.values()]
    agents = {
        item["agent_name"]: {**item, "summary": item["summary_zh"], "summary_raw": item["summary"]}
        for item in agent_outputs
    }
    coordinator = agents.get("coordinator") or agents.get("coordinator_agent") or {}

    return {
        "trade_date": target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
        "agent_outputs": agent_outputs,
        "agents": agents,
        "final": {
            "bias": coordinator.get("bias", "neutral"),
            "confidence": coordinator.get("confidence", 0.0),
            "summary": coordinator.get("summary", ""),
            "summary_zh": coordinator.get("summary", ""),
            "summary_raw": coordinator.get("summary_raw", ""),
        },
    }


_AGENT_INPUT_SECTIONS: dict[str, list[str]] = {
    "macro_liquidity_agent": ["macro"],
    "cme_options_agent": ["options"],
    "risk_agent": ["macro", "options"],
    "technical_agent": ["technical"],
    "positioning_agent": ["positioning"],
    "news_agent": ["news"],
    "market_odds_agent": ["market_odds"],
    "coordinator_agent": ["macro", "options", "technical", "positioning", "news", "market_odds"],
    "coordinator": ["macro", "options", "technical", "positioning", "news", "market_odds"],
    "market_regime": ["macro", "options", "jin10"],
    "event_impact": ["news", "macro", "options", "jin10"],
    "jin10_daily": ["jin10"],
    "jin10_report_analysis_agent": ["jin10"],
    "fact_review_agent": ["agent_outputs"],
    "synthesis_agent": ["agent_outputs", "fact_review", "reviews"],
}


def build_agent_analysis_inspection(db, target_date, run_id: str | None = None) -> dict[str, Any]:
    """Build the prompt/input/output inspection view from persisted output rows."""
    from database.models.analysis import AgentOutput, AnalysisSnapshot

    query = db.query(AgentOutput).filter(AgentOutput.trade_date == target_date).order_by(desc(AgentOutput.created_at))
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)

    latest_by_agent: dict[str, Any] = {}
    for row in query.all():
        latest_by_agent.setdefault(row.agent_name, row)

    snapshot_ids = {row.snapshot_id for row in latest_by_agent.values() if row.snapshot_id}
    snapshots = {
        snapshot.snapshot_id: snapshot
        for snapshot in (
            db.query(AnalysisSnapshot).filter(AnalysisSnapshot.snapshot_id.in_(snapshot_ids)).all()
            if snapshot_ids
            else []
        )
    }
    agents = [
        _agent_inspection_item(row, snapshots.get(row.snapshot_id).payload if snapshots.get(row.snapshot_id) else None)
        for row in latest_by_agent.values()
    ]
    first_row = next(iter(latest_by_agent.values()), None)
    return {
        "trade_date": target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
        "run_id": run_id or (first_row.run_id if first_row else None),
        "snapshot_id": first_row.snapshot_id if first_row else None,
        "agents": agents,
        "source": "agent_outputs",
    }


def _agent_inspection_item(row, snapshot_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = row.payload or {}
    prompt_messages = payload.get("prompt_messages")
    input_payload = payload.get("input_payload") or _derive_agent_input(row.agent_name, snapshot_payload)
    generated_by = str(payload.get("generated_by") or "").lower()
    prompt_kind = "rule" if generated_by == "rule" else ("llm" if row.llm_model or prompt_messages else "rule")
    agent_summary = build_agent_output_summary(row)
    prompt_metadata = prompt_metadata_from_row(row)
    return {
        "agent_output_id": row.id,
        "agent_name": row.agent_name,
        "display_name": agent_summary["display_name"],
        "registry_id": agent_summary["registry_id"],
        "role": agent_summary["role"],
        "module": row.module,
        "version": row.version,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "status": row.status,
        "bias": row.bias,
        "confidence": row.confidence,
        "prompt_version_id": row.prompt_version_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "prompt": {
            "kind": prompt_kind,
            "prompt_id": prompt_metadata["prompt_id"],
            "version": prompt_metadata["prompt_version"],
            "checksum": prompt_metadata["prompt_checksum"],
            "source_file": prompt_metadata["prompt_source_file"],
            "available": bool(prompt_messages),
            "messages": prompt_messages or [],
            "note": None if prompt_messages else (
                "规则型 Agent 未使用 LLM prompt。"
                if prompt_kind == "rule"
                else "历史 AgentOutput 未记录实际 prompt，需重新运行后查看。"
            ),
        },
        "input": {
            "input_snapshot_ids": row.input_snapshot_ids or {},
            "source_refs": [source_ref.model_dump(mode="json") for source_ref in parse_source_refs(row.source_refs)],
            "payload": input_payload,
        },
        "output": {
            "summary": row.summary,
            "summary_zh": agent_summary["summary_zh"],
            "key_findings": row.key_findings or [],
            "risk_points": row.risk_points or [],
            "watchlist": row.watchlist or [],
            "invalid_conditions": row.invalid_conditions or [],
            "claims": agent_summary["claims"],
            "claim_reviews": agent_summary["claim_reviews"],
            "prompt_id": prompt_metadata["prompt_id"],
            "prompt_version": prompt_metadata["prompt_version"],
            "prompt_checksum": prompt_metadata["prompt_checksum"],
            "prompt_source_file": prompt_metadata["prompt_source_file"],
            "payload": payload,
            "llm_raw_output": payload.get("llm_raw_output"),
        },
        "llm": {"model": row.llm_model, "usage": row.token_usage, "elapsed_seconds": row.llm_elapsed_seconds},
    }


def _derive_agent_input(agent_name: str, snapshot_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot_payload:
        return None
    sections = _AGENT_INPUT_SECTIONS.get(agent_name, [])
    if not sections:
        return {
            "snapshot_id": snapshot_payload.get("snapshot_id"),
            "trade_date": snapshot_payload.get("trade_date"),
            "available_sections": sorted(key for key, value in snapshot_payload.items() if isinstance(value, (dict, list))),
        }
    return {
        "snapshot_id": snapshot_payload.get("snapshot_id"),
        "trade_date": snapshot_payload.get("trade_date"),
        "sections": {section: snapshot_payload.get(section) for section in sections if section in snapshot_payload},
    }


def empty_agent_analysis() -> dict[str, Any]:
    return {
        "trade_date": None,
        "agent_outputs": [],
        "agents": {},
        "final": {"bias": "neutral", "confidence": 0.0, "summary": "", "summary_zh": "", "summary_raw": ""},
    }
