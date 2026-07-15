"""Deterministic assembly of canonical state plus per-source evidence deltas."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from apps.analysis.context_bundle.schemas import (
    AnalysisContextBundle,
    ContextBlock,
    ContextBudgetTrace,
    EvidenceCursor,
    EvidenceItem,
    compute_bundle_content_hash,
)


DEFAULT_CONTEXT_TOKEN_BUDGET = 15_000
_HISTORY_BODY_KEYS = frozenset(
    {
        "article_markdown",
        "full_report",
        "previous_report",
        "previous_analysis_report",
        "previous_daily",
        "previous_daily_analysis",
        "weekly_anchor",
        "weekly_report",
        "weekly_report_body",
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


class ContextBundleBudgetExceeded(ValueError):
    def __init__(self, trace: dict[str, Any]) -> None:
        super().__init__(
            "context bundle budget exceeded: "
            f"estimated_tokens={trace['estimated_tokens']}; budget={trace['budget_tokens']}"
        )
        self.trace = trace


def select_incremental_evidence(
    evidence: list[EvidenceItem | dict[str, Any]],
    *,
    cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
    cutoff_at: datetime,
    trim_reasons: dict[str, list[str]] | None = None,
) -> list[EvidenceItem]:
    """Select evidence by each source's ingest cursor, not by business time."""

    _require_aware_datetime(cutoff_at, field="cutoff_at")
    normalized_cursors = {
        source: value if isinstance(value, EvidenceCursor) else EvidenceCursor.model_validate(value)
        for source, value in (cursors or {}).items()
    }
    selected: list[EvidenceItem] = []
    for raw_item in evidence:
        sanitized = _sanitize_value(
            raw_item.model_dump(mode="json") if isinstance(raw_item, EvidenceItem) else raw_item,
            trim_reasons=trim_reasons,
        )
        item = EvidenceItem.model_validate(sanitized)
        if item.ingested_at > cutoff_at:
            continue
        cursor = normalized_cursors.get(item.source)
        if cursor is not None and (item.ingested_at, item.evidence_id) <= (
            cursor.ingested_at,
            cursor.evidence_id,
        ):
            continue
        selected.append(item)
    return sorted(selected, key=lambda item: (item.ingested_at, item.evidence_id, item.source))


