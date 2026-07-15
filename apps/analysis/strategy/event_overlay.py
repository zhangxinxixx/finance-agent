"""Optional, read-only Event Materiality overlay for ``live_strategy.v1``.

The overlay deliberately does not own live-strategy state transitions.  It is
an adapter around the pure Event Materiality scorer and exposes whether a
material event is a *candidate* for a future recomputation.  A candidate is
never a recomputation, a strategy version, or an execution instruction.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from apps.analysis.strategy.event_materiality import COMPONENT_WEIGHTS, score_event_materiality


OVERLAY_SCHEMA_VERSION = "live_strategy.event_overlay.v1"
_SCORER_FIELDS = {
    *COMPONENT_WEIGHTS,
    "official_source",
    "independent_source_count",
    "evidence",
    "source_refs",
}


def build_event_overlay(event: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build an additive overlay from one optional event observation.

    ``event`` may contain either raw scorer inputs (at the top level or under
    ``materiality_inputs``/``materiality``) or an already-scored materiality
    result.  The latter is copied so callers cannot mutate the accepted
    evidence lineage through the live response.
    """

    if not isinstance(event, Mapping) or not event:
        return _unavailable()

    payload = deepcopy(dict(event))
    event_id = _text(payload.get("event_id") or payload.get("id"))
    event_type = _text(payload.get("event_type") or payload.get("type"))
    reaction = payload.get("observed_reaction")
    reaction_observed_at = reaction.get("observed_at") if isinstance(reaction, Mapping) else None
    observed_at = _text(payload.get("observed_at") or payload.get("occurred_at") or reaction_observed_at)
    identity_valid = bool(event_id and event_type and observed_at)

    reaction_valid = _reaction_is_observed(reaction)
    materiality_source = payload.get("materiality")
    if not isinstance(materiality_source, Mapping):
        materiality_source = payload.get("materiality_inputs")
    if not isinstance(materiality_source, Mapping):
        materiality_source = payload

    if _is_scored_materiality(materiality_source):
        materiality = deepcopy(dict(materiality_source))
    else:
        scorer_inputs = _scorer_inputs(payload, materiality_source, reaction)
        materiality = score_event_materiality(**scorer_inputs)

    evidence = _copy_list(materiality.get("evidence"))
    source_refs = _copy_list(materiality.get("source_refs"))
    reasons: list[str] = []
    if not identity_valid:
        reasons.append("event_identity_required")
    if not reaction_valid:
        reasons.append("observed_reaction_required")
    if materiality.get("recompute_eligible") is not True:
        reasons.extend(_gate_reasons(materiality))

    recompute_candidate = bool(
        identity_valid
        and reaction_valid
        and materiality.get("recompute_eligible") is True
    )
    if recompute_candidate:
        status = "eligible"
        reasons = ["eligible:recompute_candidate"]
        candidate_reason = "eligible_material_event_with_observed_reaction"
    elif not identity_valid or not reaction_valid:
        status = "blocked"
        candidate_reason = "event_identity_or_observed_reaction_missing"
    else:
        status = "observed"
        candidate_reason = "materiality_gate_blocked"

    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "status": status,
        "event_id": event_id,
        "event_type": event_type,
        "observed_at": observed_at,
        "materiality": materiality,
        "evidence": evidence,
        "source_refs": source_refs,
        "recompute_candidate": recompute_candidate,
        "recompute_candidate_reason": candidate_reason,
        "reasons": list(dict.fromkeys(reasons)),
    }


def _unavailable() -> dict[str, Any]:
    return {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "status": "unavailable",
        "event_id": None,
        "event_type": None,
        "observed_at": None,
        "materiality": None,
        "evidence": [],
        "source_refs": [],
        "recompute_candidate": False,
        "recompute_candidate_reason": "event_observation_unavailable",
        "reasons": ["event_observation_unavailable"],
    }


def _scorer_inputs(
    event: Mapping[str, Any],
    materiality_source: Mapping[str, Any],
    reaction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for field in _SCORER_FIELDS:
        if field in {"evidence", "source_refs"}:
            continue
        value = materiality_source.get(field)
        if value is None:
            value = event.get(field)
        if value is None and isinstance(reaction, Mapping):
            value = reaction.get(field)
            if value is None and field == "market_reaction_strength":
                value = reaction.get("strength")
            if value is None and field == "reaction_persistence":
                value = reaction.get("persistence")
        inputs[field] = value
    inputs["evidence"] = _copy_list(materiality_source.get("evidence") or event.get("evidence"))
    inputs["source_refs"] = _copy_list(materiality_source.get("source_refs") or event.get("source_refs"))
    return inputs


def _is_scored_materiality(value: Mapping[str, Any]) -> bool:
    return "score" in value and "recompute_eligible" in value and "components" in value


def _gate_reasons(materiality: Mapping[str, Any]) -> list[str]:
    gate = materiality.get("eligibility_gate")
    failures = gate.get("failures") if isinstance(gate, Mapping) else None
    return [str(item) for item in failures or []]


def _reaction_is_observed(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    meaningful_fields = {
        "market_reaction_strength",
        "reaction_persistence",
        "strength",
        "persistence",
        "direction",
        "window",
        "observed",
    }
    return bool(set(value).intersection(meaningful_fields))


def _copy_list(value: Any) -> list[dict[str, Any]]:
    return [deepcopy(dict(item)) for item in value or [] if isinstance(item, Mapping)]


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
