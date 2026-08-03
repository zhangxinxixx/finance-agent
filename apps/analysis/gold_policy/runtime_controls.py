"""Pure builders for authoritative Gold daily-close runtime controls."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from apps.analysis.gold_policy.analysis_policy import evaluate_gold_analysis_policy
from apps.analysis.gold_policy.attribution_policy import attribute_gold_price
from apps.analysis.gold_policy.daily_close_runtime import GoldDailyCloseRuntimeControls
from apps.analysis.gold_policy.key_level_controls import (
    KeyLevelControlsBuilder,
    KeyLevelControlsInput,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotContract, SourceReference
from apps.analysis.gold_policy.state_schemas import (
    EvidenceCategory,
    EvidenceDeltaKind,
    MajorConfirmationRule,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
    TransitionEvidence,
)
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyOptionsRegimeContract,
    build_strategy_event_risk,
    build_strategy_options_regime,
)


def build_gold_daily_close_runtime_controls(
    *,
    current_feature: FeatureSnapshotContract,
    previous_feature: FeatureSnapshotContract | None,
    decision_as_of: datetime,
    previous_transition: (StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None) = None,
    options_regime_snapshot: StrategyOptionsRegimeContract | None = None,
    key_level_controls_input: KeyLevelControlsInput | None = None,
) -> GoldDailyCloseRuntimeControls:
    """Build fail-closed controls from typed inputs without I/O or prose."""

    decision_time = _aware_utc(decision_as_of)
    if current_feature.as_of > decision_time:
        raise ValueError("current feature cannot be after runtime decision_as_of")
    if current_feature.as_of.date() != decision_time.date():
        raise ValueError("current feature and runtime controls must share a UTC session date")

    analysis = evaluate_gold_analysis_policy(current_feature, previous_feature)
    attribution = attribute_gold_price(current_feature, previous_feature)
    evidence = _transition_evidence(
        current=current_feature,
        analysis=analysis,
        attribution=attribution,
        decision_as_of=decision_time,
        previous_transition=previous_transition,
    )
    options = options_regime_snapshot or _options_regime(current_feature, decision_time)
    if options.source_snapshot_id != current_feature.snapshot_id:
        raise ValueError("options regime must bind the current feature snapshot")
    if options.as_of != decision_time:
        raise ValueError("options regime must align to runtime decision_as_of")
    event_risk = _event_risk(current_feature, decision_time)
    if key_level_controls_input is None:
        key_level_controls = KeyLevelControlsBuilder().build(
            KeyLevelControlsInput(
                decision_as_of=decision_time,
                scope="daily_close",
            )
        )
        reasons = ["KEY_LEVEL_CONTROLS_EMPTY_NO_FORMAL_LIFECYCLE_INPUT"]
    else:
        if key_level_controls_input.decision_as_of != decision_time:
            raise ValueError("key-level controls must align to runtime decision_as_of")
        if key_level_controls_input.scope.value != "daily_close":
            raise ValueError("key-level controls must use daily_close scope")
        key_level_controls = KeyLevelControlsBuilder().build(key_level_controls_input)
        reasons = list(key_level_controls.reason_codes)
    if options.regime.value == "unavailable":
        reasons.append("OPTIONS_REGIME_UNAVAILABLE")
    formal_reason_codes = getattr(options, "reason_codes", ())
    reasons.extend(str(code) for code in formal_reason_codes)
    if event_risk.risk_status.value == "unavailable":
        reasons.append("EVENT_RISK_UNAVAILABLE")
    return GoldDailyCloseRuntimeControls(
        decision_as_of=decision_time,
        transition_evidence=evidence,
        options_regime=options,
        event_risk=event_risk,
        key_levels=key_level_controls.key_levels,
        key_level_decisions=key_level_controls.key_level_decisions,
        key_level_proof=key_level_controls.key_level_proof,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _transition_evidence(
    *,
    current: FeatureSnapshotContract,
    analysis: object,
    attribution: object,
    decision_as_of: datetime,
    previous_transition: (StateTransitionPolicyDecision | StateTransitionPolicyDecisionV2 | None),
) -> TransitionEvidence:
    analysis_drivers = (*analysis.dominant_drivers, *analysis.counter_drivers)  # type: ignore[attr-defined]
    categories: set[EvidenceCategory] = set()
    if analysis_drivers:
        categories.add(EvidenceCategory.MACRO)
    if attribution.price_move in {"up", "down"}:  # type: ignore[attr-defined]
        categories.add(EvidenceCategory.PRICE)

    rule_code = None
    if attribution.attribution_status == "confirmed_event":  # type: ignore[attr-defined]
        delta_kind = EvidenceDeltaKind.MAJOR_CONFIRMATION
        categories = {EvidenceCategory.PRICE, EvidenceCategory.OFFICIAL_EVENT}
        rule_code = MajorConfirmationRule.OFFICIAL_EVENT_REACTION_CONFIRMED
    elif (
        attribution.attribution_status == "cross_asset_consistent"  # type: ignore[attr-defined]
        and EvidenceCategory.MACRO in categories
        and EvidenceCategory.PRICE in categories
    ):
        delta_kind = EvidenceDeltaKind.MAJOR_CONFIRMATION
        rule_code = MajorConfirmationRule.MAJOR_MACRO_REACTION_CONFIRMED
    elif categories:
        delta_kind = EvidenceDeltaKind.ORDINARY
    else:
        delta_kind = EvidenceDeltaKind.NO_OP

    refs = _refs(
        decision_as_of,
        *(ref for driver in analysis_drivers for ref in driver.source_refs),
        *attribution.source_refs,  # type: ignore[attr-defined]
        *current.xauusd_spot.source_refs,
    )
    predecessor_evidence_id = (
        previous_transition.evidence.evidence_id
        if previous_transition is not None and delta_kind is not EvidenceDeltaKind.NO_OP
        else None
    )
    identity_payload = {
        "current_feature_id": current.snapshot_id,
        "analysis_policy_version": analysis.policy_version,  # type: ignore[attr-defined]
        "attribution_policy_version": attribution.policy_version,  # type: ignore[attr-defined]
        "delta_kind": delta_kind.value,
        "categories": sorted(item.value for item in categories),
        "rule_code": rule_code.value if rule_code is not None else None,
        "predecessor_evidence_id": predecessor_evidence_id,
    }
    digest = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return TransitionEvidence(
        evidence_id=f"gold_transition_evidence.v1:{digest}",
        scope="daily_close",
        delta_kind=delta_kind,
        as_of=decision_as_of,
        source_refs=refs,
        evidence_categories=tuple(sorted(categories, key=lambda item: item.value)),
        predecessor_evidence_id=predecessor_evidence_id,
        rule_code=rule_code,
    )


def _options_regime(current: FeatureSnapshotContract, decision_as_of: datetime):
    observation = current.cme_options_regime
    if observation.value is None or observation.quality_status == "blocked":
        regime = "unavailable"
        directional_bias = "unavailable"
    elif observation.value < 0:
        regime = "stress"
        directional_bias = "neutral"
    elif observation.value == 0:
        regime = "pinning"
        directional_bias = "neutral"
    else:
        regime = "normal"
        directional_bias = "neutral"
    return build_strategy_options_regime(
        {
            "source_snapshot_id": current.snapshot_id,
            "as_of": decision_as_of,
            "regime": regime,
            "directional_bias": directional_bias,
            "freshness_status": observation.freshness_status,
            "quality_status": observation.quality_status,
            "alignment_status": observation.alignment_status,
            "source_refs": _refs(decision_as_of, *observation.source_refs),
        }
    )


def _event_risk(current: FeatureSnapshotContract, decision_as_of: datetime):
    events = current.official_events
    if events.quality_status == "blocked" or events.freshness_status == "missing":
        risk_status = "unavailable"
        active_ids: tuple[str, ...] = ()
    else:
        active_ids = tuple(
            sorted(
                event.event_id
                for event in events.events
                if event.occurred_at <= decision_as_of and event.reaction_status != "confirmed"
            )
        )
        risk_status = "watch" if active_ids else "clear"
    return build_strategy_event_risk(
        {
            "as_of": decision_as_of,
            "risk_status": risk_status,
            "active_event_ids": active_ids,
            "quality_status": events.quality_status,
            "source_refs": _refs(decision_as_of, *events.source_refs),
        }
    )


def _refs(as_of: datetime, *refs: SourceReference) -> tuple[SourceReference, ...]:
    unique = {(ref.source, ref.reference, ref.retrieved_at): ref for ref in refs if ref.retrieved_at <= as_of}
    if not unique:
        raise ValueError("runtime controls require an upstream typed source reference")
    return tuple(unique[key] for key in sorted(unique))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime decision_as_of must be timezone-aware")
    return value.astimezone(UTC)
