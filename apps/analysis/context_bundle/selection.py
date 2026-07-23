"""Pure, deterministic evidence selection with gap-safe per-source frontiers.

This module deliberately does not infer materiality.  Callers provide stable
priority metadata and token estimates; the selector only applies that ordering
to an evidence-only budget and records enough state for a later replay.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from apps.analysis.context_bundle.schemas import EvidenceCursor, EvidenceItem


class EvidencePriorityClass(StrEnum):
    MANDATORY_CRITICAL = "mandatory_critical"
    CONFIRMED_INVALIDATION = "confirmed_invalidation"
    CONFIRMED_KEY_LEVEL = "confirmed_key_level"
    MARKET_OPTIONS_REGIME = "market_options_regime"
    LATEST_HIGH_QUALITY = "latest_high_quality"
    ORDINARY_CURRENT = "ordinary_current"
    BACKLOG = "backlog"


_PRIORITY_RANK = {
    EvidencePriorityClass.MANDATORY_CRITICAL: 0,
    EvidencePriorityClass.CONFIRMED_INVALIDATION: 1,
    EvidencePriorityClass.CONFIRMED_KEY_LEVEL: 2,
    EvidencePriorityClass.MARKET_OPTIONS_REGIME: 3,
    EvidencePriorityClass.LATEST_HIGH_QUALITY: 4,
    EvidencePriorityClass.ORDINARY_CURRENT: 5,
    EvidencePriorityClass.BACKLOG: 6,
}


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidencePriority(_StrictFrozenModel):
    """Caller-owned priority facts; no importance is inferred here."""

    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)
    semantic_hash: str
    priority_class: EvidencePriorityClass
    materiality: str = Field(min_length=1, max_length=64)
    mandatory: bool = False
    reason_codes: tuple[str, ...] = ()
    estimated_tokens: int = Field(gt=0)

    @field_validator("source", "evidence_id", "materiality")
    @classmethod
    def _strip_required_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("semantic_hash")
    @classmethod
    def _validate_semantic_hash(cls, value: str) -> str:
        return _sha256_digest(value, field="semantic_hash")

    @field_validator("reason_codes")
    @classmethod
    def _normalize_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_required_text(item, "reason_code") for item in value}))

    @model_validator(mode="after")
    def _validate_mandatory_class(self) -> "EvidencePriority":
        class_is_mandatory = self.priority_class is EvidencePriorityClass.MANDATORY_CRITICAL
        if self.mandatory != class_is_mandatory:
            raise ValueError(
                "mandatory must be true exactly when priority_class is mandatory_critical"
            )
        return self


class DeferredEvidencePointer(_StrictFrozenModel):
    """Immutable identity used by deferred and processed frontier state."""

    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)
    ingested_at: AwareDatetime
    semantic_hash: str
    deferred_priority_class: EvidencePriorityClass | None = None
    deferral_reasons: tuple[str, ...] = ()

    @field_validator("source", "evidence_id")
    @classmethod
    def _strip_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("semantic_hash")
    @classmethod
    def _validate_semantic_hash(cls, value: str) -> str:
        return _sha256_digest(value, field="semantic_hash")

    @field_validator("deferral_reasons")
    @classmethod
    def _normalize_deferral_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_required_text(item, "deferral_reason") for item in value}))


class EvidenceSelectionKey(_StrictFrozenModel):
    """Source-aware evidence identity used for all selection state."""

    source: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)

    @field_validator("source", "evidence_id")
    @classmethod
    def _strip_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class EvidenceSelectionDecision(_StrictFrozenModel):
    source: str
    evidence_id: str
    outcome: Literal["retained", "deferred", "rejected"]
    estimated_tokens: int = Field(ge=0)
    priority_class: EvidencePriorityClass | None = None
    materiality: str | None = None
    mandatory: bool = False
    reasons: tuple[str, ...] = ()

    @field_validator("source", "evidence_id")
    @classmethod
    def _strip_identity(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("reasons")
    @classmethod
    def _normalize_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_required_text(item, "reason") for item in value}))


class EvidenceSelectionTrace(_StrictFrozenModel):
    evidence_budget_tokens: int = Field(ge=0)
    retained_tokens: int = Field(ge=0)
    deferred_tokens: int = Field(ge=0)
    mandatory_tokens: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    retained_count: int = Field(ge=0)
    deferred_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    priority_order: tuple[EvidencePriorityClass, ...]


class SelectionResult(_StrictFrozenModel):
    """Selection output; ``retained_evidence_keys`` is the authoritative identity."""

    retained_evidence_keys: tuple[EvidenceSelectionKey, ...]
    # Compatibility/display projection only; evidence IDs are not source-unique.
    retained_evidence_ids: tuple[str, ...]
    deferred_queue: tuple[DeferredEvidencePointer, ...]
    processed_above_frontier: dict[str, tuple[DeferredEvidencePointer, ...]]
    next_evidence_cursors: dict[str, EvidenceCursor]
    decisions: tuple[EvidenceSelectionDecision, ...]
    trace: EvidenceSelectionTrace


class EvidenceSelectionBudgetError(ValueError):
    """Raised when mandatory evidence alone cannot fit the evidence budget."""

    def __init__(
        self,
        *,
        required_tokens: int,
        budget_tokens: int,
        mandatory_evidence_keys: tuple[EvidenceSelectionKey, ...],
    ) -> None:
        super().__init__(
            "mandatory evidence exceeds evidence budget: "
            f"required_tokens={required_tokens}; budget_tokens={budget_tokens}"
        )
        self.required_tokens = required_tokens
        self.budget_tokens = budget_tokens
        self.mandatory_evidence_keys = mandatory_evidence_keys
        self.mandatory_evidence_ids = tuple(
            key.evidence_id for key in mandatory_evidence_keys
        )


class EvidenceSelectionStateError(ValueError):
    """Raised before selection when persisted frontier state is inconsistent."""


def select_material_evidence(
    *,
    evidence: list[EvidenceItem | dict[str, Any]],
    priorities: list[EvidencePriority | dict[str, Any]],
    evidence_cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
    cutoff_at: datetime,
    evidence_budget_tokens: int,
    deferred_queue: tuple[DeferredEvidencePointer | dict[str, Any], ...] = (),
    processed_above_frontier: dict[
        str, tuple[DeferredEvidencePointer | dict[str, Any], ...]
    ]
    | None = None,
) -> SelectionResult:
    """Select evidence and advance only each source's contiguous frontier.

    The function is side-effect free.  State validation completes before any
    selection result is built, so corrupt deferred/processed pointers fail
    closed without returning an advanced cursor.
    """

    _require_aware_datetime(cutoff_at, field="cutoff_at")
    if evidence_budget_tokens < 0:
        raise ValueError("evidence_budget_tokens must be non-negative")

    normalized_evidence = _normalize_evidence(evidence)
    normalized_priorities = _normalize_priorities(priorities)
    normalized_cursors = _normalize_cursors(evidence_cursors)
    normalized_deferred = _normalize_pointer_sequence(deferred_queue, label="deferred_queue")
    normalized_processed = _normalize_processed(processed_above_frontier)

    _validate_selection_state(
        evidence=normalized_evidence,
        priorities=normalized_priorities,
        cursors=normalized_cursors,
        cutoff_at=cutoff_at,
        deferred=normalized_deferred,
        processed=normalized_processed,
    )

    processed_keys = {
        (pointer.source, pointer.evidence_id)
        for pointers in normalized_processed.values()
        for pointer in pointers
    }
    candidates: list[tuple[EvidenceItem, EvidencePriority]] = []
    rejected: list[EvidenceSelectionDecision] = []

    for key, item in sorted(normalized_evidence.items(), key=_evidence_map_sort_key):
        priority = normalized_priorities[key]
        cursor = normalized_cursors.get(item.source)
        if item.ingested_at > cutoff_at:
            rejected.append(_decision(item, priority, outcome="rejected", reasons=("after_cutoff",)))
            continue
        if cursor is not None and _position(item) <= _position(cursor):
            rejected.append(
                _decision(item, priority, outcome="rejected", reasons=("at_or_before_frontier",))
            )
            continue
        if key in processed_keys:
            rejected.append(
                _decision(
                    item,
                    priority,
                    outcome="rejected",
                    reasons=("already_processed_above_frontier",),
                )
            )
            continue
        candidates.append((item, priority))

    persisted_deferred_keys = {
        (pointer.source, pointer.evidence_id) for pointer in normalized_deferred
    }
    ranked = sorted(
        candidates,
        key=lambda value: _selection_rank(
            value,
            persisted_deferred_keys=persisted_deferred_keys,
        ),
    )
    mandatory = [(item, priority) for item, priority in ranked if priority.mandatory]
    mandatory_tokens = sum(priority.estimated_tokens for _, priority in mandatory)
    if mandatory_tokens > evidence_budget_tokens:
        raise EvidenceSelectionBudgetError(
            required_tokens=mandatory_tokens,
            budget_tokens=evidence_budget_tokens,
            mandatory_evidence_keys=tuple(
                EvidenceSelectionKey(source=item.source, evidence_id=item.evidence_id)
                for item, _ in mandatory
            ),
        )

    retained: list[tuple[EvidenceItem, EvidencePriority]] = []
    deferred: list[tuple[EvidenceItem, EvidencePriority]] = []
    used_tokens = 0
    for item, priority in ranked:
        if priority.mandatory or used_tokens + priority.estimated_tokens <= evidence_budget_tokens:
            retained.append((item, priority))
            used_tokens += priority.estimated_tokens
        else:
            deferred.append((item, priority))

    retained_keys = {(item.source, item.evidence_id) for item, _ in retained}
    deferred_keys = {(item.source, item.evidence_id) for item, _ in deferred}
    pointer_by_key = {
        key: _pointer(
            item,
            normalized_priorities[key],
            deferred=key in deferred_keys,
        )
        for key, item in normalized_evidence.items()
        if item.ingested_at <= cutoff_at
        and (
            normalized_cursors.get(item.source) is None
            or _position(item) > _position(normalized_cursors[item.source])
        )
    }
    for pointers in normalized_processed.values():
        for pointer in pointers:
            pointer_by_key.setdefault((pointer.source, pointer.evidence_id), pointer)

    next_cursors, next_processed = _advance_frontiers(
        cursors=normalized_cursors,
        pointers=pointer_by_key,
        retained_keys=retained_keys,
        deferred_keys=deferred_keys,
        processed_keys=processed_keys,
    )

    retained_decisions = [
        _decision(item, priority, outcome="retained", reasons=priority.reason_codes)
        for item, priority in retained
    ]
    deferred_decisions = [
        _decision(
            item,
            priority,
            outcome="deferred",
            reasons=(*priority.reason_codes, "evidence_budget_exhausted"),
        )
        for item, priority in deferred
    ]
    decisions = tuple(
        [*retained_decisions, *deferred_decisions, *sorted(rejected, key=_decision_sort_key)]
    )
    deferred_pointers = tuple(
        sorted(
            (pointer_by_key[key] for key in deferred_keys),
            key=_pointer_sort_key,
        )
    )
    deferred_tokens = sum(priority.estimated_tokens for _, priority in deferred)
    return SelectionResult(
        retained_evidence_keys=tuple(
            EvidenceSelectionKey(source=item.source, evidence_id=item.evidence_id)
            for item, _ in retained
        ),
        retained_evidence_ids=tuple(item.evidence_id for item, _ in retained),
        deferred_queue=deferred_pointers,
        processed_above_frontier=next_processed,
        next_evidence_cursors=next_cursors,
        decisions=decisions,
        trace=EvidenceSelectionTrace(
            evidence_budget_tokens=evidence_budget_tokens,
            retained_tokens=used_tokens,
            deferred_tokens=deferred_tokens,
            mandatory_tokens=mandatory_tokens,
            eligible_count=len(ranked),
            retained_count=len(retained),
            deferred_count=len(deferred),
            rejected_count=len(rejected),
            priority_order=tuple(
                priority_class
                for priority_class, _ in sorted(_PRIORITY_RANK.items(), key=lambda item: item[1])
            ),
        ),
    )


def _normalize_evidence(
    evidence: list[EvidenceItem | dict[str, Any]],
) -> dict[tuple[str, str], EvidenceItem]:
    normalized: dict[tuple[str, str], EvidenceItem] = {}
    for raw_item in evidence:
        item = raw_item if isinstance(raw_item, EvidenceItem) else EvidenceItem.model_validate(raw_item)
        key = (item.source, item.evidence_id)
        if key in normalized:
            if normalized[key] == item:
                continue
            raise EvidenceSelectionStateError(
                f"conflicting duplicate evidence identity: {item.source}/{item.evidence_id}"
            )
        normalized[key] = item
    return normalized


def _normalize_priorities(
    priorities: list[EvidencePriority | dict[str, Any]],
) -> dict[tuple[str, str], EvidencePriority]:
    normalized: dict[tuple[str, str], EvidencePriority] = {}
    for raw_priority in priorities:
        priority = (
            raw_priority
            if isinstance(raw_priority, EvidencePriority)
            else EvidencePriority.model_validate(raw_priority)
        )
        key = (priority.source, priority.evidence_id)
        if key in normalized:
            if normalized[key] == priority:
                continue
            raise EvidenceSelectionStateError(
                f"conflicting duplicate evidence priority: {priority.source}/{priority.evidence_id}"
            )
        normalized[key] = priority
    return normalized


def _normalize_cursors(
    cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
) -> dict[str, EvidenceCursor]:
    normalized: dict[str, EvidenceCursor] = {}
    for raw_source, raw_cursor in sorted((cursors or {}).items()):
        source = _required_text(raw_source, "cursor source")
        normalized[source] = (
            raw_cursor
            if isinstance(raw_cursor, EvidenceCursor)
            else EvidenceCursor.model_validate(raw_cursor)
        )
    return normalized


def _normalize_pointer_sequence(
    pointers: tuple[DeferredEvidencePointer | dict[str, Any], ...],
    *,
    label: str,
) -> tuple[DeferredEvidencePointer, ...]:
    normalized: dict[tuple[str, str], DeferredEvidencePointer] = {}
    for raw_pointer in pointers:
        pointer = (
            raw_pointer
            if isinstance(raw_pointer, DeferredEvidencePointer)
            else DeferredEvidencePointer.model_validate(raw_pointer)
        )
        key = (pointer.source, pointer.evidence_id)
        if key in normalized:
            raise EvidenceSelectionStateError(
                f"duplicate {label} identity: {pointer.source}/{pointer.evidence_id}"
            )
        normalized[key] = pointer
    return tuple(sorted(normalized.values(), key=_pointer_sort_key))


def _normalize_processed(
    processed: dict[str, tuple[DeferredEvidencePointer | dict[str, Any], ...]] | None,
) -> dict[str, tuple[DeferredEvidencePointer, ...]]:
    normalized: dict[str, tuple[DeferredEvidencePointer, ...]] = {}
    seen: set[tuple[str, str]] = set()
    for raw_source, raw_pointers in sorted((processed or {}).items()):
        source = _required_text(raw_source, "processed source")
        pointers = _normalize_pointer_sequence(
            raw_pointers,
            label=f"processed_above_frontier[{source}]",
        )
        for pointer in pointers:
            if pointer.source != source:
                raise EvidenceSelectionStateError(
                    "processed_above_frontier source does not match pointer source"
                )
            key = (pointer.source, pointer.evidence_id)
            if key in seen:
                raise EvidenceSelectionStateError(
                    f"duplicate processed identity: {pointer.source}/{pointer.evidence_id}"
                )
            seen.add(key)
        if pointers:
            normalized[source] = pointers
    return normalized


def _validate_selection_state(
    *,
    evidence: dict[tuple[str, str], EvidenceItem],
    priorities: dict[tuple[str, str], EvidencePriority],
    cursors: dict[str, EvidenceCursor],
    cutoff_at: datetime,
    deferred: tuple[DeferredEvidencePointer, ...],
    processed: dict[str, tuple[DeferredEvidencePointer, ...]],
) -> None:
    missing_priorities = sorted(set(evidence) - set(priorities))
    if missing_priorities:
        source, evidence_id = missing_priorities[0]
        raise EvidenceSelectionStateError(f"missing evidence priority: {source}/{evidence_id}")

    deferred_keys = {(pointer.source, pointer.evidence_id) for pointer in deferred}
    processed_pointers = {
        (pointer.source, pointer.evidence_id): pointer
        for pointers in processed.values()
        for pointer in pointers
    }
    extra_priorities = sorted(set(priorities) - set(evidence) - set(processed_pointers))
    if extra_priorities:
        source, evidence_id = extra_priorities[0]
        raise EvidenceSelectionStateError(
            f"priority has no current or processed evidence: {source}/{evidence_id}"
        )
    overlap = sorted(deferred_keys & set(processed_pointers))
    if overlap:
        source, evidence_id = overlap[0]
        raise EvidenceSelectionStateError(
            f"evidence is both deferred and processed: {source}/{evidence_id}"
        )

    for pointer in deferred:
        key = (pointer.source, pointer.evidence_id)
        if key not in evidence:
            raise EvidenceSelectionStateError(
                f"deferred evidence is missing from replay input: {pointer.source}/{pointer.evidence_id}"
            )
        _validate_pointer(pointer, evidence[key], priorities[key], cursors, cutoff_at)

    for key, pointer in processed_pointers.items():
        item = evidence.get(key)
        priority = priorities.get(key)
        if priority is None:
            raise EvidenceSelectionStateError(
                f"missing processed evidence priority: {pointer.source}/{pointer.evidence_id}"
            )
        if pointer.semantic_hash != priority.semantic_hash:
            raise EvidenceSelectionStateError(
                f"processed semantic_hash mismatch: {pointer.source}/{pointer.evidence_id}"
            )
        if item is not None:
            _validate_pointer(pointer, item, priority, cursors, cutoff_at)
        else:
            _validate_pointer_position(pointer, cursors, cutoff_at)


def _validate_pointer(
    pointer: DeferredEvidencePointer,
    item: EvidenceItem,
    priority: EvidencePriority,
    cursors: dict[str, EvidenceCursor],
    cutoff_at: datetime,
) -> None:
    if pointer.ingested_at != item.ingested_at:
        raise EvidenceSelectionStateError(
            f"queued ingested_at mismatch: {pointer.source}/{pointer.evidence_id}"
        )
    if pointer.semantic_hash != priority.semantic_hash:
        raise EvidenceSelectionStateError(
            f"queued semantic_hash mismatch: {pointer.source}/{pointer.evidence_id}"
        )
    _validate_pointer_position(pointer, cursors, cutoff_at)


def _validate_pointer_position(
    pointer: DeferredEvidencePointer,
    cursors: dict[str, EvidenceCursor],
    cutoff_at: datetime,
) -> None:
    if pointer.ingested_at > cutoff_at:
        raise EvidenceSelectionStateError(
            f"queued evidence is after cutoff: {pointer.source}/{pointer.evidence_id}"
        )
    cursor = cursors.get(pointer.source)
    if cursor is not None and _position(pointer) <= _position(cursor):
        raise EvidenceSelectionStateError(
            f"queued evidence is at or before frontier: {pointer.source}/{pointer.evidence_id}"
        )


def _advance_frontiers(
    *,
    cursors: dict[str, EvidenceCursor],
    pointers: dict[tuple[str, str], DeferredEvidencePointer],
    retained_keys: set[tuple[str, str]],
    deferred_keys: set[tuple[str, str]],
    processed_keys: set[tuple[str, str]],
) -> tuple[dict[str, EvidenceCursor], dict[str, tuple[DeferredEvidencePointer, ...]]]:
    by_source: dict[str, list[DeferredEvidencePointer]] = defaultdict(list)
    for pointer in pointers.values():
        by_source[pointer.source].append(pointer)

    next_cursors = dict(cursors)
    next_processed: dict[str, tuple[DeferredEvidencePointer, ...]] = {}
    for source in sorted(by_source):
        current = cursors.get(source)
        gap_seen = False
        completed_above_gap: list[DeferredEvidencePointer] = []
        advanced: DeferredEvidencePointer | None = None
        for pointer in sorted(by_source[source], key=_pointer_position_sort_key):
            key = (pointer.source, pointer.evidence_id)
            completed = key in retained_keys or key in processed_keys
            if key not in deferred_keys and not completed:
                continue
            if not gap_seen and key in deferred_keys:
                gap_seen = True
                continue
            if completed and not gap_seen:
                advanced = pointer
            elif completed:
                completed_above_gap.append(pointer)
        if advanced is not None:
            next_cursors[source] = EvidenceCursor(
                ingested_at=advanced.ingested_at,
                evidence_id=advanced.evidence_id,
            )
        elif current is None:
            next_cursors.pop(source, None)
        if completed_above_gap:
            next_processed[source] = tuple(completed_above_gap)
    return ({source: next_cursors[source] for source in sorted(next_cursors)}, next_processed)


def _selection_rank(
    value: tuple[EvidenceItem, EvidencePriority],
    *,
    persisted_deferred_keys: set[tuple[str, str]],
) -> tuple[int, int, int, float, str, str]:
    item, priority = value
    return (
        0 if priority.mandatory else 1,
        _PRIORITY_RANK[priority.priority_class],
        0 if (item.source, item.evidence_id) in persisted_deferred_keys else 1,
        -item.ingested_at.timestamp(),
        item.source,
        item.evidence_id,
    )


def _decision(
    item: EvidenceItem,
    priority: EvidencePriority,
    *,
    outcome: Literal["retained", "deferred", "rejected"],
    reasons: tuple[str, ...],
) -> EvidenceSelectionDecision:
    return EvidenceSelectionDecision(
        source=item.source,
        evidence_id=item.evidence_id,
        outcome=outcome,
        estimated_tokens=priority.estimated_tokens,
        priority_class=priority.priority_class,
        materiality=priority.materiality,
        mandatory=priority.mandatory,
        reasons=reasons,
    )


def _pointer(
    item: EvidenceItem,
    priority: EvidencePriority,
    *,
    deferred: bool,
) -> DeferredEvidencePointer:
    return DeferredEvidencePointer(
        source=item.source,
        evidence_id=item.evidence_id,
        ingested_at=item.ingested_at,
        semantic_hash=priority.semantic_hash,
        deferred_priority_class=priority.priority_class if deferred else None,
        deferral_reasons=(
            (*priority.reason_codes, "evidence_budget_exhausted") if deferred else ()
        ),
    )


def _evidence_map_sort_key(
    value: tuple[tuple[str, str], EvidenceItem],
) -> tuple[str, datetime, str]:
    _, item = value
    return (item.source, item.ingested_at, item.evidence_id)


def _pointer_sort_key(pointer: DeferredEvidencePointer) -> tuple[str, datetime, str]:
    return (pointer.source, pointer.ingested_at, pointer.evidence_id)


def _pointer_position_sort_key(pointer: DeferredEvidencePointer) -> tuple[datetime, str]:
    return (pointer.ingested_at, pointer.evidence_id)


def _decision_sort_key(decision: EvidenceSelectionDecision) -> tuple[str, str]:
    return (decision.source, decision.evidence_id)


def _position(value: EvidenceItem | EvidenceCursor | DeferredEvidencePointer) -> tuple[datetime, str]:
    return (value.ingested_at, value.evidence_id)


def _required_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def _sha256_digest(value: str, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _require_aware_datetime(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
