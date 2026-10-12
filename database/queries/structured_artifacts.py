"""Bounded structured artifact queries; original lineage stays on RunArtifact."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from database.models.execution import RunArtifact


def _filtered(*, run_ids=(), layer=None, status=None, schema_version=None, error=None):
    filters = []
    if run_ids:
        filters.append(RunArtifact.run_id.in_([uuid.UUID(str(value)) for value in run_ids]))
    if layer is not None:
        filters.append(RunArtifact.structured_layer == layer)
    if status is not None:
        filters.append(RunArtifact.structured_status == status)
    if schema_version is not None:
        filters.append(RunArtifact.structured_schema_version == schema_version)
    if error is not None:
        filters.append(RunArtifact.structured_error == error)
    return filters


def list_structured_artifacts(
    db: Session, *, run_ids=(), layer=None, status=None, schema_version=None, error=None, after=None, limit=100
):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    query = (
        select(RunArtifact)
        .options(undefer(RunArtifact.structured_payload))
        .where(*_filtered(run_ids=run_ids, layer=layer, status=status, schema_version=schema_version, error=error))
    )
    if after is not None:
        query = query.where(RunArtifact.artifact_id > uuid.UUID(str(after)))
    return list(db.scalars(query.order_by(RunArtifact.artifact_id).limit(limit)))


def structured_artifact_coverage(db: Session, *, run_ids=(), layer=None, status=None, schema_version=None):
    query = (
        select(RunArtifact.structured_layer, RunArtifact.structured_status, func.count())
        .where(*_filtered(run_ids=run_ids, layer=layer, status=status, schema_version=schema_version))
        .group_by(RunArtifact.structured_layer, RunArtifact.structured_status)
    )
    rows = db.execute(query).all()
    return {
        "total": sum(row[2] for row in rows),
        "groups": [{"layer": row[0], "status": row[1] or "pending", "count": row[2]} for row in rows],
    }
