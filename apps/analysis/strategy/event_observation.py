"""Pure adapter from Event Flow read models to a live-strategy observation."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping


SCHEMA_VERSION = "live_strategy.event_observation.v1"
_MATERIALITY_FIELDS = (
    "source_reliability",
    "event_importance",
    "surprise",
    "gold_relevance",
    "market_reaction_strength",
    "reaction_persistence",
    "official_source",
    "independent_source_count",
)
_REACTION_FIELDS = (
    "status",
    "updated_at",
    "baseline_time",
    "pricing_status",
    "direction",
    "window",
    "strength",
    "persistence",
    "market_reaction_strength",
    "reaction_persistence",
    "market_validation",
    "market_snapshot",
    "windows",
    "confirmation_summary",
)
_LINEAGE_FIELDS = {
    "source_ref",
    "source_refs",
    "source",
    "source_id",
    "url",
    "raw_path",
    "parsed_path",
    "artifact_path",
    "file_path",
}


def build_event_observation(
    event_detail: Mapping[str, Any] | None,
    market_reaction: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt already-built read models without selecting events or doing I/O.

    A market reaction is accepted only when the supplied read model contains an
    observed market snapshot or non-empty reaction windows.  Event prose,
    validation labels, and expected impact are never promoted into a reaction.
    """

    if not isinstance(event_detail, Mapping) or not event_detail:
        return _result(
            status="unavailable",
            event_id=None,
            event_type=None,
            observed_at=None,
            observed_reaction=None,
            materiality_inputs={},
            evidence=[],
            source_refs=[],
            reasons=["event_detail_unavailable"],
        )

    detail = deepcopy(dict(event_detail))
    event_value = detail.get("event")
    event = deepcopy(dict(event_value)) if isinstance(event_value, Mapping) else detail
    reaction_value = deepcopy(dict(market_reaction)) if isinstance(market_reaction, Mapping) else None

    event_id = _text(event.get("event_id") or event.get("id"))
    event_type = _text(event.get("event_type") or event.get("type") or event.get("kind"))
    observed_at = _text(
        event.get("observed_at")
        or event.get("occurred_at")
        or event.get("event_time")
        or event.get("time")
        or detail.get("observed_at")
    )

    observed_reaction = _observed_reaction(reaction_value)
    evidence = _dedupe_sourced_mappings(
        _mapping_items(detail.get("evidence"))
        + _mapping_items(event.get("evidence"))
        + _mapping_items(reaction_value.get("evidence") if reaction_value else None)
    )
    source_refs = _dedupe_sourced_mappings(
        _mapping_items(detail.get("source_refs"))
        + _mapping_items(event.get("source_refs"))
        + _mapping_items(reaction_value.get("source_refs") if reaction_value else None)
    )
    materiality_inputs = _materiality_inputs(detail, event, reaction_value)

    reasons: list[str] = []
    if not event_id or not event_type:
        reasons.append("event_identity_required")
    if not observed_at:
        reasons.append("observed_at_required")
    if observed_reaction is None:
        reasons.append("observed_market_reaction_required")

    return _result(
        status="blocked" if reasons else "available",
        event_id=event_id,
        event_type=event_type,
        observed_at=observed_at,
        observed_reaction=observed_reaction,
        materiality_inputs=materiality_inputs,
        evidence=evidence,
        source_refs=source_refs,
        reasons=reasons or ["available:observed_event_with_market_reaction"],
    )


def _observed_reaction(reaction: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not reaction or _text(reaction.get("status")) == "unavailable":
        return None

    validation = reaction.get("market_validation")
    validation_mapping = validation if isinstance(validation, Mapping) else {}
    snapshot = reaction.get("market_snapshot")
    if snapshot is None:
        snapshot = validation_mapping.get("market_snapshot")
    windows = reaction.get("windows")
    has_observation = _snapshot_has_observation(snapshot) or (
        isinstance(windows, Mapping)
        and any(isinstance(value, Mapping) and bool(value) for value in windows.values())
    )
    if not has_observation:
        return None

    result = {
        field: deepcopy(reaction[field])
        for field in _REACTION_FIELDS
        if field in reaction and reaction[field] is not None
    }
    if "market_snapshot" not in result and snapshot is not None:
        result["market_snapshot"] = deepcopy(snapshot)
    result["observed"] = True
    return result


def _snapshot_has_observation(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    if "observed_assets" in value:
        observed_assets = value.get("observed_assets")
        return isinstance(observed_assets, list) and bool(observed_assets)
    assets = value.get("assets")
    if isinstance(assets, list):
        return any(
            isinstance(item, Mapping) and _text(item.get("status")) == "observed"
            for item in assets
        )
    return any(isinstance(item, Mapping) and bool(item) for item in value.values())


def _materiality_inputs(
    detail: Mapping[str, Any],
    event: Mapping[str, Any],
    reaction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    nested_sources = [
        detail.get("materiality_inputs"),
        event.get("materiality_inputs"),
    ]
    sources = [value for value in nested_sources if isinstance(value, Mapping)]
    sources.extend([event, detail])
    if reaction is not None:
        sources.append(reaction)

    result: dict[str, Any] = {}
    for field in _MATERIALITY_FIELDS:
        for source in sources:
            if field in source and source[field] is not None:
                result[field] = deepcopy(source[field])
                break
    return result


def _result(
    *,
    status: str,
    event_id: str | None,
    event_type: str | None,
    observed_at: str | None,
    observed_reaction: dict[str, Any] | None,
    materiality_inputs: dict[str, Any],
    evidence: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    reasons: list[str],
) -> dict[str, Any]:
    identity_payload = {
        "event_id": event_id,
        "event_type": event_type,
        "observed_at": observed_at,
        "observed_reaction": observed_reaction,
    }
    digest = sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()[:20]
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": f"event-observation-{digest}",
        "status": status,
        "event_id": event_id,
        "event_type": event_type,
        "observed_at": observed_at,
        "observed_reaction": observed_reaction,
        "materiality_inputs": materiality_inputs,
        "evidence": evidence,
        "source_refs": source_refs,
        "reasons": reasons,
    }


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    return [deepcopy(dict(item)) for item in value or [] if isinstance(item, Mapping)]


def _dedupe_sourced_mappings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not any(item.get(field) not in (None, "", [], {}) for field in _LINEAGE_FIELDS):
            continue
        fingerprint = _canonical_json(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(item)
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
