"""Pure deterministic Event Materiality scoring for Issue 63-C.

Inputs use a ``0.0`` to ``1.0`` scale. Out-of-range finite values are
explicitly clamped; missing or non-finite values remain missing and contribute
zero. The score is never re-normalized over the available components, so absent
evidence cannot silently inflate materiality.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


RULESET = "event_materiality.rules.v1"
COMPONENT_WEIGHTS: dict[str, float] = {
    "source_reliability": 0.20,
    "event_importance": 0.20,
    "surprise": 0.15,
    "gold_relevance": 0.20,
    "market_reaction_strength": 0.15,
    "reaction_persistence": 0.10,
}
BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (80.0, "critical"),
    (65.0, "high"),
    (40.0, "medium"),
    (0.0, "low"),
)
ELIGIBILITY_THRESHOLDS: dict[str, float] = {
    "score": 70.0,
    "source_reliability": 0.80,
    "event_importance": 0.65,
    "surprise": 0.65,
    "gold_relevance": 0.65,
    "market_reaction_strength": 0.65,
    "reaction_persistence": 0.60,
}
MIN_INDEPENDENT_SOURCES = 2


def score_event_materiality(
    *,
    source_reliability: float | None = None,
    event_importance: float | None = None,
    surprise: float | None = None,
    gold_relevance: float | None = None,
    market_reaction_strength: float | None = None,
    reaction_persistence: float | None = None,
    official_source: bool | None = None,
    independent_source_count: int | None = None,
    evidence: list[Mapping[str, Any]] | None = None,
    source_refs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score one immutable event observation without I/O or clock access.

    ``recompute_eligible`` is intentionally stricter than the numeric score. A
    high score cannot authorize recomputation unless every component is known,
    the event is official and independently confirmed, and both market reaction
    strength and persistence clear their frozen gates.
    """
    inputs = {
        "source_reliability": source_reliability,
        "event_importance": event_importance,
        "surprise": surprise,
        "gold_relevance": gold_relevance,
        "market_reaction_strength": market_reaction_strength,
        "reaction_persistence": reaction_persistence,
    }
    components: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    missing_components: list[str] = []
    total = 0.0

    for name, weight in COMPONENT_WEIGHTS.items():
        raw = inputs[name]
        normalized = _finite_number(raw)
        if normalized is None:
            missing_components.append(name)
            status = "missing"
            contribution = 0.0
            reasons.append(f"missing_component:{name}")
        else:
            clamped = min(max(normalized, 0.0), 1.0)
            status = "clamped" if clamped != normalized else "observed"
            normalized = clamped
            contribution = round(normalized * weight * 100.0, 4)
            total += contribution
            if status == "clamped":
                reasons.append(f"component_clamped:{name}")
        components[name] = {
            "raw": raw,
            "value": normalized,
            "range": [0.0, 1.0],
            "weight": weight,
            "contribution": contribution,
            "status": status,
        }

    score = round(min(max(total, 0.0), 100.0), 2)
    band = "insufficient" if missing_components else _score_band(score)
    normalized_evidence = _copy_mappings(evidence)
    normalized_source_refs = _copy_mappings(source_refs)
    normalized_source_count = _non_negative_int(independent_source_count)

    gate_failures = _eligibility_failures(
        score=score,
        components=components,
        official_source=official_source,
        independent_source_count=normalized_source_count,
        evidence=normalized_evidence,
        source_refs=normalized_source_refs,
    )
    reasons.extend(gate_failures)
    recompute_eligible = not gate_failures
    if recompute_eligible:
        reasons.append("eligible:confirmed_material_event")

    return {
        "ruleset": RULESET,
        "score": score,
        "band": band,
        "components": components,
        "reasons": reasons,
        "evidence": normalized_evidence,
        "source_refs": normalized_source_refs,
        "recompute_eligible": recompute_eligible,
        "coverage": {
            "observed_components": len(COMPONENT_WEIGHTS) - len(missing_components),
            "required_components": len(COMPONENT_WEIGHTS),
            "missing_components": missing_components,
        },
        "confirmation": {
            "official_source": official_source is True,
            "independent_source_count": normalized_source_count,
            "minimum_independent_sources": MIN_INDEPENDENT_SOURCES,
        },
        "eligibility_gate": {
            "passed": recompute_eligible,
            "failures": gate_failures,
            "thresholds": dict(ELIGIBILITY_THRESHOLDS),
        },
    }


def _eligibility_failures(
    *,
    score: float,
    components: Mapping[str, Mapping[str, Any]],
    official_source: bool | None,
    independent_source_count: int | None,
    evidence: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if official_source is not True:
        failures.append("gate_failed:official_source_required")
    if independent_source_count is None or independent_source_count < MIN_INDEPENDENT_SOURCES:
        failures.append("gate_failed:multi_source_confirmation_required")
    if _unique_mapping_count(source_refs) < MIN_INDEPENDENT_SOURCES:
        failures.append("gate_failed:multi_source_lineage_required")
    if not evidence:
        failures.append("gate_failed:evidence_required")
    if score < ELIGIBILITY_THRESHOLDS["score"]:
        failures.append("gate_failed:score_below_threshold")
    for name in COMPONENT_WEIGHTS:
        value = components[name].get("value")
        threshold = ELIGIBILITY_THRESHOLDS[name]
        if value is None:
            failures.append(f"gate_failed:{name}_required")
        elif float(value) < threshold:
            failures.append(f"gate_failed:{name}_below_threshold")
    return failures


def _score_band(score: float) -> str:
    return next(band for threshold, band in BAND_THRESHOLDS if score >= threshold)


def _finite_number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _copy_mappings(items: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(item) for item in items or [] if isinstance(item, Mapping)]


def _unique_mapping_count(items: list[dict[str, Any]]) -> int:
    unique: list[dict[str, Any]] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return len(unique)
