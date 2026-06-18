"""Artifact detail API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import TraceableResponse
from .source_trace import ArtifactRef


class ArtifactDetailResponse(TraceableResponse):
    artifact: ArtifactRef
    task_id: str | None = None
    task_name: str | None = None
    stage: str | None = None
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
