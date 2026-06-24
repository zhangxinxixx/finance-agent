"""Event Flow write-action schemas."""

from __future__ import annotations

from .common import TraceableResponse
from .source_trace import ArtifactRef, SourceRef


class EventFlowActionRequest(TraceableResponse):
    action: str | None = None
    actor: str | None = None
    reason: str | None = None
    note: str | None = None
    request_id: str | None = None


class EventFlowBriefLinkRequest(EventFlowActionRequest):
    target_event_id: str


class EventFlowActionResponse(TraceableResponse):
    status: str
    action: str
    entity_type: str
    entity_id: str
    review_id: str | None = None
    audit_id: str | None = None


EventFlowActionRequest.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
EventFlowBriefLinkRequest.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
EventFlowActionResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