def assemble_context_bundle(
    *,
    run_id: str,
    asset: str,
    canonical_state_id: str,
    canonical_state: dict[str, Any],
    evidence: list[EvidenceItem | dict[str, Any]],
    evidence_cursors: dict[str, EvidenceCursor | dict[str, Any]] | None,
    cutoff_at: datetime,
    assembled_at: datetime,
    facts: list[dict[str, Any]] | None = None,
    expected_session: str | None = None,
    max_alignment_seconds: int = 86_400,
    budget_tokens: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> AnalysisContextBundle:
    """Build a stable bundle; dropped evidence never advances its source cursor."""

    if budget_tokens < 1:
        raise ValueError("budget_tokens must be positive")
    if max_alignment_seconds < 0:
        raise ValueError("max_alignment_seconds must be non-negative")
    _require_aware_datetime(cutoff_at, field="cutoff_at")
    _require_aware_datetime(assembled_at, field="assembled_at")

    trim_reasons: dict[str, list[str]] = defaultdict(list)
    state_payload = _compact_value(
        _sanitize_value(canonical_state, trim_reasons=trim_reasons, block="canonical_state"),
        trim_reasons=trim_reasons,
        block="canonical_state",
    )
    selected = select_incremental_evidence(
        evidence,
        cursors=evidence_cursors,
        cutoff_at=cutoff_at,
        trim_reasons=trim_reasons,
    )
    evidence_payload = [
        _compact_value(
            item.model_dump(mode="json"),
            trim_reasons=trim_reasons,
            block="delta_evidence",
        )
        for item in selected
    ]
    facts_payload = [
        _compact_value(
            _sanitize_value(item, trim_reasons=trim_reasons, block="facts"),
            trim_reasons=trim_reasons,
            block="facts",
        )
        for item in (facts or [])
    ]

    retained = list(selected)
    while True:
        blocks = _build_blocks(
            state_payload=state_payload,
            evidence_payload=evidence_payload,
            facts_payload=facts_payload,
            retained_evidence=retained,
            trim_reasons=trim_reasons,
        )
        trace = _budget_trace(blocks, budget_tokens=budget_tokens, trim_reasons=trim_reasons)
        if trace["within_budget"]:
            break
        if evidence_payload:
            evidence_payload.pop()
            deferred = retained.pop()
            trim_reasons["delta_evidence"].append(
                f"budget_deferred:{deferred.evidence_id}"
            )
            continue
        if facts_payload:
            facts_payload.pop(0)
            trim_reasons["facts"].append("budget_dropped_oldest_fact")
            continue
        raise ContextBundleBudgetExceeded(trace)

    normalized_cursors = {
        source: value if isinstance(value, EvidenceCursor) else EvidenceCursor.model_validate(value)
        for source, value in (evidence_cursors or {}).items()
    }
    next_cursors = dict(normalized_cursors)
    for item in retained:
        cursor = EvidenceCursor(ingested_at=item.ingested_at, evidence_id=item.evidence_id)
        current = next_cursors.get(item.source)
        if current is None or (cursor.ingested_at, cursor.evidence_id) > (
            current.ingested_at,
            current.evidence_id,
        ):
            next_cursors[item.source] = cursor

    freshness = _freshness(retained, cutoff_at=cutoff_at)
    session = _session_status(retained, expected_session=expected_session)
    alignment = _alignment_status(retained, max_alignment_seconds=max_alignment_seconds)
    source_refs = [dict(item.source_ref) for item in retained if item.source_ref]
    base_payload = {
        "schema_version": "analysis_context_bundle.v1",
        "run_id": str(run_id).strip(),
        "asset": str(asset).strip(),
        "canonical_state_id": str(canonical_state_id).strip(),
        "cutoff_at": _json_datetime(cutoff_at),
        "evidence_cursors": {
            source: cursor.model_dump(mode="json") for source, cursor in normalized_cursors.items()
        },
        "next_evidence_cursors": {
            source: cursor.model_dump(mode="json") for source, cursor in next_cursors.items()
        },
        "freshness": freshness,
        "session": session,
        "alignment": alignment,
        "blocks": [block.model_dump(mode="json") for block in blocks],
        "budget_trace": trace,
        "source_refs": source_refs,
    }
    resolved_hash = compute_bundle_content_hash(base_payload)
    resolved_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:context-bundle:{resolved_hash}")
    )
    return AnalysisContextBundle.model_validate(
        {
            **base_payload,
            "bundle_id": resolved_id,
            "content_hash": resolved_hash,
            "assembled_at": assembled_at,
        }
    )


def _build_blocks(
    *,
    state_payload: Any,
    evidence_payload: list[dict[str, Any]],
    facts_payload: list[dict[str, Any]],
    retained_evidence: list[EvidenceItem],
    trim_reasons: dict[str, list[str]],
) -> list[ContextBlock]:
    values = [
        ("canonical_state", state_payload, []),
        ("delta_evidence", evidence_payload, [item.evidence_id for item in retained_evidence]),
        ("facts", facts_payload, []),
    ]
    blocks = []
    for name, payload, retained_ids in values:
        encoded = _canonical_bytes(payload)
        blocks.append(
            ContextBlock(
                name=name,
                payload=payload,
                utf8_bytes=len(encoded),
                estimated_tokens=_estimate_tokens(encoded),
                trim_reasons=list(trim_reasons.get(name) or []),
                retained_evidence_ids=retained_ids,
            )
        )
    return blocks


