"""Read model for gateway LLM audit records and historical AgentOutput traces."""

from __future__ import annotations

from datetime import date
from typing import Any

from database.models.analysis import AgentOutput, LLMCallAudit
from database.queries.llm_audit import get_llm_call_audit, list_llm_call_audits


def list_llm_audit_view(
    db,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    caller: str | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
    trade_date: date | None = None,
) -> dict[str, Any]:
    rows, count = list_llm_call_audits(
        db,
        limit=limit,
        offset=offset,
        status=status,
        provider=provider,
        model=model,
        caller=caller,
        run_id=run_id,
        report_id=report_id,
        trade_date=trade_date,
    )
    return {"count": count, "limit": limit, "offset": offset, "audits": [audit_summary(row) for row in rows]}


def get_llm_audit_view(db, audit_id: str) -> dict[str, Any] | None:
    row = get_llm_call_audit(db, audit_id)
    return audit_detail(row) if row else None


def audit_summary(row: LLMCallAudit) -> dict[str, Any]:
    messages = row.request_messages or []
    prompt_char_count = sum(len(str(item.get("content") or "")) for item in messages if isinstance(item, dict))
    return {
        "audit_id": row.id,
        "call_id": row.call_id,
        "status": row.status,
        "caller": row.caller,
        "provider_requested": row.provider_requested,
        "provider_resolved": row.provider_resolved,
        "model_requested": row.model_requested,
        "model_resolved": row.model_resolved,
        "reasoning_effort_requested": row.reasoning_effort_requested,
        "reasoning_effort_resolved": row.reasoning_effort_resolved,
        "request_config": row.request_config or {},
        "request_sha256": row.request_sha256,
        "response_sha256": row.response_sha256,
        "prompt_message_count": len(messages),
        "prompt_char_count": prompt_char_count,
        "response_char_count": len(row.response_text or ""),
        "usage": row.usage or {},
        "latency_ms": row.latency_ms,
        "attempt_count": row.attempt_count,
        "error_type": row.error_type,
        "error_message": row.error_message,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "report_id": row.report_id,
        "trade_date": row.trade_date.isoformat() if row.trade_date else None,
        "created_at": row.created_at,
    }


def audit_detail(row: LLMCallAudit) -> dict[str, Any]:
    payload = audit_summary(row)
    payload.update(
        {
            "request_messages": row.request_messages or [],
            "response_text": row.response_text,
            "attempts": row.attempts or [],
            "context": row.context or {},
            "source_refs": row.source_refs or [],
            "secrets_redacted": True,
            "immutable": True,
        }
    )
    return payload


def build_report_llm_audit_view(row: AgentOutput) -> dict[str, Any]:
    """Project existing AgentOutput lineage; never rewrite or infer missing prompt text."""

    payload = row.payload or {}
    generated_from = payload.get("generated_from") if isinstance(payload.get("generated_from"), dict) else {}
    prompt_messages = payload.get("prompt_messages")
    prompt_messages = prompt_messages if isinstance(prompt_messages, list) else []
    input_payload = payload.get("input_payload")
    raw_output = payload.get("llm_raw_output")
    audit_id = generated_from.get("audit_id") or payload.get("llm_audit_id")
    config = {
        "provider": getattr(row, "llm_provider", None) or generated_from.get("provider"),
        "model": row.llm_model or generated_from.get("model"),
        "reasoning_effort": generated_from.get("reasoning_effort"),
        "request_timeout": generated_from.get("request_timeout"),
        "max_tokens": generated_from.get("max_tokens"),
        "temperature": generated_from.get("temperature"),
        "json_mode": generated_from.get("json_mode"),
        "prompt_version": payload.get("prompt_version") or generated_from.get("prompt_version"),
        "prompt_checksum": payload.get("prompt_checksum") or generated_from.get("prompt_hash"),
        "secrets_redacted": True,
    }
    has_trace = bool(prompt_messages or input_payload is not None or raw_output is not None)
    return {
        "available": has_trace,
        "audit_id": str(audit_id) if audit_id else None,
        "status": "available" if has_trace else "historical_missing",
        "note": None if has_trace else "历史 AgentOutput 未记录完整实际 LLM 输入输出，未回填或推测。",
        "config": {key: value for key, value in config.items() if value is not None},
        "prompt_messages": prompt_messages,
        "input_payload": input_payload,
        "output_payload": payload.get("report_json") or payload.get("validated_response") or payload.get("deterministic_output"),
        "raw_output": raw_output,
    }
