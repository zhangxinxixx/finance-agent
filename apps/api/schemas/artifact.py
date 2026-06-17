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
    metadata: dict[str, Any] = Field(default_factory=dict)
