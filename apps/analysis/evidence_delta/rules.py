"""Frozen deterministic rules and source adapters for EvidenceDeltaEvaluator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apps.analysis.context_bundle.schemas import EvidenceItem
from apps.analysis.figure_facts import FigureFact, validate_figure_fact
from apps.analysis.state.hashing import content_hash

from .schemas import (
    DELTA_EVIDENCE_ADAPTER,
    ConfirmationStatus,
    DeltaEvidence,
    EvaluationOutcome,
    FigureFactEvidence,
    KeyLevelEvidence,
    MacroMetricEvidence,
    MaterialEventEvidence,
    Materiality,
    OptionsRegimeEvidence,
    RecommendedAction,
    SourceQuality,
)


TRUSTED_MARKET_SOURCES = frozenset(
    {SourceQuality.OFFICIAL, SourceQuality.EXCHANGE, SourceQuality.PRIMARY, SourceQuality.VALIDATED}
)
MACRO_THRESHOLDS: dict[str, tuple[float, float]] = {
    # context threshold, transition threshold; rates are percentage-point changes.
    "dxy": (0.20, 0.50),
    "us02y": (0.03, 0.08),
    "us10y": (0.03, 0.08),
    "real10y": (0.03, 0.07),
    "breakeven10y": (0.03, 0.07),
    "oil": (1.00, 3.00),
}


@dataclass(frozen=True)
class RuleResult:
    materiality: Materiality
    outcome: EvaluationOutcome
    action: RecommendedAction
    affected_state_fields: tuple[str, ...]
    reasons: tuple[str, ...]


def adapt_context_evidence(item: EvidenceItem | Mapping[str, Any]) -> DeltaEvidence:
    """Adapt one ContextBundle item using an explicit ``payload.evidence_type`` contract."""

    validated = item if isinstance(item, EvidenceItem) else EvidenceItem.model_validate(item)
    evidence_type = str(validated.payload.get("evidence_type") or "").strip()
    if not evidence_type:
        raise ValueError("payload.evidence_type is required for evidence delta adaptation")
    payload = dict(validated.payload)
    payload.update(
        {
            "source": validated.source,
            "evidence_id": validated.evidence_id,
            "observed_at": validated.business_time,
            "source_ref": dict(validated.source_ref),
        }
    )
    if "asset" not in payload:
        raise ValueError("payload.asset is required for evidence delta adaptation")
    if "source_quality" not in payload:
        raise ValueError("payload.source_quality is required for evidence delta adaptation")
    return DELTA_EVIDENCE_ADAPTER.validate_python(payload)


def adapt_figure_fact(
    fact: FigureFact | Mapping[str, Any], *, observed_at: datetime, source: str = "figure_fact"
) -> FigureFactEvidence:
    """Project a validated FigureFact without promoting non-accepted facts."""

    validated = validate_figure_fact(dict(fact) if isinstance(fact, Mapping) else fact)
    return FigureFactEvidence(
        source=source,
        evidence_id=validated.figure_fact_id,
        asset=validated.asset,
        observed_at=observed_at,
        source_quality=(
            SourceQuality.VALIDATED
            if validated.quality_status.value == "accepted"
            else SourceQuality.UNVERIFIED
        ),
        source_ref=dict(validated.source_ref),
        metadata={"review_ref": validated.review_ref} if validated.review_ref else {},
        figure_fact_id=validated.figure_fact_id,
        figure_id=validated.figure_id,
        report_id=validated.report_id,
        figure_content_hash=validated.content_hash,
        quality_status=validated.quality_status.value,
        has_direct_evidence=bool(validated.observations or validated.numeric_values),
    )


def semantic_identity(item: DeltaEvidence) -> str:
    if isinstance(item, MacroMetricEvidence):
        return f"macro_metric:{item.metric}"
    if isinstance(item, KeyLevelEvidence):
        return _semantic_key("key_level", item.level_id)
    if isinstance(item, OptionsRegimeEvidence):
        return _semantic_key("options_regime", item.regime_id, item.event)
    if isinstance(item, MaterialEventEvidence):
        return _semantic_key("material_event", item.cluster_key.casefold())
    return _semantic_key("figure_fact", item.report_id, item.figure_id)


def semantic_hash(item: DeltaEvidence) -> str:
    """Hash business meaning, excluding delivery/provenance-only metadata."""

    payload = item.model_dump(
        mode="json",
        exclude={"source", "evidence_id", "observed_at", "source_ref", "metadata"},
    )
    if isinstance(item, MaterialEventEvidence):
        # Different collectors may assign different IDs to the same clustered claim.
        payload.pop("event_id", None)
        payload.pop("source_quality", None)
        payload["claim"] = " ".join(item.claim.casefold().split())
        payload["cluster_key"] = item.cluster_key.casefold()
    return content_hash(payload, exclude_keys=frozenset())


def evaluate_rule(item: DeltaEvidence) -> RuleResult:
    if isinstance(item, MacroMetricEvidence):
        return _macro_rule(item)
    if isinstance(item, KeyLevelEvidence):
        return _key_level_rule(item)
    if isinstance(item, OptionsRegimeEvidence):
        return _options_rule(item)
    if isinstance(item, MaterialEventEvidence):
        return _material_event_rule(item)
    return _figure_rule(item)


def _macro_rule(item: MacroMetricEvidence) -> RuleResult:
    if item.previous_value == 0:
        return _manual("macro_previous_value_zero", ("dominant_drivers",))
    if item.metric in {"dxy", "oil"}:
        movement = abs((item.current_value - item.previous_value) / item.previous_value) * 100.0
        unit = "pct"
    else:
        movement = abs(item.current_value - item.previous_value)
        unit = "percentage_point"
    context_threshold, transition_threshold = MACRO_THRESHOLDS[item.metric]
    prefix = f"macro:{item.metric}:movement_{movement:.6f}_{unit}"
    if movement < context_threshold:
        return _no_op(f"{prefix}:below_context_threshold")
    if item.source_quality not in TRUSTED_MARKET_SOURCES:
        if movement >= transition_threshold:
            return _manual(f"{prefix}:untrusted_material_move", ("dominant_drivers",))
        return _no_op(f"{prefix}:untrusted_source")
    if movement < transition_threshold:
        return _context(f"{prefix}:context_only", ("dominant_drivers",))
    return _transition(f"{prefix}:transition_threshold", ("dominant_drivers", "scenario_states"))


def _key_level_rule(item: KeyLevelEvidence) -> RuleResult:
    affected = ("invalidation_conditions", "key_levels", "scenario_states")
    if item.confirmation_status is ConfirmationStatus.CONFLICTING:
        return _manual("key_level:conflicting_confirmation", affected)
    if item.event in {"approach", "touch"}:
        return _context(f"key_level:{item.event}", ("key_levels",))
    if item.confirmation_status is not ConfirmationStatus.CONFIRMED:
        return _manual(f"key_level:{item.event}:confirmation_required", affected)
    if item.source_quality not in TRUSTED_MARKET_SOURCES:
        return _manual(f"key_level:{item.event}:trusted_source_required", affected)
    return _transition(f"key_level:{item.event}:confirmed", affected, critical=True)


def _options_rule(item: OptionsRegimeEvidence) -> RuleResult:
    affected = ("dominant_drivers", "key_levels", "scenario_states")
    if item.confirmation_status is ConfirmationStatus.CONFLICTING:
        return _manual("options_regime:conflicting_confirmation", affected)
    if item.event == "gamma_sign_flip":
        significant = bool(item.previous_value and item.current_value and item.previous_value * item.current_value < 0)
    else:
        significant = abs(item.change_pct or 0.0) >= 0.50
    if not significant:
        return _no_op(f"options_regime:{item.event}:below_threshold")
    if item.confirmation_status is not ConfirmationStatus.CONFIRMED:
        return _manual(f"options_regime:{item.event}:confirmation_required", affected)
    if item.source_quality is not SourceQuality.EXCHANGE:
        return _manual(f"options_regime:{item.event}:exchange_source_required", affected)
    return _transition(f"options_regime:{item.event}:confirmed", affected)


def _material_event_rule(item: MaterialEventEvidence) -> RuleResult:
    affected = ("dominant_drivers", "scenario_states", "unresolved_items")
    high_risk = item.risk_level in {"high", "critical"} or item.materiality_score >= 70.0
    if item.confirmation_status is ConfirmationStatus.CONFLICTING:
        return _manual("material_event:conflicting_claims", affected)
    if high_risk and (
        item.confirmation_status is not ConfirmationStatus.CONFIRMED or not item.recompute_eligible
    ):
        return _manual("material_event:high_risk_unconfirmed", affected)
    if item.recompute_eligible and item.materiality_score >= 70.0:
        return _transition("material_event:confirmed_material_event", affected, critical=item.risk_level == "critical")
    if item.materiality_score >= 40.0:
        return _context("material_event:context_only", affected)
    return _no_op("material_event:below_materiality_threshold")


def _figure_rule(item: FigureFactEvidence) -> RuleResult:
    if item.quality_status != "accepted" or not item.has_direct_evidence:
        return _no_op(f"figure_fact:{item.quality_status}:not_accepted")
    return _context("figure_fact:accepted_change", ("dominant_drivers", "key_levels"))


def _no_op(reason: str) -> RuleResult:
    return RuleResult(
        materiality=Materiality.NONE,
        outcome=EvaluationOutcome.IGNORED,
        action=RecommendedAction.NO_OP,
        affected_state_fields=(),
        reasons=(reason,),
    )


def _context(reason: str, affected: tuple[str, ...]) -> RuleResult:
    return RuleResult(
        materiality=Materiality.MEDIUM,
        outcome=EvaluationOutcome.CONTEXT_UPDATE,
        action=RecommendedAction.UPDATE_CONTEXT_ONLY,
        affected_state_fields=affected,
        reasons=(reason,),
    )


def _transition(reason: str, affected: tuple[str, ...], *, critical: bool = False) -> RuleResult:
    return RuleResult(
        materiality=Materiality.CRITICAL if critical else Materiality.HIGH,
        outcome=EvaluationOutcome.TRANSITION_TRIGGER,
        action=RecommendedAction.RUN_TRANSITION_ANALYSIS,
        affected_state_fields=affected,
        reasons=(reason,),
    )


def _manual(reason: str, affected: tuple[str, ...]) -> RuleResult:
    return RuleResult(
        materiality=Materiality.HIGH,
        outcome=EvaluationOutcome.MANUAL_REVIEW,
        action=RecommendedAction.MANUAL_REVIEW,
        affected_state_fields=affected,
        reasons=(reason,),
    )


def _semantic_key(kind: str, *parts: object) -> str:
    return f"{kind}:{json.dumps(parts, ensure_ascii=False, separators=(',', ':'))}"
