"""Strict contracts for one immutable, replayable analysis context bundle."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from apps.analysis.state.hashing import content_hash
from apps.analysis.state.schemas import StateScope


LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION = "analysis_context_bundle.v1"
SCOPED_CONTEXT_BUNDLE_SCHEMA_VERSION = "analysis_context_bundle.v2"
CONTEXT_BUNDLE_SCHEMA_VERSION = "analysis_context_bundle.v3"
_V3_ONLY_FIELDS = frozenset(
    {
        "evidence_delta_decision",
        "deferred_queue",
        "processed_above_frontier",
        "selection_decisions",
        "selection_trace",
        "freshness_sla_seconds",
        "default_freshness_sla_seconds",
    }
)
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
    schema_version: Literal[
        "analysis_context_bundle.v1",
        "analysis_context_bundle.v2",
        "analysis_context_bundle.v3",
    ] = CONTEXT_BUNDLE_SCHEMA_VERSION
    state_scope: StateScope | None = None
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
    evidence_delta_decision: dict[str, Any] | None = None
    deferred_queue: list[dict[str, Any]] = Field(default_factory=list)
    processed_above_frontier: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    selection_decisions: list[dict[str, Any]] = Field(default_factory=list)
    selection_trace: dict[str, Any] | None = None
    freshness_sla_seconds: dict[str, StrictInt] = Field(default_factory=dict)
    default_freshness_sla_seconds: StrictInt | None = None
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

    @field_validator("evidence_delta_decision", mode="before")
    @classmethod
    def _normalize_evidence_delta_decision(cls, value: Any) -> Any:
        if value is None:
            return None
        from apps.analysis.evidence_delta.schemas import EvidenceDeltaDecision

        return EvidenceDeltaDecision.model_validate(value).model_dump(mode="json")

    @field_validator("deferred_queue", mode="before")
    @classmethod
    def _normalize_deferred_queue(cls, value: Any) -> list[dict[str, Any]]:
        from apps.analysis.context_bundle.selection import DeferredEvidencePointer

        normalized = [
            DeferredEvidencePointer.model_validate(item).model_dump(mode="json")
            for item in (value or [])
        ]
        return sorted(
            normalized,
            key=lambda item: (item["source"], item["ingested_at"], item["evidence_id"]),
        )

    @field_validator("processed_above_frontier", mode="before")
    @classmethod
    def _normalize_processed_above_frontier(cls, value: Any) -> dict[str, list[dict[str, Any]]]:
        from apps.analysis.context_bundle.selection import DeferredEvidencePointer

        return {
            str(source).strip(): sorted(
                [
                    DeferredEvidencePointer.model_validate(item).model_dump(mode="json")
                    for item in pointers
                ],
                key=lambda item: (item["ingested_at"], item["evidence_id"]),
            )
            for source, pointers in sorted(dict(value or {}).items())
        }

    @field_validator("selection_decisions", mode="before")
    @classmethod
    def _normalize_selection_decisions(cls, value: Any) -> list[dict[str, Any]]:
        from apps.analysis.context_bundle.selection import EvidenceSelectionDecision

        normalized = [
            EvidenceSelectionDecision.model_validate(item).model_dump(mode="json")
            for item in (value or [])
        ]
        return sorted(
            normalized,
            key=lambda item: (item["source"], item["evidence_id"], item["outcome"]),
        )

    @field_validator("selection_trace", mode="before")
    @classmethod
    def _normalize_selection_trace(cls, value: Any) -> Any:
        if value is None:
            return None
        from apps.analysis.context_bundle.selection import EvidenceSelectionTrace

        return EvidenceSelectionTrace.model_validate(value).model_dump(mode="json")

    @field_validator("freshness_sla_seconds")
    @classmethod
    def _normalize_freshness_slas(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for source, sla_seconds in sorted(value.items()):
            source_name = _required_text(source, "freshness SLA source")
            if sla_seconds < 0:
                raise ValueError("freshness SLA seconds must be non-negative integers")
            normalized[source_name] = sla_seconds
        return normalized

    @model_validator(mode="after")
    def _validate_bundle(self) -> "AnalysisContextBundle":
        payload = self.model_dump(mode="json")
        _reject_transport_keys(payload)
        if self.schema_version == LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION:
            if self.state_scope is not None:
                raise ValueError("legacy context bundle must not declare state_scope")
        elif self.state_scope is None:
            raise ValueError("scoped context bundle requires state_scope")
        if self.schema_version == CONTEXT_BUNDLE_SCHEMA_VERSION:
            self._validate_v3_selection_contract()
        elif any(
            (
                self.evidence_delta_decision is not None,
                bool(self.deferred_queue),
                bool(self.processed_above_frontier),
                bool(self.selection_decisions),
                self.selection_trace is not None,
                bool(self.freshness_sla_seconds),
                self.default_freshness_sla_seconds is not None,
            )
        ):
            raise ValueError("context bundle v1/v2 must not carry v3 selection fields")
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
        expected_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:context-bundle:{expected}")
        )
        if self.bundle_id != expected_id:
            raise ValueError("bundle_id does not match content_hash")
        if self.budget_trace.within_budget is not True:
            raise ValueError("persisted context bundle must be within budget")
        return self

    def _validate_v3_selection_contract(self) -> None:
        # Imports stay local because selection imports EvidenceItem/EvidenceCursor
        # from this module.
        from apps.analysis.evidence_delta.schemas import EvidenceDeltaDecision
        from apps.analysis.context_bundle.selection import (
            DeferredEvidencePointer,
            EvidenceSelectionDecision,
            EvidenceSelectionTrace,
        )

        if self.selection_trace is None or self.evidence_delta_decision is None:
            raise ValueError("context bundle v3 requires decision and selection_trace")
        trace = EvidenceSelectionTrace.model_validate(self.selection_trace)
        delta_decision = EvidenceDeltaDecision.model_validate(self.evidence_delta_decision)
        if (
            delta_decision.asset != self.asset
            or delta_decision.state_scope != self.state_scope
            or delta_decision.canonical_state_id != self.canonical_state_id
        ):
            raise ValueError("evidence delta decision identity does not match bundle")
        for pointer in self.deferred_queue:
            DeferredEvidencePointer.model_validate(pointer)
        for source, pointers in self.processed_above_frontier.items():
            if not str(source).strip():
                raise ValueError("processed_above_frontier source must not be blank")
            for pointer in pointers:
                validated = DeferredEvidencePointer.model_validate(pointer)
                if validated.source != source:
                    raise ValueError(
                        "processed_above_frontier source does not match pointer source"
                    )
        decisions = [
            EvidenceSelectionDecision.model_validate(decision)
            for decision in self.selection_decisions
        ]
        outcome_counts = {
            outcome: sum(decision.outcome == outcome for decision in decisions)
            for outcome in ("retained", "deferred", "rejected")
        }
        if (
            trace.retained_count != outcome_counts["retained"]
            or trace.deferred_count != outcome_counts["deferred"]
            or trace.rejected_count != outcome_counts["rejected"]
            or trace.eligible_count != trace.retained_count + trace.deferred_count
            or len(decisions)
            != trace.retained_count + trace.deferred_count + trace.rejected_count
            or len(self.deferred_queue) != trace.deferred_count
        ):
            raise ValueError("selection trace counts do not match selection decisions")
        decision_keys = [(decision.source, decision.evidence_id) for decision in decisions]
        if len(decision_keys) != len(set(decision_keys)):
            raise ValueError("selection decisions must be unique by source and evidence_id")
        deferred_decision_refs = {
            (decision.source, decision.evidence_id)
            for decision in decisions
            if decision.outcome == "deferred"
        }
        deferred_pointer_refs = {
            (str(pointer["source"]), str(pointer["evidence_id"]))
            for pointer in self.deferred_queue
        }
        if deferred_pointer_refs != deferred_decision_refs:
            raise ValueError("deferred queue does not match deferred selection decisions")
        processed_refs = [
            (str(pointer["source"]), str(pointer["evidence_id"]))
            for pointers in self.processed_above_frontier.values()
            for pointer in pointers
        ]
        if (
            len(processed_refs) != len(set(processed_refs))
            or set(processed_refs) & deferred_pointer_refs
        ):
            raise ValueError("processed frontier identities must be unique and not deferred")
        if (
            trace.retained_tokens
            != sum(
                decision.estimated_tokens
                for decision in decisions
                if decision.outcome == "retained"
            )
            or trace.deferred_tokens
            != sum(
                decision.estimated_tokens
                for decision in decisions
                if decision.outcome == "deferred"
            )
            or trace.mandatory_tokens
            != sum(decision.estimated_tokens for decision in decisions if decision.mandatory)
        ):
            raise ValueError("selection trace token totals do not match selection decisions")
        if self.default_freshness_sla_seconds is None:
            raise ValueError("context bundle v3 requires a default freshness SLA")
        if self.default_freshness_sla_seconds < 0:
            raise ValueError("default freshness SLA must be non-negative")
        eligible_sources = {
            decision.source
            for decision in decisions
            if decision.outcome in {"retained", "deferred"}
        }
        if not eligible_sources.issubset(self.freshness):
            raise ValueError("freshness must cover every eligible evidence source")

        retained_refs = {
            (decision.source, decision.evidence_id)
            for decision in decisions
            if decision.outcome == "retained"
        }
        facts_block = next(block for block in self.blocks if block.name == "facts")
        accepted_fact_refs = {
            ("figure_fact", str(item["figure_fact_id"]))
            for item in facts_block.payload
            if isinstance(item, dict)
            and item.get("quality_status") == "accepted"
            and item.get("figure_fact_id")
        }
        allowed_refs = retained_refs | accepted_fact_refs
        evaluated_refs = {
            (ref.source, ref.evidence_id)
            for item in delta_decision.evaluated_items
            for ref in item.evidence_refs
        }
        if evaluated_refs != allowed_refs:
            raise ValueError("evidence delta decision refs do not match retained bundle facts")

        delta_block = next(block for block in self.blocks if block.name == "delta_evidence")
        block_refs = {
            (str(item.get("source") or ""), str(item.get("evidence_id") or ""))
            for item in delta_block.payload
            if isinstance(item, dict)
        }
        if block_refs != retained_refs:
            raise ValueError("retained selection decisions do not match delta evidence block")


def compute_bundle_content_hash(value: AnalysisContextBundle | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("bundle_id", None)
    payload.pop("content_hash", None)
    payload.pop("assembled_at", None)
    schema_version = payload.get("schema_version")
    if schema_version == LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION:
        payload.pop("state_scope", None)
    if schema_version in {
        LEGACY_CONTEXT_BUNDLE_SCHEMA_VERSION,
        SCOPED_CONTEXT_BUNDLE_SCHEMA_VERSION,
    }:
        for field in _V3_ONLY_FIELDS:
            payload.pop(field, None)
    elif schema_version == CONTEXT_BUNDLE_SCHEMA_VERSION:
        payload = _canonicalize_v3_hash_fields(payload)
    return content_hash(payload, exclude_keys=frozenset())


def _canonicalize_v3_hash_fields(payload: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.context_bundle.selection import (
        DeferredEvidencePointer,
        EvidenceSelectionDecision,
        EvidenceSelectionTrace,
    )
    from apps.analysis.evidence_delta.schemas import EvidenceDeltaDecision

    normalized = dict(payload)
    decision = normalized.get("evidence_delta_decision")
    if decision is not None:
        normalized["evidence_delta_decision"] = EvidenceDeltaDecision.model_validate(
            decision
        ).model_dump(mode="json")
    normalized["deferred_queue"] = sorted(
        [
            DeferredEvidencePointer.model_validate(item).model_dump(mode="json")
            for item in normalized.get("deferred_queue") or []
        ],
        key=lambda item: (item["source"], item["ingested_at"], item["evidence_id"]),
    )
    normalized["processed_above_frontier"] = {
        str(source).strip(): sorted(
            [
                DeferredEvidencePointer.model_validate(item).model_dump(mode="json")
                for item in pointers
            ],
            key=lambda item: (item["ingested_at"], item["evidence_id"]),
        )
        for source, pointers in sorted(
            dict(normalized.get("processed_above_frontier") or {}).items()
        )
    }
    normalized["selection_decisions"] = sorted(
        [
            EvidenceSelectionDecision.model_validate(item).model_dump(mode="json")
            for item in normalized.get("selection_decisions") or []
        ],
        key=lambda item: (item["source"], item["evidence_id"], item["outcome"]),
    )
    trace = normalized.get("selection_trace")
    if trace is not None:
        normalized["selection_trace"] = EvidenceSelectionTrace.model_validate(trace).model_dump(
            mode="json"
        )
    normalized["freshness_sla_seconds"] = {
        str(source).strip(): value
        for source, value in sorted(
            dict(normalized.get("freshness_sla_seconds") or {}).items()
        )
    }
    return normalized


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
