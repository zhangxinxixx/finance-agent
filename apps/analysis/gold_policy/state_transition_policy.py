"""Deterministic hysteresis policy for canonical XAUUSD analysis state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta

from apps.analysis.gold_policy.analysis_policy import (
    GoldAnalysisDecision,
    GoldAnalysisDecisionV2,
)
from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import (
    AnalysisStage,
    AnalysisState,
    AnalysisStateV2,
    EvidenceCategory,
    EvidenceDeltaKind,
    PendingRule,
    PendingTransition,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
    TransitionAction,
    TransitionEvidence,
    build_analysis_state,
    build_analysis_state_v2,
    build_state_transition_policy_decision,
    build_state_transition_policy_decision_v2,
)


AnalysisDecisionContract = GoldAnalysisDecision | GoldAnalysisDecisionV2


_STAGE_GRAPH: dict[AnalysisStage, frozenset[AnalysisStage]] = {
    AnalysisStage.PRESSURE: frozenset({AnalysisStage.RANGE, AnalysisStage.WEAK_REPAIR}),
    AnalysisStage.RANGE: frozenset({AnalysisStage.PRESSURE, AnalysisStage.DIRECTION_DECISION}),
    AnalysisStage.DIRECTION_DECISION: frozenset({AnalysisStage.RANGE, AnalysisStage.WEAK_REPAIR}),
    AnalysisStage.WEAK_REPAIR: frozenset(
        {
            AnalysisStage.PRESSURE,
            AnalysisStage.DIRECTION_DECISION,
            AnalysisStage.REVERSAL_WATCH,
        }
    ),
    AnalysisStage.REVERSAL_WATCH: frozenset({AnalysisStage.WEAK_REPAIR, AnalysisStage.TREND_CONFIRMED}),
    AnalysisStage.TREND_CONFIRMED: frozenset({AnalysisStage.REVERSAL_WATCH}),
}

_DEFAULT_CONFIRMATION_GAP = {
    "intraday": timedelta(days=1),
    "daily_close": timedelta(days=4),
    "weekly_fundamental": timedelta(days=10),
}

_TREND_EXIT_CONFIRMATION_GAP = {
    "intraday": timedelta(hours=12),
    "daily_close": timedelta(days=2),
    "weekly_fundamental": timedelta(days=8),
}


@dataclass(frozen=True, slots=True)
class AnalysisStateTransitionResult:
    """One policy decision and the canonical state it leaves at the head."""

    decision: StateTransitionPolicyDecision
    state: AnalysisState | None


@dataclass(frozen=True, slots=True)
class AnalysisStateTransitionV2Result:
    """Independent v2 transition result; v1 policy remains untouched."""

    decision: StateTransitionPolicyDecisionV2
    state: AnalysisStateV2 | None


def evaluate_analysis_state_transition_v2(
    previous: AnalysisStateV2 | None,
    analysis: GoldAnalysisDecisionV2,
    evidence: TransitionEvidence,
    *,
    previous_transition: StateTransitionPolicyDecisionV2 | None = None,
) -> AnalysisStateTransitionV2Result:
    """Apply one evidence item without changing more than one v2 state dimension."""
    if previous_transition is not None:
        if previous is None or previous_transition.to_state_id != previous.state_id:
            raise ValueError("previous v2 transition must target supplied state")
        if previous_transition.evidence.as_of > evidence.as_of:
            raise ValueError("previous v2 transition cannot be after current evidence")
    if evidence.delta_kind is EvidenceDeltaKind.NO_OP:
        return _v2_preserve(
            previous,
            evidence,
            "V2_NO_MATERIAL_EVIDENCE_DELTA",
            action=TransitionAction.MAINTAIN,
        )
    if previous is not None and previous.pending_transition is not None:
        pending = previous.pending_transition
        gap = evidence.as_of - pending.last_seen_at
        max_gap = (
            _TREND_EXIT_CONFIRMATION_GAP[evidence.scope.value]
            if pending.rule is PendingRule.TREND_EXIT
            else _DEFAULT_CONFIRMATION_GAP[evidence.scope.value]
        )
        if (
            previous_transition is None
            or not previous_transition.advance
            or previous_transition.evidence.evidence_id != pending.last_evidence_id
            or not timedelta(0) < gap <= max_gap
        ):
            return _v2_preserve(previous, evidence, "V2_PENDING_HEAD_NOT_PERSISTED")
        if (
            evidence.evidence_id == pending.last_evidence_id
            or evidence.predecessor_evidence_id != pending.last_evidence_id
        ):
            return _v2_preserve(previous, evidence, "V2_DUPLICATE_PENDING_EVIDENCE")
    if previous is not None and (evidence.scope is not previous.scope or evidence.as_of <= previous.as_of):
        return _v2_preserve(previous, evidence, "V2_SCOPE_OR_TIME_MISMATCH")
    if analysis.quality_status != "accepted" or analysis.direction == "unavailable":
        return _v2_preserve(previous, evidence, "V2_ANALYSIS_NOT_ACCEPTED")
    if previous is None:
        if evidence.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION:
            return _v2_preserve(previous, evidence, "V2_INVALIDATION_WITHOUT_HEAD")
        regime = (
            "trend"
            if evidence.delta_kind is EvidenceDeltaKind.MAJOR_CONFIRMATION
            and analysis.direction in {"bullish", "bearish"}
            else _v2_regime(analysis.direction)
        )
        maturity = "confirmed" if regime == "trend" else "forming"
        state = _v2_state(None, analysis, evidence, regime, maturity, None)
        return _v2_result(None, state, evidence, "V2_BOOTSTRAP")
    if evidence.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION:
        state = _v2_state(
            previous,
            analysis,
            evidence,
            previous.market_regime,
            "invalidated",
            None,
            direction=previous.direction,
            tilt=previous.direction_tilt,
        )
        return _v2_result(
            previous,
            state,
            evidence,
            "V2_HARD_INVALIDATION",
            action=TransitionAction.INVALIDATE,
        )
    if evidence.delta_kind is EvidenceDeltaKind.MAJOR_CONFIRMATION and analysis.direction in {"bullish", "bearish"}:
        state = _v2_state(
            previous, analysis, evidence, "trend", "confirmed", None, direction=analysis.direction, tilt="none"
        )
        return _v2_result(
            previous,
            state,
            evidence,
            "V2_MAJOR_CONFIRMATION",
            action=TransitionAction.STRENGTHEN,
        )
    if (
        evidence.delta_kind is EvidenceDeltaKind.ORDINARY
        and previous.market_regime == "trend"
        and previous.trend_maturity == "confirmed"
        and analysis.direction != previous.direction
    ):
        pending = previous.pending_transition
        if pending is None or pending.rule is not PendingRule.TREND_EXIT:
            pending = PendingTransition(
                rule=PendingRule.TREND_EXIT,
                direction=analysis.direction,
                count=1,
                first_seen_at=evidence.as_of,
                last_seen_at=evidence.as_of,
                last_evidence_id=evidence.evidence_id,
                source_refs=evidence.source_refs,
            )
            state = _v2_state(
                previous,
                analysis,
                evidence,
                previous.market_regime,
                previous.trend_maturity,
                pending,
                direction=previous.direction,
                tilt=previous.direction_tilt,
            )
            return _v2_result(previous, state, evidence, "V2_TREND_EXIT_PENDING")
        state = _v2_state(
            previous,
            analysis,
            evidence,
            previous.market_regime,
            "watching",
            None,
            direction=previous.direction,
            tilt=previous.direction_tilt,
        )
        return _v2_result(previous, state, evidence, "V2_TREND_EXIT_CONFIRMED")
    if evidence.delta_kind is EvidenceDeltaKind.ORDINARY and {previous.direction, analysis.direction} == {
        "bullish",
        "bearish",
    }:
        pending = previous.pending_transition
        if pending is None or pending.rule is not PendingRule.OPPOSITE_BIAS or pending.direction != analysis.direction:
            pending = PendingTransition(
                rule=PendingRule.OPPOSITE_BIAS,
                direction=analysis.direction,
                count=1,
                first_seen_at=evidence.as_of,
                last_seen_at=evidence.as_of,
                last_evidence_id=evidence.evidence_id,
                source_refs=evidence.source_refs,
            )
            state = _v2_state(
                previous,
                analysis,
                evidence,
                previous.market_regime,
                previous.trend_maturity,
                pending,
                direction=previous.direction,
                tilt=previous.direction_tilt,
            )
            return _v2_result(previous, state, evidence, "V2_OPPOSITE_PENDING")
        # A persisted, distinct evidence item may change direction only.
        state = _v2_state(
            previous,
            analysis,
            evidence,
            previous.market_regime,
            previous.trend_maturity,
            None,
            direction=analysis.direction,
            tilt="none",
        )
        return _v2_result(previous, state, evidence, "V2_OPPOSITE_CONFIRMED")
    if evidence.delta_kind is EvidenceDeltaKind.ORDINARY:
        analysis_tilt = analysis.direction_tilt if analysis.direction == "mixed" else "none"
        if previous.market_regime == "trend" and analysis.direction not in {"bullish", "bearish"}:
            state = _v2_state(
                previous,
                analysis,
                evidence,
                "repair",
                previous.trend_maturity,
                None,
                direction=previous.direction,
                tilt=previous.direction_tilt,
            )
            return _v2_result(previous, state, evidence, "V2_ORDINARY_TREND_EXIT_STEP")
        if analysis.direction != previous.direction or analysis_tilt != previous.direction_tilt:
            state = _v2_state(
                previous,
                analysis,
                evidence,
                previous.market_regime,
                previous.trend_maturity,
                None,
                direction=analysis.direction,
                tilt=analysis_tilt,
            )
            return _v2_result(previous, state, evidence, "V2_ORDINARY_DIRECTION_STEP")
        regime, maturity = _v2_ordinary_progression(previous, analysis.direction)
        if (regime, maturity) != (previous.market_regime, previous.trend_maturity):
            state = _v2_state(
                previous,
                analysis,
                evidence,
                regime,
                maturity,
                previous.pending_transition,
            )
            return _v2_result(previous, state, evidence, "V2_ORDINARY_STATE_STEP")
    return _v2_preserve(
        previous,
        evidence,
        "V2_ORDINARY_MAINTAIN",
        action=TransitionAction.MAINTAIN,
    )


def _v2_regime(direction: str) -> str:
    return {
        "mixed": "direction_decision",
        "neutral": "range",
        "bullish": "pressure",
        "bearish": "pressure",
        "unavailable": "range",
    }[direction]


def _v2_ordinary_progression(
    previous: AnalysisStateV2,
    direction: str,
) -> tuple[str, str]:
    """Move one regime/maturity dimension for one ordinary evidence item."""

    if direction == "mixed":
        return "direction_decision", previous.trend_maturity
    if direction == "neutral":
        return "range", previous.trend_maturity
    if previous.market_regime in {"pressure", "range", "direction_decision"}:
        return "repair", previous.trend_maturity
    if previous.market_regime == "repair" and previous.trend_maturity == "forming":
        return previous.market_regime, "watching"
    if previous.market_regime == "repair" and previous.trend_maturity == "watching":
        return "trend", previous.trend_maturity
    return previous.market_regime, previous.trend_maturity


def _v2_state(previous, analysis, evidence, regime, maturity, pending, *, direction=None, tilt=None) -> AnalysisStateV2:
    refs = _refs(
        *(
            (
                SourceReference(
                    source="analysis_state",
                    reference=previous.state_id,
                    retrieved_at=previous.as_of,
                ),
            )
            if previous
            else ()
        ),
        *evidence.source_refs,
        *(ref for driver in (*analysis.dominant_drivers, *analysis.counter_drivers) for ref in driver.source_refs),
    )
    return build_analysis_state_v2(
        {
            "direction": direction or analysis.direction,
            "direction_tilt": tilt
            if tilt is not None
            else (analysis.direction_tilt if analysis.direction == "mixed" else "none"),
            "market_regime": regime,
            "trend_maturity": maturity,
            "pending_transition": pending,
            "scope": evidence.scope,
            "as_of": evidence.as_of,
            "confidence": analysis.confidence,
            "quality_status": "accepted",
            "source_refs": refs,
        }
    )


def _v2_result(previous, state, evidence, reason, *, action=None) -> AnalysisStateTransitionV2Result:
    changed_dimensions = ()
    if previous is not None:
        if previous.direction != state.direction or previous.direction_tilt != state.direction_tilt:
            changed_dimensions += ("direction",)
        if previous.market_regime != state.market_regime:
            changed_dimensions += ("market_regime",)
        if previous.trend_maturity != state.trend_maturity:
            changed_dimensions += ("trend_maturity",)
    payload = {
        "from_state_id": previous.state_id if previous else None,
        "to_state_id": state.state_id,
        "action": action or (TransitionAction.PENDING if state.pending_transition else TransitionAction.STRENGTHEN),
        "transition_allowed": True,
        "advance": previous is None or previous.state_id != state.state_id,
        "from_direction": previous.direction if previous else None,
        "to_direction": state.direction,
        "from_direction_tilt": previous.direction_tilt if previous else None,
        "to_direction_tilt": state.direction_tilt,
        "from_market_regime": previous.market_regime if previous else None,
        "to_market_regime": state.market_regime,
        "from_trend_maturity": previous.trend_maturity if previous else None,
        "to_trend_maturity": state.trend_maturity,
        "changed_dimensions": changed_dimensions,
        "evidence": evidence,
        "reasons": (reason,),
    }
    decision = build_state_transition_policy_decision_v2(payload)
    return AnalysisStateTransitionV2Result(decision=decision, state=state)


def _v2_preserve(previous, evidence, reason, *, action=TransitionAction.PENDING) -> AnalysisStateTransitionV2Result:
    decision = build_state_transition_policy_decision_v2(
        {
            "from_state_id": previous.state_id if previous else None,
            "to_state_id": previous.state_id if previous else None,
            "action": action,
            "transition_allowed": previous is not None,
            "advance": False,
            "from_direction": previous.direction if previous else None,
            "to_direction": previous.direction if previous else None,
            "from_direction_tilt": previous.direction_tilt if previous else None,
            "to_direction_tilt": previous.direction_tilt if previous else None,
            "from_market_regime": previous.market_regime if previous else None,
            "to_market_regime": previous.market_regime if previous else None,
            "from_trend_maturity": previous.trend_maturity if previous else None,
            "to_trend_maturity": previous.trend_maturity if previous else None,
            "changed_dimensions": (),
            "evidence": evidence,
            "reasons": (reason,),
        }
    )
    return AnalysisStateTransitionV2Result(decision=decision, state=previous)


def evaluate_analysis_state_transition(
    previous: AnalysisState | None,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
    *,
    previous_transition: StateTransitionPolicyDecision | None = None,
) -> AnalysisStateTransitionResult:
    """Evaluate one immutable transition without I/O, clocks, or prose inference.

    ``previous_transition`` must be the latest transition-head artifact for the
    same scope. A missing or non-advancing head can never complete pending
    hysteresis, which keeps persistence failures fail-closed.
    """

    if previous is not None and evidence.as_of < previous.as_of:
        raise ValueError("transition evidence cannot predate the previous state")
    if previous_transition is not None:
        if previous is None or previous_transition.to_state_id != previous.state_id:
            raise ValueError("previous transition must target the supplied canonical state")
        if previous_transition.evidence.as_of > evidence.as_of:
            raise ValueError("previous transition cannot be after current evidence")

    if previous is not None and evidence.scope is not previous.scope:
        return _preserve(
            previous,
            evidence,
            action=_preserve_action(evidence),
            transition_allowed=False,
            reason="SCOPE_HEAD_MISMATCH",
        )

    if analysis.quality_status != "accepted":
        reason = (
            "ANALYSIS_DECISION_BLOCKED" if analysis.quality_status == "blocked" else "ANALYSIS_DECISION_NOT_ACCEPTED"
        )
        return _preserve(
            previous,
            evidence,
            action=_preserve_action(evidence),
            transition_allowed=False,
            reason=reason,
        )

    if (
        previous is not None
        and previous.pending_transition is not None
        and previous.pending_transition.last_evidence_id == evidence.evidence_id
    ):
        return _preserve(
            previous,
            evidence,
            action=_preserve_action(evidence),
            transition_allowed=True,
            reason="DUPLICATE_EVIDENCE_ALREADY_APPLIED",
        )

    if previous is not None and evidence.as_of == previous.as_of and evidence.delta_kind is not EvidenceDeltaKind.NO_OP:
        return _preserve(
            previous,
            evidence,
            action=TransitionAction.PENDING,
            transition_allowed=False,
            reason="EVIDENCE_AS_OF_NOT_STRICTLY_NEW",
        )

    if evidence.delta_kind is EvidenceDeltaKind.NO_OP:
        return _preserve(
            previous,
            evidence,
            action=TransitionAction.MAINTAIN,
            transition_allowed=previous is not None,
            reason="NO_MATERIAL_EVIDENCE_DELTA",
        )

    if analysis.market_stage_candidate != _expected_analysis_candidate(analysis.direction):
        return _preserve(
            previous,
            evidence,
            action=TransitionAction.PENDING,
            transition_allowed=False,
            reason="ANALYSIS_STAGE_CANDIDATE_MISMATCH",
        )

    if analysis.direction == "unavailable":
        return _preserve(
            previous,
            evidence,
            action=TransitionAction.PENDING,
            transition_allowed=False,
            reason="ACCEPTED_DIRECTION_UNAVAILABLE",
        )

    if previous is None:
        return _bootstrap(analysis, evidence)

    if evidence.delta_kind is EvidenceDeltaKind.HARD_INVALIDATION:
        return _hard_invalidation(previous, analysis, evidence)
    if evidence.delta_kind is EvidenceDeltaKind.MAJOR_CONFIRMATION:
        return _major_confirmation(
            previous,
            previous_transition,
            analysis,
            evidence,
        )
    return _ordinary(previous, previous_transition, analysis, evidence)


def ordinary_stage_distance(start: AnalysisStage, target: AnalysisStage) -> int:
    """Return shortest business-graph distance; enum order is deliberately unused."""

    if start is target:
        return 0
    frontier = {start}
    visited = set(frontier)
    distance = 0
    while frontier:
        distance += 1
        frontier = {adjacent for stage in frontier for adjacent in _STAGE_GRAPH[stage] if adjacent not in visited}
        if target in frontier:
            return distance
        visited.update(frontier)
    raise ValueError(f"no stage path from {start} to {target}")


def _bootstrap(
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisStateTransitionResult:
    stage = _base_stage(analysis.direction)
    state = _state(
        previous=None,
        stage=stage,
        bias=analysis.direction,
        pending=None,
        confidence=analysis.confidence,
        analysis=analysis,
        evidence=evidence,
    )
    return _result(
        previous=None,
        state=state,
        evidence=evidence,
        action=(TransitionAction.PENDING if analysis.direction == "mixed" else TransitionAction.STRENGTHEN),
        transition_allowed=True,
        reason=f"INITIAL_{stage.value.upper()}_BOOTSTRAP",
    )


def _ordinary(
    previous: AnalysisState,
    previous_transition: StateTransitionPolicyDecision | None,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisStateTransitionResult:
    new_bias = analysis.direction
    old_bias = previous.directional_bias

    if previous.stage is AnalysisStage.TREND_CONFIRMED and new_bias != old_bias:
        if EvidenceCategory.PRICE not in evidence.evidence_categories:
            return _preserve(
                previous,
                evidence,
                action=TransitionAction.PENDING,
                transition_allowed=True,
                reason="TREND_EXIT_EVIDENCE_INSUFFICIENT",
            )
        if not _pending_matches(
            previous,
            PendingRule.TREND_EXIT,
            new_bias,
            evidence,
            previous_transition,
        ):
            return _pending(
                previous,
                analysis,
                evidence,
                PendingRule.TREND_EXIT,
                new_bias,
            )
        return _advance(
            previous,
            analysis,
            evidence,
            stage=AnalysisStage.REVERSAL_WATCH,
            bias=old_bias,
            pending=None,
            action=TransitionAction.WEAKEN,
            reason="TREND_EXIT_COUNTER_EVIDENCE_CONFIRMED",
        )

    if new_bias == "mixed":
        return _conflict(
            previous,
            previous_transition,
            analysis,
            evidence,
        )

    if _opposite(old_bias, new_bias):
        rule = PendingRule.OPPOSITE_BIAS
        if not _pending_matches(
            previous,
            rule,
            new_bias,
            evidence,
            previous_transition,
        ):
            return _pending(previous, analysis, evidence, rule, new_bias)
        next_stage = _opposite_step(previous.stage)
        next_bias = "mixed" if next_stage in {AnalysisStage.RANGE, AnalysisStage.DIRECTION_DECISION} else old_bias
        return _advance(
            previous,
            analysis,
            evidence,
            stage=next_stage,
            bias=next_bias,
            pending=None,
            action=TransitionAction.WEAKEN,
            reason="OPPOSITE_EVIDENCE_CONFIRMED",
        )

    if old_bias == "mixed" and new_bias in {"bullish", "bearish"}:
        if not _pending_matches(
            previous,
            PendingRule.NEW_BIAS,
            new_bias,
            evidence,
            previous_transition,
        ):
            return _pending(
                previous,
                analysis,
                evidence,
                PendingRule.NEW_BIAS,
                new_bias,
            )
        return _advance(
            previous,
            analysis,
            evidence,
            stage=previous.stage,
            bias=new_bias,
            pending=None,
            action=TransitionAction.STRENGTHEN,
            reason="NEW_BIAS_CONFIRMED",
        )

    if old_bias == "neutral" and new_bias in {"bullish", "bearish"}:
        next_stage = _one_step(previous.stage, AnalysisStage.PRESSURE)
        return _advance(
            previous,
            analysis,
            evidence,
            stage=next_stage,
            bias=new_bias,
            pending=None,
            action=TransitionAction.STRENGTHEN,
            reason="ORDINARY_DIRECTION_ESTABLISHED",
        )

    if new_bias == "neutral":
        next_stage = _one_step(previous.stage, AnalysisStage.RANGE)
        next_bias = "neutral" if next_stage is AnalysisStage.RANGE else old_bias
        return _advance(
            previous,
            analysis,
            evidence,
            stage=next_stage,
            bias=next_bias,
            pending=None,
            action=TransitionAction.WEAKEN,
            reason="ORDINARY_PRESSURE_EASED",
        )

    if new_bias in {"bullish", "bearish"} and new_bias == old_bias:
        if previous.pending_transition is not None and previous.pending_transition.rule is not PendingRule.TREND_ENTRY:
            return _advance(
                previous,
                analysis,
                evidence,
                stage=previous.stage,
                bias=old_bias,
                pending=None,
                action=TransitionAction.STRENGTHEN,
                reason="COUNTER_EVIDENCE_CLEARED",
            )
        if previous.stage is AnalysisStage.REVERSAL_WATCH:
            if not _multi_category_confirmation(evidence):
                return _preserve(
                    previous,
                    evidence,
                    action=TransitionAction.PENDING,
                    transition_allowed=True,
                    reason="TREND_ENTRY_EVIDENCE_INSUFFICIENT",
                )
            if not _pending_matches(
                previous,
                PendingRule.TREND_ENTRY,
                new_bias,
                evidence,
                previous_transition,
            ):
                return _pending(
                    previous,
                    analysis,
                    evidence,
                    PendingRule.TREND_ENTRY,
                    new_bias,
                )
            return _advance(
                previous,
                analysis,
                evidence,
                stage=AnalysisStage.TREND_CONFIRMED,
                bias=old_bias,
                pending=None,
                action=TransitionAction.STRENGTHEN,
                reason="TREND_ENTRY_CONFIRMED",
            )
        next_stage = _support_step(previous.stage)
        return _advance(
            previous,
            analysis,
            evidence,
            stage=next_stage,
            bias=old_bias,
            pending=None,
            action=TransitionAction.STRENGTHEN,
            reason="ORDINARY_SUPPORT_ONE_STEP",
        )

    next_stage = _one_step(previous.stage, _base_stage(new_bias))
    return _advance(
        previous,
        analysis,
        evidence,
        stage=next_stage,
        bias=new_bias,
        pending=None,
        action=TransitionAction.STRENGTHEN,
        reason="ORDINARY_STATE_ALIGNED",
    )


def _conflict(
    previous: AnalysisState,
    previous_transition: StateTransitionPolicyDecision | None,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisStateTransitionResult:
    if not _pending_matches(
        previous,
        PendingRule.CONFLICT,
        "mixed",
        evidence,
        previous_transition,
    ):
        return _pending(
            previous,
            analysis,
            evidence,
            PendingRule.CONFLICT,
            "mixed",
        )
    next_stage = _one_step(previous.stage, AnalysisStage.DIRECTION_DECISION)
    next_bias = (
        "mixed" if next_stage in {AnalysisStage.DIRECTION_DECISION, AnalysisStage.RANGE} else previous.directional_bias
    )
    return _advance(
        previous,
        analysis,
        evidence,
        stage=next_stage,
        bias=next_bias,
        pending=None,
        action=TransitionAction.WEAKEN,
        reason="CONFLICT_PERSISTED",
    )


def _major_confirmation(
    previous: AnalysisState,
    previous_transition: StateTransitionPolicyDecision | None,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisStateTransitionResult:
    new_bias = analysis.direction
    old_bias = previous.directional_bias
    if new_bias not in {"bullish", "bearish"}:
        return _preserve(
            previous,
            evidence,
            action=TransitionAction.PENDING,
            transition_allowed=False,
            reason="MAJOR_CONFIRMATION_DIRECTION_NOT_DIRECTIONAL",
        )
    if _opposite(old_bias, new_bias):
        pending = _new_pending(evidence, PendingRule.NEW_BIAS, new_bias)
        return _advance(
            previous,
            analysis,
            evidence,
            stage=AnalysisStage.DIRECTION_DECISION,
            bias="mixed",
            pending=pending,
            action=TransitionAction.INVALIDATE,
            reason="MAJOR_CONFIRMATION_INVALIDATED_PRIOR_BIAS",
        )
    if previous.stage is AnalysisStage.REVERSAL_WATCH and _pending_matches(
        previous,
        PendingRule.TREND_ENTRY,
        new_bias,
        evidence,
        previous_transition,
    ):
        return _advance(
            previous,
            analysis,
            evidence,
            stage=AnalysisStage.TREND_CONFIRMED,
            bias=new_bias,
            pending=None,
            action=TransitionAction.STRENGTHEN,
            reason="MAJOR_CONFIRMATION_TREND_ENTRY_SATISFIED",
        )
    target = (
        AnalysisStage.TREND_CONFIRMED
        if previous.stage is AnalysisStage.TREND_CONFIRMED
        else AnalysisStage.REVERSAL_WATCH
    )
    return _advance(
        previous,
        analysis,
        evidence,
        stage=target,
        bias=new_bias,
        pending=None,
        action=TransitionAction.STRENGTHEN,
        reason="MAJOR_CONFIRMATION_ACCELERATED",
    )


def _hard_invalidation(
    previous: AnalysisState,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisStateTransitionResult:
    if analysis.direction == "neutral":
        stage = AnalysisStage.RANGE
        bias = "neutral"
    else:
        stage = AnalysisStage.DIRECTION_DECISION
        bias = "mixed"
    return _advance(
        previous,
        analysis,
        evidence,
        stage=stage,
        bias=bias,
        pending=None,
        action=TransitionAction.INVALIDATE,
        reason=(evidence.rule_code.value if evidence.rule_code is not None else "HARD_INVALIDATION"),
    )


def _pending(
    previous: AnalysisState,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
    rule: PendingRule,
    direction: str,
) -> AnalysisStateTransitionResult:
    pending = _new_pending(evidence, rule, direction)
    return _advance(
        previous,
        analysis,
        evidence,
        stage=previous.stage,
        bias=previous.directional_bias,
        pending=pending,
        action=TransitionAction.PENDING,
        reason=f"{rule.value.upper()}_FIRST_OR_CONTINUING_EVIDENCE",
    )


def _new_pending(
    evidence: TransitionEvidence,
    rule: PendingRule,
    direction: str,
) -> PendingTransition:
    return PendingTransition(
        rule=rule,
        direction=direction,
        count=1,
        first_seen_at=evidence.as_of,
        last_seen_at=evidence.as_of,
        last_evidence_id=evidence.evidence_id,
        source_refs=evidence.source_refs,
    )


def _pending_matches(
    previous: AnalysisState,
    rule: PendingRule,
    direction: str,
    evidence: TransitionEvidence,
    previous_transition: StateTransitionPolicyDecision | None,
) -> bool:
    pending = previous.pending_transition
    return (
        pending is not None
        and pending.rule is rule
        and pending.direction == direction
        and _pending_is_continuous(
            previous,
            pending,
            evidence,
            previous_transition,
        )
    )


def _pending_is_continuous(
    previous: AnalysisState,
    pending: PendingTransition,
    evidence: TransitionEvidence,
    previous_transition: StateTransitionPolicyDecision | None,
) -> bool:
    gap = evidence.as_of - pending.last_seen_at
    max_gap = (
        _TREND_EXIT_CONFIRMATION_GAP[evidence.scope.value]
        if pending.rule is PendingRule.TREND_EXIT
        else _DEFAULT_CONFIRMATION_GAP[evidence.scope.value]
    )
    return (
        timedelta(0) < gap <= max_gap
        and previous_transition is not None
        and previous_transition.to_state_id == previous.state_id
        and previous_transition.action is TransitionAction.PENDING
        and previous_transition.transition_allowed
        and previous_transition.advance
        and previous_transition.evidence.evidence_id == pending.last_evidence_id
        and previous_transition.evidence.scope is evidence.scope
        and evidence.predecessor_evidence_id == pending.last_evidence_id
    )


def _advance(
    previous: AnalysisState,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
    *,
    stage: AnalysisStage,
    bias: str,
    pending: PendingTransition | None,
    action: TransitionAction,
    reason: str,
) -> AnalysisStateTransitionResult:
    if evidence.delta_kind is EvidenceDeltaKind.ORDINARY:
        distance = ordinary_stage_distance(previous.stage, stage)
        if distance > 1:
            raise ValueError("ordinary transition cannot cross more than one business edge")
    confidence = _confidence(previous, analysis, action)
    state = _state(
        previous=previous,
        stage=stage,
        bias=bias,
        pending=pending,
        confidence=confidence,
        analysis=analysis,
        evidence=evidence,
    )
    return _result(
        previous=previous,
        state=state,
        evidence=evidence,
        action=action,
        transition_allowed=True,
        reason=reason,
    )


def _state(
    *,
    previous: AnalysisState | None,
    stage: AnalysisStage,
    bias: str,
    pending: PendingTransition | None,
    confidence: float,
    analysis: AnalysisDecisionContract,
    evidence: TransitionEvidence,
) -> AnalysisState:
    source_refs = _refs(
        *(
            (
                SourceReference(
                    source="analysis_state",
                    reference=previous.state_id,
                    retrieved_at=previous.as_of,
                ),
            )
            if previous is not None
            else ()
        ),
        *evidence.source_refs,
        *(ref for driver in (*analysis.dominant_drivers, *analysis.counter_drivers) for ref in driver.source_refs),
    )
    return build_analysis_state(
        {
            "stage": stage,
            "directional_bias": bias,
            "pending_transition": pending,
            "scope": evidence.scope,
            "as_of": evidence.as_of,
            "confidence": confidence,
            "quality_status": "accepted",
            "source_refs": source_refs,
        }
    )


def _result(
    *,
    previous: AnalysisState | None,
    state: AnalysisState,
    evidence: TransitionEvidence,
    action: TransitionAction,
    transition_allowed: bool,
    reason: str,
) -> AnalysisStateTransitionResult:
    decision = build_state_transition_policy_decision(
        {
            "from_state_id": previous.state_id if previous is not None else None,
            "to_state_id": state.state_id,
            "from_stage": previous.stage if previous is not None else None,
            "to_stage": state.stage,
            "action": action,
            "transition_allowed": transition_allowed,
            "advance": previous is None or previous.state_id != state.state_id,
            "stage_changed": previous is None or previous.stage is not state.stage,
            "evidence": evidence,
            "reasons": (reason,),
        }
    )
    return AnalysisStateTransitionResult(decision=decision, state=state)


def _preserve(
    previous: AnalysisState | None,
    evidence: TransitionEvidence,
    *,
    action: TransitionAction,
    transition_allowed: bool,
    reason: str,
) -> AnalysisStateTransitionResult:
    decision = build_state_transition_policy_decision(
        {
            "from_state_id": previous.state_id if previous is not None else None,
            "to_state_id": previous.state_id if previous is not None else None,
            "from_stage": previous.stage if previous is not None else None,
            "to_stage": previous.stage if previous is not None else None,
            "action": action,
            "transition_allowed": transition_allowed,
            "advance": False,
            "stage_changed": False,
            "evidence": evidence,
            "reasons": (reason,),
        }
    )
    return AnalysisStateTransitionResult(decision=decision, state=previous)


def _base_stage(direction: str) -> AnalysisStage:
    if direction == "mixed":
        return AnalysisStage.DIRECTION_DECISION
    if direction == "neutral":
        return AnalysisStage.RANGE
    return AnalysisStage.PRESSURE


def _expected_analysis_candidate(direction: str) -> str:
    return {
        "bullish": "upside_pressure",
        "bearish": "downside_pressure",
        "mixed": "direction_decision",
        "neutral": "range",
        "unavailable": "unavailable",
    }[direction]


def _support_step(stage: AnalysisStage) -> AnalysisStage:
    return {
        AnalysisStage.PRESSURE: AnalysisStage.WEAK_REPAIR,
        AnalysisStage.RANGE: AnalysisStage.PRESSURE,
        AnalysisStage.DIRECTION_DECISION: AnalysisStage.WEAK_REPAIR,
        AnalysisStage.WEAK_REPAIR: AnalysisStage.REVERSAL_WATCH,
        AnalysisStage.TREND_CONFIRMED: AnalysisStage.TREND_CONFIRMED,
    }[stage]


def _opposite_step(stage: AnalysisStage) -> AnalysisStage:
    return {
        AnalysisStage.PRESSURE: AnalysisStage.WEAK_REPAIR,
        AnalysisStage.RANGE: AnalysisStage.DIRECTION_DECISION,
        AnalysisStage.DIRECTION_DECISION: AnalysisStage.DIRECTION_DECISION,
        AnalysisStage.WEAK_REPAIR: AnalysisStage.DIRECTION_DECISION,
        AnalysisStage.REVERSAL_WATCH: AnalysisStage.WEAK_REPAIR,
        AnalysisStage.TREND_CONFIRMED: AnalysisStage.REVERSAL_WATCH,
    }[stage]


def _one_step(start: AnalysisStage, target: AnalysisStage) -> AnalysisStage:
    if start is target:
        return start
    candidates = sorted(
        _STAGE_GRAPH[start],
        key=lambda stage: (ordinary_stage_distance(stage, target), stage.value),
    )
    return candidates[0]


def _opposite(old_bias: str, new_bias: str) -> bool:
    return {old_bias, new_bias} == {"bullish", "bearish"}


def _preserve_action(evidence: TransitionEvidence) -> TransitionAction:
    return TransitionAction.MAINTAIN if evidence.delta_kind is EvidenceDeltaKind.NO_OP else TransitionAction.PENDING


def _multi_category_confirmation(evidence: TransitionEvidence) -> bool:
    categories = set(evidence.evidence_categories)
    return EvidenceCategory.PRICE in categories and bool(
        categories.intersection({EvidenceCategory.MACRO, EvidenceCategory.STRUCTURE})
    )


def _confidence(
    previous: AnalysisState,
    analysis: AnalysisDecisionContract,
    action: TransitionAction,
) -> float:
    if action is TransitionAction.STRENGTHEN:
        return max(previous.confidence, analysis.confidence)
    if action is TransitionAction.WEAKEN:
        return min(previous.confidence, analysis.confidence)
    if action is TransitionAction.INVALIDATE:
        return analysis.confidence
    return previous.confidence


def _refs(*refs: SourceReference) -> tuple[SourceReference, ...]:
    unique: dict[tuple[str, str, object], SourceReference] = {}
    for ref in refs:
        key = (ref.source, ref.reference, ref.retrieved_at.astimezone(UTC))
        unique[key] = ref
    return tuple(unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], item[2])))
