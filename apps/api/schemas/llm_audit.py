"""Read-only API contracts for LLM call audit records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import SchemaModel


class LLMAuditSummary(SchemaModel):
    audit_id: str
    call_id: str
    status: str
    caller: str
    provider_requested: str | None = None
    provider_resolved: str | None = None
    model_requested: str | None = None
    model_resolved: str | None = None
    reasoning_effort_requested: str | None = None
    reasoning_effort_resolved: str | None = None
    request_config: dict[str, Any] = Field(default_factory=dict)
    request_sha256: str
    response_sha256: str | None = None
    prompt_message_count: int = 0
    prompt_char_count: int = 0
    response_char_count: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    attempt_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    run_id: str | None = None
    snapshot_id: str | None = None
    report_id: str | None = None
    trade_date: str | None = None
    created_at: datetime | None = None


class LLMAuditDetail(LLMAuditSummary):
    request_messages: list[dict[str, Any]] = Field(default_factory=list)
    response_text: str | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    secrets_redacted: bool = True
    immutable: bool = True


class LLMAuditListResponse(SchemaModel):
    count: int
    limit: int
    offset: int
    audits: list[LLMAuditSummary] = Field(default_factory=list)


class ReportLLMAuditView(SchemaModel):
    """Audit projection for historical AgentOutput rows without backfill."""

    available: bool = False
    audit_id: str | None = None
    status: str = "historical_missing"
    note: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    prompt_messages: list[dict[str, Any]] = Field(default_factory=list)
    input_payload: Any = None
    output_payload: Any = None
    raw_output: Any = None
