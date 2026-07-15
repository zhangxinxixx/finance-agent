"""Sanitized, append-only observability for shared-gateway LLM calls."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
from datetime import date
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_SECRET_KEY = re.compile(
    r"(^|_)(api_?key|access_?token|refresh_?token|authorization|password|secret|cookie)($|_)",
    re.IGNORECASE,
)
_DATA_URL = re.compile(r"^data:([^;,]+)?(?:;[^,]*)?,", re.IGNORECASE)
_STRING_SECRETS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|cookie)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|key)=)[^&#\s]+"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)


def infer_llm_caller() -> str:
    """Return the first caller outside the shared LLM package."""

    frame = inspect.currentframe()
    try:
        frame = frame.f_back if frame else None
        while frame:
            module = str(frame.f_globals.get("__name__") or "")
            if module and not module.startswith("apps.llm"):
                return f"{module}.{frame.f_code.co_name}"
            frame = frame.f_back
    finally:
        del frame
    return "unknown"


def sanitize_audit_value(value: Any, *, key: str | None = None) -> Any:
    """Remove credentials and image binary while preserving exact text prompts."""

    if key and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): sanitize_audit_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_value(item) for item in value]
    if isinstance(value, bytes):
        return {
            "redacted": "binary",
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, str):
        match = _DATA_URL.match(value)
        if match:
            encoded = value.encode("utf-8")
            return {
                "redacted": "data_url",
                "media_type": match.group(1) or "application/octet-stream",
                "size_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        return _sanitize_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _sanitize_string(str(value))


def _sanitize_string(value: str) -> str:
    sanitized = value
    for pattern in _STRING_SECRETS:
        if pattern.pattern.startswith("\\b[A-Z0-9"):
            sanitized = pattern.sub("[REDACTED_EMAIL]", sanitized)
        elif "sk-" in pattern.pattern:
            sanitized = pattern.sub("[REDACTED]", sanitized)
        else:
            sanitized = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", sanitized)
    return sanitized


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_llm_call_audit_payload(
    *,
    call_id: str,
    status: str,
    caller: str,
    messages: list[dict[str, Any]],
    request_config: Mapping[str, Any],
    response_text: str | None,
    usage: Mapping[str, Any] | None,
    latency_ms: int | None,
    attempts: list[dict[str, Any]],
    error: Exception | None,
    audit_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    safe_messages = sanitize_audit_value(messages)
    safe_config = sanitize_audit_value(dict(request_config))
    safe_context = sanitize_audit_value(dict(audit_context or {}))
    safe_attempts = sanitize_audit_value(attempts)
    safe_response = sanitize_audit_value(response_text)
    if safe_response is not None and not isinstance(safe_response, str):
        safe_response = json.dumps(safe_response, ensure_ascii=False, sort_keys=True)
    safe_error = sanitize_audit_value(str(error)) if error else None
    redaction_applied = any(
        "[REDACTED" in json.dumps(value, ensure_ascii=False, default=str)
        for value in (safe_messages, safe_config, safe_context, safe_attempts, safe_response, safe_error)
    )
    if isinstance(safe_config, dict):
        safe_config["sanitization_performed"] = True
        safe_config["secrets_redacted"] = redaction_applied
    resolved = safe_config.get("resolved") if isinstance(safe_config, dict) else {}
    requested = safe_config.get("requested") if isinstance(safe_config, dict) else {}
    resolved = resolved if isinstance(resolved, dict) else {}
    requested = requested if isinstance(requested, dict) else {}
    trade_date = _parse_date(safe_context.get("trade_date") if isinstance(safe_context, dict) else None)
    return {
        "call_id": call_id,
        "status": status,
        "caller": caller or "unknown",
        "provider_requested": _optional_text(requested.get("provider")),
        "provider_resolved": _optional_text(resolved.get("provider")),
        "model_requested": _optional_text(requested.get("model")),
        "model_resolved": _optional_text(resolved.get("model")),
        "reasoning_effort_requested": _optional_text(requested.get("reasoning_effort")),
        "reasoning_effort_resolved": _optional_text(resolved.get("reasoning_effort")),
        "request_config": safe_config,
        "request_messages": safe_messages,
        "request_sha256": canonical_sha256(safe_messages),
        "response_text": safe_response,
        "response_sha256": hashlib.sha256(safe_response.encode("utf-8")).hexdigest() if isinstance(safe_response, str) else None,
        "usage": sanitize_audit_value(dict(usage or {})),
        "latency_ms": latency_ms,
        "attempts": safe_attempts,
        "attempt_count": len(attempts),
        "error_type": type(error).__name__ if error else None,
        "error_message": safe_error,
        "context": safe_context,
        "source_refs": list(safe_context.get("source_refs") or []) if isinstance(safe_context, dict) else [],
        "run_id": _optional_text(safe_context.get("run_id")) if isinstance(safe_context, dict) else None,
        "snapshot_id": _optional_text(safe_context.get("snapshot_id")) if isinstance(safe_context, dict) else None,
        "report_id": _optional_text(safe_context.get("report_id")) if isinstance(safe_context, dict) else None,
        "trade_date": trade_date,
    }


def persist_llm_call_audit(payload: dict[str, Any]) -> str | None:
    """Persist an audit row without changing the outcome of the LLM call."""

    if "PYTEST_CURRENT_TEST" in os.environ and os.getenv("FINANCE_AGENT_ENABLE_LLM_AUDIT_IN_TESTS") != "1":
        return None
    try:
        from database.models.analysis import ensure_analysis_tables
        from database.models.engine import SessionLocal
        from database.queries.llm_audit import create_llm_call_audit

        with SessionLocal() as session:
            ensure_analysis_tables(session)
            row = create_llm_call_audit(session, payload)
            session.commit()
            return row.id
    except Exception:
        logger.warning("LLM audit persistence failed; model call result is preserved", exc_info=True)
        return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
