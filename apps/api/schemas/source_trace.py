"""Source trace and artifact reference schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ArtifactType, DataStatus, SchemaModel, TraceableResponse


class SourceRef(SchemaModel):
    source_id: str
    source_name: str
    source_type: str
    data_date: str | None = None
    endpoint: str | None = None
    captured_at: datetime | None = None
    file_path: str | None = None
    sha256: str | None = None
    url: str | None = None
    status: str | None = None


class ArtifactRef(SchemaModel):
    artifact_id: str
    artifact_type: ArtifactType
    file_path: str
    version: str | None = None
    generated_at: datetime | None = None
    sha256: str | None = None


class SnapshotRef(SchemaModel):
    snapshot_id: str
    snapshot_type: str
    data_date: str | None = None
    run_id: str | None = None
    data_status: DataStatus = DataStatus.live
    created_at: datetime | None = None
    input_snapshot_ids: list[str] = Field(default_factory=list)


class SourceTraceResponse(TraceableResponse):
    snapshot: SnapshotRef | None = None
    input_snapshots: list[SnapshotRef] = Field(default_factory=list)
    related_artifacts: list[ArtifactRef] = Field(default_factory=list)


TraceableResponse.model_rebuild(_types_namespace={"SourceRef": SourceRef, "ArtifactRef": ArtifactRef})
