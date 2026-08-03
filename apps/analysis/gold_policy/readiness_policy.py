"""Pure multi-domain readiness policy for ``feature_snapshot.v2``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.analysis.gold_policy.schemas import (
    AnalysisReadiness,
    FeatureSnapshotV2Input,
    OfficialEventSnapshot,
    ReadinessProhibitedOutput,
    SourceReference,
    VariableObservation,
)


_REQUIRED_CORE = (
    ("XAUUSD", "xauusd_spot"),
    ("US10Y", "us10y"),
    ("T10YIE", "t10yie"),
    ("REAL10Y_ESTIMATED", "real10y_estimated"),
    ("BROAD_DOLLAR", "broad_dollar"),
)
_CONFIRMATORY = (
    ("US02Y", "us02y"),
    ("US30Y", "us30y"),
    ("GC", "gc_futures"),
    ("WTI", "wti"),
    ("BRENT", "brent"),
    ("ETF", "etf_flow"),
    ("COT", "cot"),
)


class GoldReadinessDecision(BaseModel):
    """Immutable result; tuple ordering is part of the deterministic contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["gold_readiness_policy.v1"] = "gold_readiness_policy.v1"
    analysis_readiness: AnalysisReadiness
    strategy_readiness: AnalysisReadiness
    options_readiness: AnalysisReadiness
    event_attribution_readiness: AnalysisReadiness
    missing_required_inputs: tuple[str, ...]
    missing_confirmatory_inputs: tuple[str, ...]
    prohibited_outputs: tuple[ReadinessProhibitedOutput, ...]
    reason_codes: tuple[str, ...]


def evaluate_gold_readiness(
    snapshot: FeatureSnapshotV2Input,
    *,
    real10y_estimated: VariableObservation,
) -> GoldReadinessDecision:
    """Evaluate readiness without I/O, clocks, prose, or authority fallbacks."""

    missing_required: list[str] = []
    missing_confirmatory: list[str] = []
    reasons: list[str] = []
    required_degraded = False
    confirmatory_degraded = False

    for label, field_name in _REQUIRED_CORE:
        observation = (
            real10y_estimated
            if field_name == "real10y_estimated"
            else getattr(snapshot, field_name)
        )
        status = _observation_status(observation, snapshot.as_of)
        if status == "unusable":
            missing_required.append(label)
            reasons.append(f"REQUIRED_INPUT_UNUSABLE:{label}")
        elif status == "degraded":
            required_degraded = True
            reasons.append(f"REQUIRED_INPUT_DEGRADED:{label}")

    for label, field_name in _CONFIRMATORY:
        status = _observation_status(getattr(snapshot, field_name), snapshot.as_of)
        if status == "unusable":
            missing_confirmatory.append(label)
            reasons.append(f"CONFIRMATORY_INPUT_UNUSABLE:{label}")
        elif status == "degraded":
            confirmatory_degraded = True
            reasons.append(f"CONFIRMATORY_INPUT_DEGRADED:{label}")

    if missing_required:
        analysis: AnalysisReadiness = "blocked"
    elif required_degraded or missing_confirmatory or confirmatory_degraded:
        analysis = "observe"
    else:
        analysis = "ready"

    options_status = _observation_status(snapshot.cme_options_regime, snapshot.as_of)
    if options_status == "unusable":
        options: AnalysisReadiness = "blocked"
        reasons.append("OPTIONS_INPUT_UNUSABLE")
    elif options_status == "degraded":
        options = "observe"
        reasons.append("OPTIONS_INPUT_DEGRADED")
    else:
        options = "ready"

    event, event_reasons = _event_readiness(snapshot.official_events, snapshot.as_of)
    reasons.extend(event_reasons)

    if analysis == "blocked":
        strategy: AnalysisReadiness = "blocked"
    elif analysis == "observe" or options != "ready":
        strategy = "observe"
    else:
        strategy = "ready"

    prohibited: list[ReadinessProhibitedOutput] = []
    if analysis == "blocked":
        prohibited.extend(("DIRECTIONAL_ANALYSIS", "DIRECTIONAL_STRATEGY"))
    if options != "ready":
        prohibited.append("OPTIONS_CONFIRMATION")
    if strategy != "ready":
        prohibited.append("TRIGGERED_STRATEGY")
    if event != "ready":
        prohibited.append("CONFIRMED_EVENT_ATTRIBUTION")

    return GoldReadinessDecision(
        analysis_readiness=analysis,
        strategy_readiness=strategy,
        options_readiness=options,
        event_attribution_readiness=event,
        missing_required_inputs=tuple(missing_required),
        missing_confirmatory_inputs=tuple(missing_confirmatory),
        prohibited_outputs=tuple(prohibited),
        reason_codes=tuple(reasons),
    )


def _observation_status(
    observation: VariableObservation,
    cutoff: datetime,
) -> Literal["ready", "degraded", "unusable"]:
    if (
        observation.value is None
        or observation.freshness_status == "missing"
        or observation.quality_status == "blocked"
        or observation.alignment_status == "misaligned"
        or not _at_or_before(observation.as_of, cutoff)
        or not _valid_refs(observation.source_refs, cutoff)
    ):
        return "unusable"
    if (
        observation.freshness_status == "stale"
        or observation.quality_status == "observe"
        or observation.alignment_status == "unknown"
    ):
        return "degraded"
    return "ready"


def _event_readiness(
    events: OfficialEventSnapshot,
    cutoff: datetime,
) -> tuple[AnalysisReadiness, tuple[str, ...]]:
    if (
        events.freshness_status == "missing"
        or events.quality_status == "blocked"
        or events.alignment_status == "misaligned"
        or not _at_or_before(events.as_of, cutoff)
        or not _valid_refs(events.source_refs, cutoff)
        or any(
            not _at_or_before(event.occurred_at, cutoff)
            or (
                event.reaction_window_end is not None
                and (
                    not _at_or_before(event.reaction_window_end, cutoff)
                    or event.reaction_window_end < event.occurred_at
                )
            )
            or not _valid_refs(event.source_refs, cutoff)
            or not _valid_refs(event.reaction_source_refs, cutoff, allow_empty=True)
            for event in events.events
        )
    ):
        return "blocked", ("OFFICIAL_EVENT_SNAPSHOT_UNUSABLE",)
    if (
        events.freshness_status == "stale"
        or events.quality_status == "observe"
        or events.alignment_status == "unknown"
    ):
        return "observe", ("OFFICIAL_EVENT_SNAPSHOT_DEGRADED",)
    if not events.events:
        return "ready", ("NO_MATERIAL_OFFICIAL_EVENT",)
    if any(event.reaction_status != "confirmed" for event in events.events):
        return "observe", ("OFFICIAL_EVENT_REACTION_UNCONFIRMED",)
    return "ready", ("OFFICIAL_EVENT_REACTION_CONFIRMED",)


def _valid_refs(
    refs: tuple[SourceReference, ...],
    cutoff: datetime,
    *,
    allow_empty: bool = False,
) -> bool:
    if not refs:
        return allow_empty
    return all(_at_or_before(ref.retrieved_at, cutoff) for ref in refs)


def _at_or_before(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None or value.utcoffset() is None:
        return False
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return False
    return value <= cutoff


# Noun-oriented alias for callers that treat policies as builders.
build_gold_readiness_decision = evaluate_gold_readiness
