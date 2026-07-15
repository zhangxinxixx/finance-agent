"""Pure event-gated recompute evaluation for ``live_strategy.v1``.

This module only evaluates whether an already-built candidate strategy is
eligible to replace a previous read model.  It never builds a strategy,
executes a recompute, persists an artifact, or infers institutional intent.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from apps.analysis.strategy.strategy_diff import diff_live_strategy


RECOMPUTE_SCHEMA_VERSION = "live_strategy.recompute.v1"
LIVE_STRATEGY_SCHEMA_VERSION = "live_strategy.v1"
_VALID_RESPONSE_STATUSES = {"available", "partial"}


def evaluate_strategy_recompute(
    previous: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate a material-event candidate without executing it.

    A candidate is accepted only when the event overlay explicitly marks it as
    a recompute candidate, both read models have valid identity/version fields,
    canonical 5m data is available for both models, neither model is suspended
    for data, and at least one decision field (rather than the additive event
    overlay itself) changed.
    """

    if not isinstance(previous, Mapping) or not isinstance(candidate, Mapping):
        raise TypeError("previous and candidate must be mappings")

    diff = diff_live_strategy(previous, candidate)
    decision_changes = [
        change
        for change in diff["changes"]
        if not str(change.get("path", "")).startswith("event_overlay")
    ]
    decision_diff = _decision_diff(diff, decision_changes)

    reason_codes: list[str] = []
    reason_codes.extend(_identity_reasons(previous, "previous"))
    reason_codes.extend(_identity_reasons(candidate, "candidate"))
    reason_codes.extend(_canonical_reasons(previous, "previous"))
    reason_codes.extend(_canonical_reasons(candidate, "candidate"))

    overlay = candidate.get("event_overlay")
    if not isinstance(overlay, Mapping):
        reason_codes.append("candidate_event_overlay_required")
    elif overlay.get("recompute_candidate") is not True:
        reason_codes.append("event_recompute_candidate_required")

    if not decision_changes:
        reason_codes.append("decision_diff_unchanged")

    reason_codes = list(dict.fromkeys(reason_codes))
    accepted = not reason_codes
    if accepted:
        reason_codes = ["accepted:material_event_decision_changed"]

    output_without_id = {
        "schema_version": RECOMPUTE_SCHEMA_VERSION,
        "accepted": accepted,
        "reason_codes": reason_codes,
        "from_strategy_id": _text_or_none(previous.get("strategy_id")),
        "to_strategy_id": _text_or_none(candidate.get("strategy_id")),
        "from_strategy_version": _text_or_none(previous.get("strategy_version")),
        "to_strategy_version": _text_or_none(candidate.get("strategy_version")),
        "event_evidence": _event_evidence(overlay),
        "event_overlay_ref": _event_overlay_ref(overlay),
        "diff": deepcopy(diff),
        "decision_diff": decision_diff,
        "decision_changed": bool(decision_changes),
    }
    canonical = _canonical_json(output_without_id)
    return {
        **output_without_id,
        "recompute_id": f"recompute-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
    }


def _identity_reasons(model: Mapping[str, Any], role: str) -> list[str]:
    reasons: list[str] = []
    if model.get("schema_version") != LIVE_STRATEGY_SCHEMA_VERSION:
        reasons.append(f"{role}_schema_version_required")
    if not _valid_text(model.get("strategy_id")):
        reasons.append(f"{role}_strategy_id_required")
    if not _valid_text(model.get("strategy_version")):
        reasons.append(f"{role}_strategy_version_required")
    return reasons


def _canonical_reasons(model: Mapping[str, Any], role: str) -> list[str]:
    reasons: list[str] = []
    response_status = model.get("status")
    if response_status == "unavailable" or response_status not in _VALID_RESPONSE_STATUSES:
        reasons.append(f"{role}_status_unavailable")
    if model.get("strategy_status") == "SUSPENDED_DATA":
        reasons.append(f"{role}_strategy_suspended_data")

    market = model.get("live_market")
    market_status = market.get("status") if isinstance(market, Mapping) else None
    if market_status != "available":
        reasons.append(f"{role}_canonical_market_unavailable")

    quality = model.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, Mapping) else None
    canonical_status = canonical.get("status") if isinstance(canonical, Mapping) else None
    if canonical_status != "available":
        reasons.append(f"{role}_canonical_data_unavailable")
    return reasons


def _decision_diff(diff: Mapping[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "schema_version": diff.get("schema_version"),
        "from_strategy_id": diff.get("from_strategy_id"),
        "to_strategy_id": diff.get("to_strategy_id"),
        "from_strategy_version": diff.get("from_strategy_version"),
        "to_strategy_version": diff.get("to_strategy_version"),
        "changed": bool(changes),
        "changes": deepcopy(changes),
    }
    payload["diff_id"] = f"diff-{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"
    return payload


def _event_evidence(overlay: Any) -> list[dict[str, Any]]:
    if not isinstance(overlay, Mapping):
        return []
    return [deepcopy(dict(item)) for item in overlay.get("evidence", []) or [] if isinstance(item, Mapping)]


def _event_overlay_ref(overlay: Any) -> dict[str, Any] | None:
    if not isinstance(overlay, Mapping):
        return None
    return {
        "schema_version": overlay.get("schema_version"),
        "event_id": overlay.get("event_id"),
        "event_type": overlay.get("event_type"),
        "observed_at": overlay.get("observed_at"),
        "status": overlay.get("status"),
        "source_refs": [
            deepcopy(dict(item))
            for item in overlay.get("source_refs", []) or []
            if isinstance(item, Mapping)
        ],
    }


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = ["RECOMPUTE_SCHEMA_VERSION", "evaluate_strategy_recompute"]
