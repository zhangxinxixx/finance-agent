"""Pure orchestration for event-gated live-strategy recompute.

The adapter composes the existing recompute evaluator with the bounded
institutional-intent hypothesis builder.  It intentionally has no side
effects: callers still own persistence, scheduling, and execution.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from apps.analysis.strategy.institutional_intent import (
    SCHEMA_VERSION as INSTITUTIONAL_INTENT_SCHEMA_VERSION,
    build_institutional_intent_hypotheses,
)
from apps.analysis.strategy.recompute import evaluate_strategy_recompute


RECOMPUTE_EXECUTION_SCHEMA_VERSION = "live_strategy.recompute_execution.v1"


def execute_strategy_recompute(
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    options_decision: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate and package a recompute without executing or persisting it.

    ``evaluate_strategy_recompute`` remains the sole gate.  Institutional
    intent is generated only for an accepted recompute; a blocked result
    carries an explicit unavailable, empty intent object rather than a
    speculative hypothesis.
    """

    _require_mapping(previous, "previous")
    _require_mapping(candidate, "candidate")
    _require_optional_mapping(options_decision, "options_decision")
    _require_optional_mapping(evidence, "evidence")

    recompute = evaluate_strategy_recompute(previous, candidate)
    accepted = bool(recompute.get("accepted"))
    if accepted:
        institutional_intent = build_institutional_intent_hypotheses(
            deepcopy(candidate),
            deepcopy(options_decision) if options_decision is not None else None,
            deepcopy(evidence) if evidence is not None else None,
        )
    else:
        institutional_intent = _unavailable_intent()

    output_without_id: dict[str, Any] = {
        "schema_version": RECOMPUTE_EXECUTION_SCHEMA_VERSION,
        "status": "accepted" if accepted else "blocked",
        "recompute": deepcopy(recompute),
        "institutional_intent": deepcopy(institutional_intent),
        "from_ref": _strategy_ref(previous),
        "to_ref": _strategy_ref(candidate),
    }
    return {
        **output_without_id,
        "execution_id": f"execution-{_digest(output_without_id)}",
    }


def _strategy_ref(strategy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": strategy.get("strategy_id") if isinstance(strategy.get("strategy_id"), str) else None,
        "strategy_version": strategy.get("strategy_version")
        if isinstance(strategy.get("strategy_version"), str)
        else None,
    }


def _unavailable_intent() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": INSTITUTIONAL_INTENT_SCHEMA_VERSION,
        "status": "unavailable",
        "hypotheses": [],
        "evidence_refs": [],
        "counter_evidence": [],
        "reasons": ["recompute_blocked"],
    }
    payload["intent_id"] = f"intent-{_digest(payload)}"
    return payload


def _require_mapping(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")


def _require_optional_mapping(value: Any, name: str) -> None:
    if value is not None and not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping or None")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["RECOMPUTE_EXECUTION_SCHEMA_VERSION", "execute_strategy_recompute"]
