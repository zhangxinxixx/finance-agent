from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.runtime.execution_event_bridge import emit_task_event

logger = logging.getLogger(__name__)


def load_premarket_source_status_index() -> dict[str, dict[str, Any]]:
    """Load source readiness facts once per run without hard-failing the worker."""
    try:
        from apps.api.services.source_service import get_data_source_status_index

        return get_data_source_status_index()
    except Exception:
        logger.exception("Failed to load data source status index for premarket gating")
        return {}


def should_apply_source_readiness_gate(
    contract: Any,
    source_status_index: dict[str, dict[str, Any]],
) -> bool:
    required_sources = tuple(getattr(contract, "required_sources", ()) or ())
    if not required_sources:
        return False

    observed_rows = [
        source_status_index[source_key]
        for source_key in required_sources
        if source_key in source_status_index
    ]
    if not observed_rows:
        return False

    return any(_source_row_has_runtime_signal(row) for row in observed_rows)


def format_source_readiness_blocked_reason(readiness: Any) -> str:
    blocked_sources = list(getattr(readiness, "blocked_sources", ()) or ())
    gating_reason = str(getattr(readiness, "gating_reason", "") or "source_readiness_blocked")
    if blocked_sources:
        return f"source readiness blocked: {', '.join(blocked_sources)} ({gating_reason})"
    return f"source readiness blocked ({gating_reason})"


def emit_source_readiness_events(
    db: DBSession,
    *,
    run_id: str,
    step: Any,
    readiness: Any,
) -> None:
    payload = {
        "decision": getattr(readiness, "decision", None),
        "gating_reason": getattr(readiness, "gating_reason", None),
        "required_sources": list(getattr(readiness, "required_sources", ()) or ()),
        "degraded_sources": list(getattr(readiness, "degraded_sources", ()) or ()),
        "blocked_sources": list(getattr(readiness, "blocked_sources", ()) or ()),
        "step_name": getattr(step, "name", None),
        "stage": getattr(step, "stage", None),
        "task_kind": getattr(step, "task_kind", None),
        "source": "worker",
    }
    emit_task_event(db, run_id, str(step.id), "SOURCE_READINESS_EVALUATED", payload)

    decision = str(getattr(readiness, "decision", "") or "")
    if decision == "blocked":
        emit_task_event(db, run_id, str(step.id), "SOURCE_BLOCKED_TASK", payload)
    elif decision == "degraded_allowed":
        emit_task_event(db, run_id, str(step.id), "SOURCE_FALLBACK_USED", payload)


def _source_row_has_runtime_signal(row: dict[str, Any]) -> bool:
    return bool(
        row.get("readiness_state")
        or row.get("raw_ingested")
        or row.get("parsed")
        or row.get("analysis_ready")
        or row.get("latest_health_at")
        or row.get("latest_update_time")
        or row.get("last_run_id")
        or row.get("error_message")
    )
