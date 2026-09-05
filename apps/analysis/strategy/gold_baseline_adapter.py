"""Read-only adapter from verified Gold daily-close authority to live strategy.

The live strategy may consume intraday canonical candles for timing, but its
directional authority comes only from a verified Gold daily-close effective
head.  This module never repairs, selects, or writes a head: any missing,
invalid, non-directional, or future-dated authority is projected as no-trade.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseCanonicalHead,
    load_gold_daily_close_head,
    verify_gold_daily_close_bundle,
)


_DIRECTION_BY_STRATEGY_STATUS = {
    "LONG_WATCH": "long",
    "LONG_RESEARCH_TRIGGERED": "long",
    "SHORT_WATCH": "short",
    "SHORT_RESEARCH_TRIGGERED": "short",
}


def resolve_verified_gold_baseline(
    *,
    storage_root: Path,
    now: datetime,
) -> dict[str, Any]:
    """Resolve one verified daily-close authority projection without I/O side effects.

    A retained ``HOLD`` may expose the predecessor's effective head, but only
    after the *latest* receipt and its lineage have both been verified.  The
    caller can use ``authority_ready`` and ``direction`` directly as hard
    intraday gates.
    """
    root = Path(storage_root)
    current_time = _as_utc(now)
    try:
        lookup = load_gold_daily_close_head(storage_root=root)
    except (OSError, TypeError, ValueError):
        return _unavailable_projection(
            status="invalid",
            reason_code="gold_daily_close_head_lookup_failed",
        )

    if lookup.status != "found" or lookup.head is None or lookup.latest_receipt is None:
        return _unavailable_projection(
            status="invalid" if lookup.status in {"invalid", "ambiguous"} else "unavailable",
            reason_code=_prefixed_reason(lookup.reason_code),
            receipt=lookup.latest_receipt,
            artifact_refs=_lookup_artifact_refs(root, lookup.source_path),
        )

    head = lookup.head
    receipt = lookup.latest_receipt
    try:
        verification = verify_gold_daily_close_bundle(
            storage_root=root,
            bundle_path=head.latest_receipt_path.parent,
        )
    except (OSError, TypeError, ValueError):
        return _unavailable_projection(
            status="invalid",
            reason_code="gold_daily_close_bundle_verification_failed",
            receipt=receipt,
            artifact_refs=_head_artifact_refs(root, head),
        )

    if verification.status != "valid" or not _verified_head_matches(head, verification):
        return _unavailable_projection(
            status="invalid",
            reason_code="gold_daily_close_authority_lineage_invalid",
            receipt=receipt,
            artifact_refs=_head_artifact_refs(root, head),
        )

    if not _head_is_xauusd_daily_close(head):
        return _unavailable_projection(
            status="invalid",
            reason_code="gold_daily_close_authority_scope_invalid",
            receipt=receipt,
            artifact_refs=_head_artifact_refs(root, head),
        )

    strategy = head.strategy_decision
    state = head.analysis_state
    decision_as_of = _as_utc(receipt.decision_as_of)
    strategy_as_of = _as_utc(strategy.decision_as_of)
    state_as_of = _as_utc(state.as_of)
    if any(value > current_time for value in (decision_as_of, strategy_as_of, state_as_of)):
        return _unavailable_projection(
            status="invalid",
            reason_code="gold_daily_close_authority_future",
            receipt=receipt,
            head=head,
            artifact_refs=_head_artifact_refs(root, head),
        )

    strategy_status = _enum_value(strategy.status)
    strategy_direction = _enum_value(strategy.direction)
    expected_direction = _DIRECTION_BY_STRATEGY_STATUS.get(strategy_status)
    quality_status = _enum_value(state.quality_status)
    held = _enum_value(receipt.action) == "hold"
    projection = _head_projection(
        root=root,
        head=head,
        receipt=receipt,
        strategy_status=strategy_status,
        quality_status=quality_status,
        direction=expected_direction if expected_direction == strategy_direction else "none",
        status="held" if held else "accepted",
        reason_code="gold_daily_close_head_held" if held else "gold_daily_close_head_accepted",
    )

    if expected_direction is None or expected_direction != strategy_direction:
        projection.update(
            status="unavailable",
            reason_code="gold_strategy_status_not_directional",
            direction="none",
            authority_ready=False,
        )
    elif quality_status != "accepted":
        projection.update(
            status="unavailable",
            reason_code=f"gold_analysis_state_{quality_status}",
            direction="none",
            authority_ready=False,
        )
    return projection


def _verified_head_matches(head: DailyCloseCanonicalHead, verification: Any) -> bool:
    receipt = verification.receipt
    verified_head = verification.head
    effective = head.latest_receipt.effective_head
    if receipt is None or verified_head is None or effective is None:
        return False
    if (
        receipt.receipt_id != head.latest_receipt.receipt_id
        or receipt.effective_head != effective
        or _effective_identity(verified_head) != _effective_identity(head)
    ):
        return False
    return _effective_identity(head) == (
        effective.result_id,
        effective.feature_snapshot_id,
        effective.state_id,
        effective.transition_decision_hash,
        effective.strategy_id,
        effective.consistency_decision_id,
    )


def _effective_identity(head: DailyCloseCanonicalHead) -> tuple[str, str, str, str, str, str]:
    return (
        head.loop_result.result_id,
        head.feature_snapshot.snapshot_id,
        head.analysis_state.state_id,
        head.transition_decision.decision_hash,
        head.strategy_decision.decision_id,
        head.consistency_decision.decision_id,
    )


def _head_is_xauusd_daily_close(head: DailyCloseCanonicalHead) -> bool:
    return all(
        _enum_value(getattr(value, "asset", None)) == "XAUUSD"
        and _enum_value(getattr(value, "scope", None)) == "daily_close"
        for value in (
            head.feature_snapshot,
            head.analysis_state,
            head.strategy_policy_input,
            head.strategy_decision,
            head.loop_result,
        )
    )


def _head_projection(
    *,
    root: Path,
    head: DailyCloseCanonicalHead,
    receipt: Any,
    strategy_status: str,
    quality_status: str,
    direction: str,
    status: str,
    reason_code: str,
) -> dict[str, Any]:
    effective = receipt.effective_head
    assert effective is not None
    state = head.analysis_state
    return {
        "status": status,
        "reason_code": reason_code,
        "asset": "XAUUSD",
        "scope": "daily_close",
        "direction": direction,
        "strategy_status": strategy_status,
        "quality_status": quality_status,
        "decision_as_of": _as_utc(receipt.decision_as_of).isoformat(),
        "strategy_decision_as_of": _as_utc(head.strategy_decision.decision_as_of).isoformat(),
        "state_as_of": _as_utc(head.analysis_state.as_of).isoformat(),
        "gold_head_held": _enum_value(receipt.action) == "hold",
        "authority_ready": status in {"accepted", "held"} and direction in {"long", "short"} and quality_status == "accepted",
        "lineage_verified": True,
        "receipt_id": receipt.receipt_id,
        "result_id": effective.result_id,
        "feature_snapshot_id": effective.feature_snapshot_id,
        "state_id": effective.state_id,
        "transition_decision_hash": effective.transition_decision_hash,
        "strategy_id": effective.strategy_id,
        "consistency_decision_id": effective.consistency_decision_id,
        "strategy_policy_version": _enum_value(head.strategy_decision.policy_version),
        "is_trade_instruction": head.strategy_decision.is_trade_instruction,
        "confidence": state.confidence,
        "market_regime": _state_market_regime(state),
        "source_refs": _head_source_refs(head),
        "artifact_refs": _head_artifact_refs(root, head),
    }


def _unavailable_projection(
    *,
    status: str,
    reason_code: str,
    receipt: Any | None = None,
    head: DailyCloseCanonicalHead | None = None,
    artifact_refs: list[str] | None = None,
) -> dict[str, Any]:
    projection = {
        "status": status,
        "reason_code": reason_code,
        "asset": "XAUUSD",
        "scope": "daily_close",
        "direction": "none",
        "strategy_status": "unavailable",
        "quality_status": "unavailable",
        "decision_as_of": _iso_datetime(getattr(receipt, "decision_as_of", None)),
        "strategy_decision_as_of": None,
        "state_as_of": None,
        "gold_head_held": _enum_value(getattr(receipt, "action", None)) == "hold",
        "authority_ready": False,
        "lineage_verified": False,
        "receipt_id": getattr(receipt, "receipt_id", None),
        "result_id": None,
        "feature_snapshot_id": None,
        "state_id": None,
        "transition_decision_hash": None,
        "strategy_id": None,
        "consistency_decision_id": None,
        "strategy_policy_version": None,
        "is_trade_instruction": False,
        "confidence": None,
        "market_regime": "unavailable",
        "source_refs": [],
        "artifact_refs": artifact_refs or [],
    }
    if head is not None:
        projection.update(
            strategy_status=_enum_value(head.strategy_decision.status),
            quality_status=_enum_value(head.analysis_state.quality_status),
            strategy_decision_as_of=_iso_datetime(head.strategy_decision.decision_as_of),
            state_as_of=_iso_datetime(head.analysis_state.as_of),
            result_id=head.loop_result.result_id,
            feature_snapshot_id=head.feature_snapshot.snapshot_id,
            state_id=head.analysis_state.state_id,
            transition_decision_hash=head.transition_decision.decision_hash,
            strategy_id=head.strategy_decision.decision_id,
            consistency_decision_id=head.consistency_decision.decision_id,
            strategy_policy_version=_enum_value(head.strategy_decision.policy_version),
            is_trade_instruction=head.strategy_decision.is_trade_instruction,
            confidence=head.analysis_state.confidence,
            market_regime=_state_market_regime(head.analysis_state),
            source_refs=_head_source_refs(head),
        )
    return projection


def _head_source_refs(head: DailyCloseCanonicalHead) -> list[dict[str, Any]]:
    refs = [
        {"name": "gold_daily_close_receipt", "source_ref": head.latest_receipt.receipt_id, "status": "held" if _enum_value(head.latest_receipt.action) == "hold" else "ok"},
        *(_model_dict(item) for item in head.analysis_state.source_refs),
        *(_model_dict(item) for item in head.strategy_decision.source_refs),
        *(_model_dict(item) for item in head.loop_result.source_refs),
    ]
    return _unique_dicts(refs)


def _head_artifact_refs(root: Path, head: DailyCloseCanonicalHead) -> list[str]:
    effective = head.latest_receipt.effective_head
    pointers = (
        effective.feature,
        effective.state,
        effective.transition,
        effective.strategy_policy_input,
        effective.strategy,
        effective.consistency,
        effective.result,
    ) if effective is not None else ()
    values = [
        _relative_path(root, head.latest_receipt_path),
        _relative_path(root, head.selected_bundle_path),
        *(pointer.path for pointer in pointers),
    ]
    return list(dict.fromkeys(value for value in values if value))


def _lookup_artifact_refs(root: Path, source_path: Path | None) -> list[str]:
    value = _relative_path(root, source_path)
    return [value] if value else []


def _relative_path(root: Path, value: Path | None) -> str | None:
    if value is None:
        return None
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _state_market_regime(state: Any) -> str:
    value = getattr(state, "market_regime", None) or getattr(state, "stage", None)
    return _enum_value(value)


def _model_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {"source_ref": str(value)}


def _unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for value in values:
        unique.setdefault(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), value)
    return list(unique.values())


def _prefixed_reason(reason_code: str) -> str:
    return reason_code if reason_code.startswith("gold_") else f"gold_{reason_code}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso_datetime(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value or "unavailable"))
