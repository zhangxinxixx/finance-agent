from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from apps.analysis.agents.schemas import AgentStatus
from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
    immutable_json_item,
    write_immutable_artifact_bundle,
)


class GoldAgentArtifact(BaseModel):
    """Lineage envelope for a Gold analysis agent's canonical business artifact."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    agent_name: str
    run_id: str
    snapshot_id: str
    input_snapshot_ids: dict[str, JsonValue]
    source_refs: list[dict[str, JsonValue]] = Field(default_factory=list)
    artifact_refs: list[dict[str, JsonValue]] = Field(default_factory=list)
    evidence_refs: list[dict[str, JsonValue]] = Field(default_factory=list)
    evidence_items: list[dict[str, JsonValue]] = Field(default_factory=list)
    data_quality: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: AgentStatus
    created_at: datetime

    @field_validator("agent_name", "run_id", "snapshot_id")
    @classmethod
    def _require_non_empty_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        return value


class GoldArtifactWriteResult(BaseModel):
    """Traceable outcome of an idempotent artifact write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_path: str
    storage_relative_path: str | None
    content_sha256: str
    written: bool


GoldArtifactConflictError = ImmutableArtifactConflictError


def canonical_gold_agent_artifact_json(artifact: GoldAgentArtifact) -> str:
    """Return the stable JSON representation used for comparison and storage."""

    payload = artifact.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_gold_agent_artifact(
    target_path: str | Path,
    artifact: GoldAgentArtifact,
    *,
    storage_root: str | Path | None = None,
) -> GoldArtifactWriteResult:
    """Atomically write an immutable Gold agent envelope.

    An existing canonically identical JSON object is accepted without being
    rewritten. Any other existing content is treated as an immutable-artifact
    conflict.
    """

    result = write_immutable_artifact_bundle(
        [immutable_json_item(target_path, artifact.model_dump(mode="json"))],
        storage_root=storage_root,
    )[0]
    return GoldArtifactWriteResult.model_validate(asdict(result))


def write_canonical_gold_json(
    target_path: str | Path,
    payload: dict[str, JsonValue],
    *,
    storage_root: str | Path | None = None,
) -> GoldArtifactWriteResult:
    """Atomically write an immutable canonical Gold business artifact."""

    result = write_immutable_artifact_bundle(
        [immutable_json_item(target_path, payload)],
        storage_root=storage_root,
    )[0]
    return GoldArtifactWriteResult.model_validate(asdict(result))