def _budget_trace(
    blocks: list[ContextBlock],
    *,
    budget_tokens: int,
    trim_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    total_bytes = sum(block.utf8_bytes for block in blocks)
    estimated_tokens = sum(block.estimated_tokens for block in blocks)
    return ContextBudgetTrace(
        budget_tokens=budget_tokens,
        total_utf8_bytes=total_bytes,
        estimated_tokens=estimated_tokens,
        within_budget=estimated_tokens <= budget_tokens,
        blocks=[
            {
                "name": block.name,
                "utf8_bytes": block.utf8_bytes,
                "estimated_tokens": block.estimated_tokens,
                "retained_evidence_ids": list(block.retained_evidence_ids),
            }
            for block in blocks
        ],
        trim_reasons=[
            {"block": block, "reason": reason}
            for block in sorted(trim_reasons)
            for reason in trim_reasons[block]
        ],
    ).model_dump(mode="json")


def _sanitize_value(
    value: Any,
    *,
    trim_reasons: dict[str, list[str]] | None,
    block: str = "delta_evidence",
) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _TRANSPORT_KEYS:
                continue
            if normalized in _HISTORY_BODY_KEYS:
                if trim_reasons is not None:
                    trim_reasons[block].append(f"omitted_field:{key}")
                continue
            result[str(key)] = _sanitize_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
            )
        return result
    if isinstance(value, list):
        return [
            _sanitize_value(item, trim_reasons=trim_reasons, block=block) for item in value
        ]
    return value


def _compact_value(
    value: Any,
    *,
    trim_reasons: dict[str, list[str]],
    block: str,
    depth: int = 0,
) -> Any:
    if depth >= 8 and isinstance(value, (dict, list)):
        trim_reasons[block].append("nested_depth_limited")
        return "[nested data omitted]"
    if isinstance(value, dict):
        items = list(value.items())
        if len(items) > 80:
            trim_reasons[block].append("mapping_keys_limited")
            items = items[:80]
        return {
            str(key): _compact_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
                depth=depth + 1,
            )
            for key, item in items
        }
    if isinstance(value, list):
        if len(value) > 80:
            trim_reasons[block].append("list_items_limited")
        return [
            _compact_value(
                item,
                trim_reasons=trim_reasons,
                block=block,
                depth=depth + 1,
            )
            for item in value[:80]
        ]
    if isinstance(value, str) and len(value) > 2_000:
        trim_reasons[block].append("text_value_limited")
        marker = "...[deterministic trim]..."
        remaining = 2_000 - len(marker)
        return f"{value[: remaining * 3 // 4]}{marker}{value[-remaining // 4 :]}"
    return value


def _freshness(items: list[EvidenceItem], *, cutoff_at: datetime) -> dict[str, Any]:
    latest: dict[str, EvidenceItem] = {}
    for item in items:
        current = latest.get(item.source)
        if current is None or item.ingested_at > current.ingested_at:
            latest[item.source] = item
    return {
        source: {
            "status": "current",
            "latest_ingested_at": _json_datetime(item.ingested_at),
            "age_seconds": max(0.0, (cutoff_at - item.ingested_at).total_seconds()),
        }
        for source, item in sorted(latest.items())
    }


def _session_status(
    items: list[EvidenceItem], *, expected_session: str | None
) -> dict[str, Any]:
    observed = sorted({item.session for item in items if item.session})
    if expected_session is None:
        status = "not_checked"
    elif not observed:
        status = "missing"
    elif observed == [expected_session]:
        status = "aligned"
    else:
        status = "mismatch"
    return {
        "status": status,
        "expected": expected_session,
        "observed": observed,
    }


def _alignment_status(
    items: list[EvidenceItem], *, max_alignment_seconds: int
) -> dict[str, Any]:
    if len(items) < 2:
        span = 0.0
    else:
        times = [item.business_time for item in items]
        span = (max(times) - min(times)).total_seconds()
    return {
        "status": "aligned" if span <= max_alignment_seconds else "misaligned",
        "business_time_span_seconds": span,
        "max_alignment_seconds": max_alignment_seconds,
    }


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


def _json_datetime(value: datetime) -> str:
    normalized = value.astimezone(UTC).isoformat()
    return normalized.replace("+00:00", "Z")


def _require_aware_datetime(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
