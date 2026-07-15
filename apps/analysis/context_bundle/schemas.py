"""Strict contracts for one immutable, replayable analysis context bundle."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.state.hashing import content_hash


CONTEXT_BUNDLE_SCHEMA_VERSION = "analysis_context_bundle.v1"
_TRANSPORT_KEYS = frozenset(
    {
        "provider",
        "provider_id",
        "thread",
        "thread_id",
        "conversation",
        "conversation_id",
        "messages",
    }
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceCursor(_StrictFrozenModel):
    ingested_at: AwareDatetime
    evidence_id: str = Field(min_length=1, max_length=255)

    @field_validator("evidence_id")
    @classmethod
    def _strip_evidence_id(cls, value: str) -> str:
        return _required_text(value, "evidence_id")


class EvidenceItem(_StrictFrozenModel):
    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)
    business_time: AwareDatetime
    ingested_at: AwareDatetime
    session: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any]
    source_ref: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "evidence_id")
    @classmethod
    def _strip_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("session")
    @classmethod
    def _strip_session(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "session")

    @model_validator(mode="after")
    def _reject_transport_metadata(self) -> "EvidenceItem":
        _reject_transport_keys(self.payload)
        _reject_transport_keys(self.source_ref)
        return self


class ContextBlock(_StrictFrozenModel):
    name: Literal["canonical_state", "delta_evidence", "facts"]
    payload: Any
    utf8_bytes: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    trim_reasons: list[str] = Field(default_factory=list)
    retained_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_transport_metadata(self) -> "ContextBlock":
        _reject_transport_keys(self.payload)
        encoded = _canonical_bytes(self.payload)
        if self.utf8_bytes != len(encoded):
            raise ValueError("utf8_bytes does not match block payload")
        if self.estimated_tokens != _estimate_tokens(encoded):
            raise ValueError("estimated_tokens does not match block payload")
        return self


class ContextBudgetTrace(_StrictFrozenModel):
    budget_tokens: int = Field(gt=0)
    total_utf8_bytes: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    within_budget: bool
    blocks: list[dict[str, Any]]
    trim_reasons: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_budget_status(self) -> "ContextBudgetTrace":
        if self.within_budget != (self.estimated_tokens <= self.budget_tokens):
            raise ValueError("within_budget contradicts estimated_tokens")
        return self


class AnalysisContextBundle(_StrictFrozenModel):
    schema_version: Literal["analysis_context_bundle.v1"] = CONTEXT_BUNDLE_SCHEMA_VERSION
    bundle_id: str
    content_hash: str
    run_id: str
    asset: str
    canonical_state_id: str
    cutoff_at: AwareDatetime
    assembled_at: AwareDatetime
    evidence_cursors: dict[str, EvidenceCursor] = Field(default_factory=dict)
    next_evidence_cursors: dict[str, EvidenceCursor] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    alignment: dict[str, Any] = Field(default_factory=dict)
    blocks: list[ContextBlock] = Field(min_length=1)
    budget_trace: ContextBudgetTrace
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("bundle_id", "run_id", "asset", "canonical_state_id")
    @classmethod
    def _strip_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("content_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        return normalized

    @model_validator(mode="after")
    def _validate_bundle(self) -> "AnalysisContextBundle":
        payload = self.model_dump(mode="json")
        _reject_transport_keys(payload)
        if any(not source.strip() for source in self.evidence_cursors):
            raise ValueError("evidence cursor source must not be blank")
        if any(not source.strip() for source in self.next_evidence_cursors):
            raise ValueError("next evidence cursor source must not be blank")
        block_bytes = sum(block.utf8_bytes for block in self.blocks)
        block_tokens = sum(block.estimated_tokens for block in self.blocks)
        if self.budget_trace.total_utf8_bytes != block_bytes:
            raise ValueError("budget total_utf8_bytes does not match blocks")
        if self.budget_trace.estimated_tokens != block_tokens:
            raise ValueError("budget estimated_tokens does not match blocks")
        expected_trace_blocks = [
            {
                "name": block.name,
                "utf8_bytes": block.utf8_bytes,
                "estimated_tokens": block.estimated_tokens,
                "retained_evidence_ids": list(block.retained_evidence_ids),
            }
            for block in self.blocks
        ]
        if self.budget_trace.blocks != expected_trace_blocks:
            raise ValueError("budget block trace does not match blocks")
        expected_reasons = [
            {"block": block.name, "reason": reason}
            for block in sorted(self.blocks, key=lambda item: item.name)
            for reason in block.trim_reasons
        ]
        if self.budget_trace.trim_reasons != expected_reasons:
            raise ValueError("budget trim reasons do not match blocks")
        expected = compute_bundle_content_hash(payload)
        if self.content_hash != expected:
            raise ValueError("content_hash does not match bundle content")
        if self.budget_trace.within_budget is not True:
            raise ValueError("persisted context bundle must be within budget")
        return self


def compute_bundle_content_hash(value: AnalysisContextBundle | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("bundle_id", None)
    payload.pop("content_hash", None)
    payload.pop("assembled_at", None)
    return content_hash(payload, exclude_keys=frozenset())


def _reject_transport_keys(value: Any, *, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _TRANSPORT_KEYS:
                raise ValueError(f"provider conversation metadata is forbidden at {path}.{key}")
            _reject_transport_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_transport_keys(item, path=f"{path}[{index}]")


def _required_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _estimate_tokens(encoded: bytes) -> int:
    return (len(encoded) + 2) // 3
