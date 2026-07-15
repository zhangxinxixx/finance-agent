from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_COMPARABLE_FIELDS = (
    "underlying",
    "event_type",
    "predicate",
    "target_value",
    "target_unit",
    "probability_semantics",
    "horizon_start",
    "horizon_end",
)


def compare_market_odds(
    *,
    external: dict[str, Any],
    internal: dict[str, Any],
    conflict_gap: float = 0.15,
    max_observation_gap_hours: float = 24.0,
) -> dict[str, Any]:
    """Compare identical event definitions without aggregating probabilities."""
    external_view = _normalized(external, external=True)
    internal_view = _normalized(internal, external=False)
    mismatches = [field for field in _COMPARABLE_FIELDS if external_view.get(field) != internal_view.get(field)]
    base = {
        "comparison_status": "not_comparable",
        "reason_codes": [f"different_{field}" for field in mismatches],
        "external_probability": external_view.get("probability"),
        "internal_probability": internal_view.get("probability"),
        "probability_gap": None,
        "aggregation_allowed": False,
        "external_evidence_refs": external.get("evidence_refs") or external.get("source_refs") or [],
        "internal_evidence_refs": internal.get("evidence_refs") or internal.get("source_refs") or [],
    }
    if external.get("analysis_eligible") is False:
        base["reason_codes"] = [
            "external_not_analysis_eligible",
            *[str(item) for item in external.get("analysis_block_reasons") or []],
        ]
        return base
    if mismatches:
        return base
    external_observed_at = _timestamp(external_view.get("observed_at"))
    internal_observed_at = _timestamp(internal_view.get("observed_at"))
    if external_observed_at is None or internal_observed_at is None:
        base["reason_codes"] = ["observation_time_missing_or_invalid"]
        return base
    observation_gap_hours = abs((external_observed_at - internal_observed_at).total_seconds()) / 3600
    if observation_gap_hours > max_observation_gap_hours:
        base["reason_codes"] = ["observation_time_not_close"]
        base["observation_gap_hours"] = round(observation_gap_hours, 4)
        return base
    external_probability = _probability(external_view.get("probability"))
    internal_probability = _probability(internal_view.get("probability"))
    if external_probability is None or internal_probability is None:
        base["reason_codes"] = ["probability_missing_or_invalid"]
        return base
    gap = round(external_probability - internal_probability, 10)
    base.update(
        comparison_status="conflicts" if abs(gap) > conflict_gap else "supports",
        reason_codes=[
            *[f"same_{field}" for field in _COMPARABLE_FIELDS],
            "observation_time_within_limit",
        ],
        external_probability=external_probability,
        internal_probability=internal_probability,
        probability_gap=gap,
        observation_gap_hours=round(observation_gap_hours, 4),
    )
    return base


def _normalized(item: dict[str, Any], *, external: bool) -> dict[str, Any]:
    value = dict(item)
    value["underlying"] = value.get("underlying") or value.get("asset")
    if external:
        value["odds_kind"] = "external_report_odds"
    else:
        value["odds_kind"] = "market_derived_odds"
    return value


def _probability(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 1 else None


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
