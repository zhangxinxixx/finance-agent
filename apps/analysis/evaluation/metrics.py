"""Pure aggregation for shadow strategy outcome evaluations."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Any

from .outcomes import HORIZONS, OutcomeEvaluation

_CLASSIFICATIONS = ("correct", "incorrect", "neutral", "hold", "invalidated", "blocked", "unscorable")
_STATUSES = ("scored", "blocked", "unscorable")


def aggregate_outcome_metrics(
    outcomes: Iterable[OutcomeEvaluation | Mapping[str, Any]],
    *,
    horizon: str | None = None,
) -> dict[str, Any]:
    """Aggregate shadow outcomes without treating missing results as failures.

    Only ``scored`` outcomes whose ``direction_accuracy`` is ``correct`` or
    ``incorrect`` enter the accuracy denominator.  Blocked and unscorable
    outcomes remain visible in counts but never become synthetic failures.
    Duplicate ``(evaluation_id, horizon)`` records are ignored when their
    canonical payload is identical; conflicting duplicates fail loudly.
    """

    if horizon is not None and horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon: {horizon}")

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for outcome in outcomes:
        payload = _payload(outcome)
        item_horizon = _required_text(payload, "horizon")
        if item_horizon not in HORIZONS:
            raise ValueError(f"unsupported horizon: {item_horizon}")
        if horizon is not None and item_horizon != horizon:
            continue
        evaluation_id = _required_text(payload, "evaluation_id")
        key = (evaluation_id, item_horizon)
        canonical = _canonical_json(payload)
        previous = unique.get(key)
        if previous is not None:
            if _canonical_json(previous) != canonical:
                raise ValueError(f"conflicting duplicate outcome: {evaluation_id}/{item_horizon}")
            continue
        unique[key] = payload

    grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in HORIZONS}
    for payload in unique.values():
        grouped[payload["horizon"]].append(payload)

    selected = [payload for values in grouped.values() for payload in values]
    result = _summarize(selected)
    result["schema_version"] = "shadow_evaluation_metrics.v1"
    result["by_horizon"] = {key: _summarize(grouped[key]) for key in HORIZONS if grouped[key]}
    if horizon is not None:
        result["horizon"] = horizon
    return result


def _payload(outcome: OutcomeEvaluation | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(outcome, OutcomeEvaluation):
        return outcome.to_dict()
    if isinstance(outcome, Mapping):
        return dict(outcome)
    raise TypeError("outcomes must contain OutcomeEvaluation or mapping values")


def _summarize(values: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(_required_text(item, "status") for item in values)
    classification_counts = Counter(_required_text(item, "classification") for item in values)
    unknown_statuses = set(status_counts) - set(_STATUSES)
    if unknown_statuses:
        raise ValueError(f"unsupported outcome status: {sorted(unknown_statuses)!r}")
    unknown_classes = set(classification_counts) - set(_CLASSIFICATIONS)
    if unknown_classes:
        raise ValueError(f"unsupported outcome classification: {sorted(unknown_classes)!r}")

    directional = [
        item
        for item in values
        if item.get("status") == "scored"
        and item.get("direction_accuracy") in {"correct", "incorrect"}
    ]
    scored_values = [item for item in values if item.get("status") == "scored"]
    mfe_values = [_number(item.get("mfe")) for item in scored_values]
    mae_values = [_number(item.get("mae")) for item in scored_values]
    mfe_values = [value for value in mfe_values if value is not None]
    mae_values = [value for value in mae_values if value is not None]
    return {
        "total_count": len(values),
        "approved_count": status_counts.get("scored", 0),
        "scored_count": status_counts.get("scored", 0),
        "blocked_count": status_counts.get("blocked", 0),
        "unscorable_count": status_counts.get("unscorable", 0),
        "directional_count": len(directional),
        "correct_count": sum(item.get("direction_accuracy") == "correct" for item in directional),
        "incorrect_count": sum(item.get("direction_accuracy") == "incorrect" for item in directional),
        "accuracy": (sum(item.get("direction_accuracy") == "correct" for item in directional) / len(directional))
        if directional
        else None,
        "mfe_avg": sum(mfe_values) / len(mfe_values) if mfe_values else None,
        "mae_avg": sum(mae_values) / len(mae_values) if mae_values else None,
        "classification_counts": {key: classification_counts.get(key, 0) for key in _CLASSIFICATIONS},
    }


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"outcome {key} is required")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    return float(value)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


__all__ = ["aggregate_outcome_metrics"]
