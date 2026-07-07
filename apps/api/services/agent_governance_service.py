"""Shared Agent prompt governance API contracts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from apps.api.services.agent_output_service import prompt_contract_id

_PROMPT_VERSION_STATUSES = {"draft", "candidate", "active", "deprecated", "rolled_back"}
_PROMPT_KINDS = {"llm", "hybrid", "rule", "vlm"}


def validate_prompt_version_create_payload(payload: Any) -> None:
    if not payload.prompt_template:
        raise HTTPException(status_code=400, detail="prompt_template must not be empty")
    status = payload.status or "draft"
    if status not in _PROMPT_VERSION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid prompt status: {status}")
    kind = payload.prompt_kind or "llm"
    if kind not in _PROMPT_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid prompt kind: {kind}")


def prompt_version_item(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "prompt_id": prompt_contract_id(row.agent_id),
        "agent_id": row.agent_id,
        "agent_name": row.agent_id,
        "version": row.version,
        "prompt_kind": row.prompt_kind,
        "prompt_source": row.prompt_source,
        "source_file": row.prompt_source,
        "prompt_template": row.prompt_template,
        "prompt_sha256": row.prompt_sha256,
        "checksum": row.prompt_sha256,
        "status": row.status,
        "enabled": row.enabled,
        "model_routing": row.model_routing,
        "change_note": row.change_note,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def prompt_feedback_item(row: Any) -> dict[str, Any]:
    return {
        "feedback_id": row.feedback_id,
        "agent_output_id": row.agent_output_id,
        "agent_id": row.agent_id,
        "prompt_version_id": row.prompt_version_id,
        "run_id": row.run_id,
        "rating": row.rating,
        "category": row.category,
        "comment": row.comment,
        "suggested_changes": row.suggested_changes,
        "review_item_id": row.review_item_id,
        "status": row.status,
        "submitted_by": row.submitted_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
