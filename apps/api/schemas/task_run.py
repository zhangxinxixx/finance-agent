"""Task run and task step public response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import TaskStatus, TraceableResponse
from .source_trace import ArtifactRef, SourceRef


class TaskStepResponse(TraceableResponse):
    step_id: str
    task_name: str
    stage: str | None = None
    task_kind: str | None = None
    status: TaskStatus
    progress: float | None = None
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    output_refs: list[ArtifactRef] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    input_json: dict | None = None
    output_json: dict | None = None
    error_json: dict | None = None


class TaskRunResponse(TraceableResponse):
    task_id: str
    task_type: str
    workspace_id: str | None = None
    trading_date: str | None = None
    status: TaskStatus
    current_stage: str | None = None
    progress: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    total_cost_usd: float | None = None
    token_in: int | None = None
    token_out: int | None = None
    final_result_id: str | None = None
    error_summary: str | None = None
    steps: list[TaskStepResponse] = Field(default_factory=list)


TaskStepResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
TaskRunResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
