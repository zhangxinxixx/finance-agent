"""Deterministic daily-close interpretation of the minimum gold factor set."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.gold_policy.feature_snapshot import feature_snapshot_integrity_valid
from apps.analysis.gold_policy.materiality_policy import evaluate_gold_materiality
from apps.analysis.gold_policy.schemas import (
    AlignmentStatus,
    FeatureSnapshot,
    FeatureSnapshotV2,
    FreshnessStatus,
    QualityStatus,
    SourceReference,
    VariableObservation,
)


Direction = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
DirectionalTilt = Literal["bullish", "bearish", "none"]
DecisionQuality = Literal["accepted", "observe", "blocked"]
DriverDirection = Literal["bullish", "bearish"]


_V2_OUTPUT_QUANTUM = Decimal("0.00000001")
_V2_DIRECTION_THRESHOLD = Decimal("0.25")
_V2_NET_STRENGTH_CAP = Decimal("1.0")
_V2_READINESS_WEIGHTS = {
    "accepted": Decimal("1.0"),
    "observe": Decimal("0.75"),
    "blocked": Decimal("0.0"),
}


class _FrozenPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyDriver(_FrozenPolicyModel):
    """A deterministic, source-backed factor delta used by the policy."""

    factor: Literal["real_yield", "breakeven", "broad_dollar", "oil", "xauusd_price_state"]
    direction: DriverDirection
    current_value: float
    previous_value: float
    delta: float
    rule_code: str = Field(min_length=1)
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)


class Real10YCrossCheckLineage(_FrozenPolicyModel):
    """Non-directional DFII10 evidence, deliberately separate from driver refs."""

    alignment: str
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)


class GoldAnalysisDecision(_FrozenPolicyModel):
    current_snapshot_id: str = Field(min_length=1)
    previous_snapshot_id: str = Field(min_length=1)
    direction: Direction
    direction_tilt: DirectionalTilt
    macro_regime: str = Field(min_length=1)
    market_stage_candidate: str = Field(min_length=1)
    dominant_drivers: tuple[PolicyDriver, ...]
    counter_drivers: tuple[PolicyDriver, ...]
    conflicts: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    quality_status: DecisionQuality
    policy_version: Literal["gold_analysis_policy.v1"] = "gold_analysis_policy.v1"
    real10y_cross_check: Real10YCrossCheckLineage | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class GoldAnalysisFactorContributionV2(_FrozenPolicyModel):
    """A materiality-derived v2 macro contribution with no caller-controlled output."""

    factor: Literal["real10y_estimated", "broad_dollar", "breakeven"]
    current_value: Decimal
    previous_value: Decimal
    delta: Decimal
    direction_sign: Literal[-1, 1]
    materiality_threshold: Decimal = Field(gt=Decimal("0"))
    factor_weight: Decimal = Field(ge=Decimal("0"))
    quality_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    freshness_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    raw_ratio: Decimal = Field(ge=Decimal("0"))
    materiality_bucket: Literal["noise", "small", "material", "large"]
    normalized_move: Decimal = Field(ge=Decimal("0"))
    contribution: Decimal
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_injected_derivations(self) -> "GoldAnalysisFactorContributionV2":
        if self.delta != self.current_value - self.previous_value:
            raise ValueError("delta does not match factor values")
        materiality = evaluate_gold_materiality(
            factor={"real10y_estimated": "real_yield", "broad_dollar": "broad_dollar", "breakeven": "breakeven"}[self.factor],  # type: ignore[arg-type]
            move_magnitude=abs(self.delta),
            direction_sign=self.direction_sign,
            quality_status=("accepted" if self.quality_weight == 1 else "observe" if self.quality_weight == Decimal("0.5") else "blocked"),
            alignment_status=("aligned" if self.quality_weight in {Decimal("1"), Decimal("0.5")} else "misaligned"),
            freshness_status=("fresh" if self.freshness_weight == 1 else "stale" if self.freshness_weight == Decimal("0.5") else "missing"),
        )
        expected = {
            "materiality_threshold": materiality.threshold,
            "factor_weight": materiality.factor_weight,
            "quality_weight": materiality.quality_weight,
            "freshness_weight": materiality.freshness_weight,
            "raw_ratio": materiality.raw_ratio,
            "materiality_bucket": materiality.bucket,
            "normalized_move": materiality.normalized_move,
            "contribution": materiality.contribution,
        }
        for field_name, value in expected.items():
            if getattr(self, field_name) != value:
                raise ValueError(f"{field_name} does not match v2 materiality derivation")
        if len({_source_ref_identity(ref) for ref in self.source_refs}) != len(
            self.source_refs
        ):
            raise ValueError("factor source_refs must be deduplicated")
        return self


class GoldAnalysisDecisionV2(_FrozenPolicyModel):
    """Frozen, hash-addressed macro decision for ``feature_snapshot.v2`` only."""

    current_snapshot_id: str = Field(min_length=1)
    previous_snapshot_id: str = Field(min_length=1)
    direction: Direction
    direction_tilt: DirectionalTilt
    quality_status: DecisionQuality
    factor_contributions: tuple[GoldAnalysisFactorContributionV2, ...]
    bullish_contribution: Decimal = Field(ge=Decimal("0"))
    bearish_contribution: Decimal = Field(ge=Decimal("0"))
    net_contribution: Decimal
    direction_threshold: Decimal = Field(gt=Decimal("0"))
    net_strength_cap: Decimal = Field(gt=Decimal("0"))
    readiness_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    evidence_observed_inputs: int = Field(ge=0, le=20)
    evidence_total_inputs: Literal[20] = 20
    evidence_coverage_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    conflict_share_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    conflicts: tuple[str, ...]
    policy_version: Literal["gold_analysis_policy.v2"] = "gold_analysis_policy.v2"
    materiality_policy_version: Literal["gold_analysis_materiality.v1"] = "gold_analysis_materiality.v1"
    real10y_cross_check: Real10YCrossCheckLineage | None = None
    macro_regime: str = Field(min_length=1)
    market_stage_candidate: str = Field(min_length=1)
    dominant_drivers: tuple[PolicyDriver, ...]
    counter_drivers: tuple[PolicyDriver, ...]
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^gold_analysis_decision\.v2:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _reject_injected_derivations(self) -> "GoldAnalysisDecisionV2":
        bullish = _v2_quantize(sum((item.contribution for item in self.factor_contributions if item.contribution > 0), Decimal("0")))
        bearish = _v2_quantize(-sum((item.contribution for item in self.factor_contributions if item.contribution < 0), Decimal("0")))
        net = _v2_quantize(bullish - bearish)
        total = bullish + bearish
        conflict = _v2_quantize(min(bullish, bearish) / total) if total else Decimal("0")
        confidence = _v2_quantize(
            min(abs(net), self.net_strength_cap)
            * (Decimal("1") - conflict)
            * self.evidence_coverage_ratio
            * self.readiness_weight
        )
        expected_direction, expected_tilt = _v2_direction(bullish, bearish)
        if self.quality_status == "blocked":
            expected_direction, expected_tilt = "unavailable", "none"
        expected_dominant = _v2_legacy_drivers(
            self.factor_contributions, positive=True
        )
        expected_counter = _v2_legacy_drivers(
            self.factor_contributions, positive=False
        )
        expected = {
            "bullish_contribution": bullish,
            "bearish_contribution": bearish,
            "net_contribution": net,
            "direction_threshold": _V2_DIRECTION_THRESHOLD,
            "net_strength_cap": _V2_NET_STRENGTH_CAP,
            "readiness_weight": _V2_READINESS_WEIGHTS[self.quality_status],
            "evidence_coverage_ratio": _v2_quantize(
                Decimal(self.evidence_observed_inputs) / Decimal(self.evidence_total_inputs)
            ),
            "conflict_share_ratio": conflict,
            "confidence": confidence,
            "direction": expected_direction,
            "direction_tilt": expected_tilt,
            "macro_regime": _macro_regime(
                expected_direction, expected_dominant, expected_counter
            ),
            "market_stage_candidate": _market_stage_candidate(expected_direction),
            "dominant_drivers": expected_dominant,
            "counter_drivers": expected_counter,
        }
        for field_name, value in expected.items():
            if getattr(self, field_name) != value:
                raise ValueError(f"{field_name} does not match v2 analysis derivation")
        payload = self.model_dump(mode="json", exclude={"payload_hash", "decision_id"})
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if self.payload_hash != digest or self.decision_id != f"gold_analysis_decision.v2:{digest}":
            raise ValueError("payload_hash or decision_id does not match v2 decision payload")
        return self

_MIN_ABSOLUTE_DELTAS = {
    "real_yield": 0.03,
    "breakeven": 0.03,
    "broad_dollar": 0.20,
    "oil": 0.50,
    "xauusd_price_state": 0.20,
}


FeatureSnapshotContract = FeatureSnapshot | FeatureSnapshotV2


def evaluate_gold_analysis_policy(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
) -> GoldAnalysisDecision | GoldAnalysisDecisionV2:
    """Dispatch immutable snapshots to their version-specific policy contract."""

    if isinstance(current, FeatureSnapshotV2):
        return _evaluate_gold_analysis_policy_v2(current, previous)
    return _evaluate_gold_analysis_policy_v1(current, previous)


def _evaluate_gold_analysis_policy_v1(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
) -> GoldAnalysisDecision:
    """Evaluate current versus previous snapshots without I/O or inferred text.

    Nominal Treasury yields are intentionally not read: their movement has no
    standalone directional meaning until decomposed into real yield and inflation.
    """

    if not feature_snapshot_integrity_valid(current) or (
        previous is not None and not feature_snapshot_integrity_valid(previous)
    ):
        return GoldAnalysisDecision(
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id if previous is not None else "missing",
            direction="unavailable",
            direction_tilt="none",
            macro_regime="snapshot_integrity_invalid",
            market_stage_candidate="unavailable",
            dominant_drivers=(),
            counter_drivers=(),
            conflicts=("FEATURE_SNAPSHOT_DERIVATION_INVALID",),
            confidence=0.0,
            quality_status="blocked",
        )
    if previous is None:
        return GoldAnalysisDecision(
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id="missing",
            direction="unavailable",
            direction_tilt="none",
            macro_regime="previous_snapshot_missing",
            market_stage_candidate="unavailable",
            dominant_drivers=(),
            counter_drivers=(),
            conflicts=("PREVIOUS_FEATURE_SNAPSHOT_MISSING",),
            confidence=0.0,
            quality_status="blocked",
            real10y_cross_check=_real10y_cross_check_lineage(current),
        )
    if previous.as_of > current.as_of:
        return GoldAnalysisDecision(
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            direction="unavailable",
            direction_tilt="none",
            macro_regime="snapshot_order_invalid",
            market_stage_candidate="unavailable",
            dominant_drivers=(),
            counter_drivers=(),
            conflicts=("PREVIOUS_SNAPSHOT_AFTER_CURRENT",),
            confidence=0.0,
            quality_status="blocked",
            real10y_cross_check=_real10y_cross_check_lineage(current),
        )

    cross_check_codes = _real10y_cross_check_codes(current, previous)
    quality_status = _decision_quality(current, previous, cross_check_codes=cross_check_codes)
    if quality_status == "blocked":
        return GoldAnalysisDecision(
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            direction="unavailable",
            direction_tilt="none",
            macro_regime="data_blocked",
            market_stage_candidate="unavailable",
            dominant_drivers=(),
            counter_drivers=(),
            conflicts=("ANALYSIS_INPUT_READINESS_BLOCKED",),
            confidence=0.0,
            quality_status="blocked",
            real10y_cross_check=_real10y_cross_check_lineage(current),
        )

    drivers, conflicts = _drivers(current, previous)
    conflicts.extend(cross_check_codes)
    bullish = tuple(driver for driver in drivers if driver.direction == "bullish")
    bearish = tuple(driver for driver in drivers if driver.direction == "bearish")
    direction, tilt = _direction(bullish, bearish)

    if direction == "bullish":
        dominant, counter = bullish, bearish
    elif direction == "bearish":
        dominant, counter = bearish, bullish
    else:
        dominant, counter = bullish, bearish

    return GoldAnalysisDecision(
        current_snapshot_id=current.snapshot_id,
        previous_snapshot_id=previous.snapshot_id,
        direction=direction,
        direction_tilt=tilt,
        macro_regime=_macro_regime(direction, bullish, bearish),
        market_stage_candidate=_market_stage_candidate(direction),
        dominant_drivers=dominant,
        counter_drivers=counter,
        conflicts=tuple(conflicts),
        confidence=_confidence(
            direction,
            bullish,
            bearish,
            quality_status,
            cross_check_degraded=bool(cross_check_codes),
        ),
        quality_status=quality_status,
        real10y_cross_check=_real10y_cross_check_lineage(current),
    )


def _evaluate_gold_analysis_policy_v2(
    current: FeatureSnapshotV2,
    previous: FeatureSnapshotContract | None,
) -> GoldAnalysisDecisionV2:
    """Evaluate the v2 three-factor macro contract without price contribution."""

    previous_v2 = previous if isinstance(previous, FeatureSnapshotV2) else None
    if not feature_snapshot_integrity_valid(current) or (
        previous_v2 is not None and not feature_snapshot_integrity_valid(previous_v2)
    ):
        return _build_v2_decision(
            current=current,
            previous=previous_v2,
            quality_status="blocked",
            factors=(),
            observed_inputs=0,
            conflicts=("FEATURE_SNAPSHOT_DERIVATION_INVALID",),
        )
    if previous_v2 is None:
        return _build_v2_decision(
            current=current,
            previous=None,
            quality_status="blocked",
            factors=(),
            observed_inputs=0,
            conflicts=(("PREVIOUS_FEATURE_SNAPSHOT_MISSING",) if previous is None else ("FEATURE_SNAPSHOT_SCHEMA_TRANSITION_NO_DELTA",)),
        )
    if previous_v2.as_of > current.as_of:
        return _build_v2_decision(
            current=current,
            previous=previous_v2,
            quality_status="blocked",
            factors=(),
            observed_inputs=0,
            conflicts=("PREVIOUS_SNAPSHOT_AFTER_CURRENT",),
        )

    quality_status, quality_conflicts = _v2_quality(current, previous_v2)
    observed_inputs = _v2_evidence_observed_inputs(current, previous_v2)
    if quality_status == "blocked":
        return _build_v2_decision(
            current=current,
            previous=previous_v2,
            quality_status=quality_status,
            factors=(),
            observed_inputs=observed_inputs,
            conflicts=quality_conflicts,
        )
    factors = (
        _v2_factor("real10y_estimated", current.real10y_estimated, previous_v2.real10y_estimated, bullish_on_rise=False),
        _v2_factor("broad_dollar", current.broad_dollar, previous_v2.broad_dollar, bullish_on_rise=False),
        _v2_factor("breakeven", current.t10yie, previous_v2.t10yie, bullish_on_rise=True),
    )
    return _build_v2_decision(
        current=current,
        previous=previous_v2,
        quality_status=quality_status,
        factors=factors,
        observed_inputs=observed_inputs,
        conflicts=quality_conflicts,
    )


def _v2_worst_quality(
    current: VariableObservation, previous: VariableObservation
) -> QualityStatus:
    values = {current.quality_status, previous.quality_status}
    if "blocked" in values:
        return "blocked"
    if "observe" in values:
        return "observe"
    return "accepted"


def _v2_worst_alignment(
    current: VariableObservation, previous: VariableObservation
) -> AlignmentStatus:
    values = {current.alignment_status, previous.alignment_status}
    if "misaligned" in values:
        return "misaligned"
    if "unknown" in values:
        return "unknown"
    return "aligned"


def _v2_worst_freshness(
    current: VariableObservation, previous: VariableObservation
) -> FreshnessStatus:
    values = {current.freshness_status, previous.freshness_status}
    if "missing" in values:
        return "missing"
    if "stale" in values:
        return "stale"
    return "fresh"


def _source_ref_identity(ref: SourceReference) -> tuple[object, object, object]:
    return ref.source, ref.reference, ref.retrieved_at


def _v2_factor(
    factor: Literal["real10y_estimated", "broad_dollar", "breakeven"],
    current: VariableObservation,
    previous: VariableObservation,
    *,
    bullish_on_rise: bool,
) -> GoldAnalysisFactorContributionV2:
    current_value = Decimal(str(current.value)) if current.value is not None else Decimal("0")
    previous_value = Decimal(str(previous.value)) if previous.value is not None else Decimal("0")
    delta = current_value - previous_value
    direction_sign = 1 if ((delta > 0) == bullish_on_rise) else -1
    materiality = evaluate_gold_materiality(
        factor={"real10y_estimated": "real_yield", "broad_dollar": "broad_dollar", "breakeven": "breakeven"}[factor],  # type: ignore[arg-type]
        move_magnitude=abs(delta),
        direction_sign=direction_sign,
        quality_status=_v2_worst_quality(current, previous),
        alignment_status=_v2_worst_alignment(current, previous),
        freshness_status=_v2_worst_freshness(current, previous),
    )
    return GoldAnalysisFactorContributionV2(
        factor=factor,
        current_value=current_value,
        previous_value=previous_value,
        delta=delta,
        direction_sign=direction_sign,
        materiality_threshold=materiality.threshold,
        factor_weight=materiality.factor_weight,
        quality_weight=materiality.quality_weight,
        freshness_weight=materiality.freshness_weight,
        raw_ratio=materiality.raw_ratio,
        materiality_bucket=materiality.bucket,
        normalized_move=materiality.normalized_move,
        contribution=materiality.contribution,
        source_refs=_combined_refs(current, previous),
    )


def _v2_quality(current: FeatureSnapshotV2, previous: FeatureSnapshotV2) -> tuple[DecisionQuality, tuple[str, ...]]:
    readiness = {current.data_quality.analysis_readiness, previous.data_quality.analysis_readiness}
    conflicts: list[str] = []
    if "blocked" in readiness:
        return "blocked", ("ANALYSIS_INPUT_READINESS_BLOCKED",)
    if "observe" in readiness:
        conflicts.append("ANALYSIS_INPUT_READINESS_OBSERVE")
    for snapshot in (previous, current):
        if snapshot.real10y_alignment == "diverged":
            conflicts.append("REAL10Y_BASIS_DIVERGED")
        elif snapshot.real10y_alignment == "unavailable":
            conflicts.append("REAL10Y_DIRECT_CROSS_CHECK_UNAVAILABLE")
    return ("observe" if conflicts else "accepted"), tuple(dict.fromkeys(conflicts))


def _v2_evidence_observed_inputs(current: FeatureSnapshotV2, previous: FeatureSnapshotV2) -> int:
    inputs = (
        "real10y_estimated",
        "broad_dollar",
        "t10yie",
        "gc_futures",
        "us02y",
        "us30y",
        "wti",
        "brent",
        "etf_flow",
        "cot",
    )
    usable_count = sum(
        _usable(getattr(snapshot, name))
        for snapshot in (current, previous)
        for name in inputs
    )
    return usable_count


def _v2_direction(bullish: Decimal, bearish: Decimal) -> tuple[Direction, DirectionalTilt]:
    net = bullish - bearish
    if bullish and bearish and abs(net) < _V2_DIRECTION_THRESHOLD:
        return "mixed", "bullish" if net > 0 else "bearish" if net < 0 else "none"
    if net >= _V2_DIRECTION_THRESHOLD:
        return "bullish", "bullish"
    if net <= -_V2_DIRECTION_THRESHOLD:
        return "bearish", "bearish"
    return "neutral", "none"


def _v2_quantize(value: Decimal) -> Decimal:
    return value.quantize(_V2_OUTPUT_QUANTUM, rounding=ROUND_HALF_EVEN)


def _build_v2_decision(
    *,
    current: FeatureSnapshotV2,
    previous: FeatureSnapshotV2 | None,
    quality_status: DecisionQuality,
    factors: tuple[GoldAnalysisFactorContributionV2, ...],
    observed_inputs: int,
    conflicts: tuple[str, ...],
) -> GoldAnalysisDecisionV2:
    bullish = _v2_quantize(sum((item.contribution for item in factors if item.contribution > 0), Decimal("0")))
    bearish = _v2_quantize(-sum((item.contribution for item in factors if item.contribution < 0), Decimal("0")))
    direction, tilt = _v2_direction(bullish, bearish)
    if quality_status == "blocked":
        direction, tilt, bullish, bearish, observed_inputs = "unavailable", "none", Decimal("0"), Decimal("0"), 0
    net = _v2_quantize(bullish - bearish)
    total = bullish + bearish
    conflict_share = _v2_quantize(min(bullish, bearish) / total) if total else Decimal("0")
    readiness_weight = _V2_READINESS_WEIGHTS[quality_status]
    coverage = _v2_quantize(Decimal(observed_inputs) / Decimal(20))
    confidence = _v2_quantize(min(abs(net), _V2_NET_STRENGTH_CAP) * (Decimal("1") - conflict_share) * coverage * readiness_weight)
    dominant = _v2_legacy_drivers(factors, positive=True)
    counter = _v2_legacy_drivers(factors, positive=False)
    payload = {
        "current_snapshot_id": current.snapshot_id,
        "previous_snapshot_id": previous.snapshot_id if previous else "missing",
        "direction": direction,
        "direction_tilt": tilt,
        "quality_status": quality_status,
        "factor_contributions": factors,
        "bullish_contribution": bullish,
        "bearish_contribution": bearish,
        "net_contribution": net,
        "direction_threshold": _V2_DIRECTION_THRESHOLD,
        "net_strength_cap": _V2_NET_STRENGTH_CAP,
        "readiness_weight": readiness_weight,
        "evidence_observed_inputs": observed_inputs,
        "evidence_total_inputs": 20,
        "evidence_coverage_ratio": coverage,
        "conflict_share_ratio": conflict_share,
        "confidence": confidence,
        "conflicts": conflicts,
        "real10y_cross_check": _real10y_cross_check_lineage(current),
        "macro_regime": _macro_regime(direction, dominant, counter),
        "market_stage_candidate": _market_stage_candidate(direction),
        "dominant_drivers": dominant,
        "counter_drivers": counter,
    }
    canonical = json.dumps(
        GoldAnalysisDecisionV2.model_construct(
            **payload, payload_hash="", decision_id="gold_analysis_decision.v2:" + "0" * 64
        ).model_dump(mode="json", exclude={"payload_hash", "decision_id"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return GoldAnalysisDecisionV2(**payload, payload_hash=digest, decision_id=f"gold_analysis_decision.v2:{digest}")


def _v2_legacy_drivers(
    factors: tuple[GoldAnalysisFactorContributionV2, ...], *, positive: bool
) -> tuple[PolicyDriver, ...]:
    drivers: list[PolicyDriver] = []
    for item in factors:
        if (item.contribution > 0) != positive or not item.contribution:
            continue
        factor = {"real10y_estimated": "real_yield", "broad_dollar": "broad_dollar", "breakeven": "breakeven"}[item.factor]
        direction: DriverDirection = "bullish" if positive else "bearish"
        drivers.append(PolicyDriver(
            factor=factor,  # type: ignore[arg-type]
            direction=direction,
            current_value=float(item.current_value),
            previous_value=float(item.previous_value),
            delta=float(item.delta),
            rule_code=f"V2_{item.factor.upper()}_{direction.upper()}",
            source_refs=item.source_refs,
        ))
    return tuple(drivers)


# Short alias retained for callers that prefer a noun-oriented API.
build_gold_analysis_decision = evaluate_gold_analysis_policy


def _decision_quality(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract,
    *,
    cross_check_codes: tuple[str, ...] = (),
) -> DecisionQuality:
    readiness = {current.data_quality.analysis_readiness, previous.data_quality.analysis_readiness}
    if "blocked" in readiness:
        return "blocked"
    if "observe" in readiness or cross_check_codes:
        return "observe"
    return "accepted"


def _drivers(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[list[PolicyDriver], list[str]]:
    drivers: list[PolicyDriver] = []
    conflicts: list[str] = []

    real_yield_pair = _real10y_directional_pair(current, previous)
    if real_yield_pair is None:
        conflicts.append("REAL10Y_SCHEMA_TRANSITION_NO_DELTA")
    else:
        driver = _single_factor_driver("real_yield", *real_yield_pair, bullish_on_rise=False)
        if driver is not None:
            drivers.append(driver)

    for factor, current_observation, previous_observation, bullish_on_rise in (
        ("breakeven", current.t10yie, previous.t10yie, True),
        ("broad_dollar", current.broad_dollar, previous.broad_dollar, False),
        ("xauusd_price_state", current.xauusd_spot, previous.xauusd_spot, True),
    ):
        driver = _single_factor_driver(
            factor,
            current_observation,
            previous_observation,
            bullish_on_rise=bullish_on_rise,
        )
        if driver is not None:
            drivers.append(driver)

    oil_driver, oil_conflict = _oil_driver(current, previous)
    if oil_driver is not None:
        drivers.append(oil_driver)
    if oil_conflict is not None:
        conflicts.append(oil_conflict)
    return drivers, conflicts


def _single_factor_driver(
    factor: Literal["real_yield", "breakeven", "broad_dollar", "xauusd_price_state"],
    current: VariableObservation,
    previous: VariableObservation,
    *,
    bullish_on_rise: bool,
) -> PolicyDriver | None:
    if not _usable(current) or not _usable(previous):
        return None
    assert current.value is not None and previous.value is not None
    delta = current.value - previous.value
    if abs(delta) < _MIN_ABSOLUTE_DELTAS[factor]:
        return None
    is_bullish = (delta > 0) == bullish_on_rise
    direction: DriverDirection = "bullish" if is_bullish else "bearish"
    sign = "RISE" if delta > 0 else "FALL"
    return PolicyDriver(
        factor=factor,
        direction=direction,
        current_value=current.value,
        previous_value=previous.value,
        delta=delta,
        rule_code=f"{factor.upper()}_{sign}_{direction.upper()}",
        source_refs=_combined_refs(current, previous),
    )


def _oil_driver(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[PolicyDriver | None, str | None]:
    observations = (current.wti, current.brent, previous.wti, previous.brent)
    if not all(_usable(observation) for observation in observations):
        return None, None
    assert all(observation.value is not None for observation in observations)
    wti_delta = current.wti.value - previous.wti.value  # type: ignore[operator]
    brent_delta = current.brent.value - previous.brent.value  # type: ignore[operator]
    if wti_delta * brent_delta < 0:
        return None, "OIL_BENCHMARKS_DIVERGED"
    if (
        abs(wti_delta) < _MIN_ABSOLUTE_DELTAS["oil"]
        or abs(brent_delta) < _MIN_ABSOLUTE_DELTAS["oil"]
    ):
        return None, None
    delta = (wti_delta + brent_delta) / 2
    direction: DriverDirection = "bullish" if delta > 0 else "bearish"
    return (
        PolicyDriver(
            factor="oil",
            direction=direction,
            current_value=(current.wti.value + current.brent.value) / 2,  # type: ignore[operator]
            previous_value=(previous.wti.value + previous.brent.value) / 2,  # type: ignore[operator]
            delta=delta,
            rule_code=f"OIL_INFLATION_PATH_{'RISE' if delta > 0 else 'FALL'}_{direction.upper()}",
            source_refs=_combined_refs(current.wti, current.brent, previous.wti, previous.brent),
        ),
        None,
    )


def _usable(observation: VariableObservation) -> bool:
    return (
        observation.value is not None
        and observation.freshness_status == "fresh"
        and observation.quality_status == "accepted"
        and observation.alignment_status == "aligned"
    )


def _combined_refs(*observations: VariableObservation) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = []
    seen: set[tuple[str, str, object]] = set()
    for observation in observations:
        for source_ref in observation.source_refs:
            identity = (source_ref.source, source_ref.reference, source_ref.retrieved_at)
            if identity not in seen:
                seen.add(identity)
                refs.append(source_ref)
    return tuple(refs)


def _direction(
    bullish: tuple[PolicyDriver, ...], bearish: tuple[PolicyDriver, ...]
) -> tuple[Direction, DirectionalTilt]:
    if bullish and bearish:
        if len(bullish) > len(bearish):
            return "mixed", "bullish"
        if len(bearish) > len(bullish):
            return "mixed", "bearish"
        return "mixed", "none"
    if bullish:
        return "bullish", "bullish"
    if bearish:
        return "bearish", "bearish"
    return "neutral", "none"


def _macro_regime(
    direction: Direction, bullish: tuple[PolicyDriver, ...], bearish: tuple[PolicyDriver, ...]
) -> str:
    if direction == "unavailable":
        return "unavailable"
    if direction == "mixed":
        return "cross_asset_conflict"
    if direction == "neutral":
        return "stable_cross_asset_inputs"
    directional = bullish if direction == "bullish" else bearish
    if not directional:
        return "directional_evidence_unavailable"
    primary = directional[0].factor
    return f"{primary}_{direction}"


def _market_stage_candidate(direction: Direction) -> str:
    return {
        "bullish": "upside_pressure",
        "bearish": "downside_pressure",
        "mixed": "direction_decision",
        "neutral": "range",
        "unavailable": "unavailable",
    }[direction]


def _confidence(
    direction: Direction,
    bullish: tuple[PolicyDriver, ...],
    bearish: tuple[PolicyDriver, ...],
    quality_status: DecisionQuality,
    *,
    cross_check_degraded: bool = False,
) -> float:
    evidence_count = len(bullish) + len(bearish)
    if direction in {"neutral", "unavailable"}:
        base = 0.5 if direction == "neutral" else 0.0
    elif direction == "mixed":
        base = min(0.65, 0.35 + evidence_count * 0.05)
    else:
        base = min(0.9, 0.45 + evidence_count * 0.1)
    multiplier = 0.75 if quality_status == "observe" else 1.0
    if cross_check_degraded:
        multiplier *= 0.9
    return round(base * multiplier, 4)


def _real10y_directional(snapshot: FeatureSnapshotContract) -> VariableObservation:
    """Use DFII10 only in v1; v2 directional semantics are estimated real yield."""

    return snapshot.real10y_estimated if isinstance(snapshot, FeatureSnapshotV2) else snapshot.real10y


def _real10y_directional_pair(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[VariableObservation, VariableObservation] | None:
    if isinstance(current, FeatureSnapshotV2) != isinstance(previous, FeatureSnapshotV2):
        return None
    return _real10y_directional(current), _real10y_directional(previous)


def _real10y_cross_check_lineage(
    snapshot: FeatureSnapshotContract,
) -> Real10YCrossCheckLineage | None:
    if not isinstance(snapshot, FeatureSnapshotV2):
        return None
    return Real10YCrossCheckLineage(
        alignment=snapshot.real10y_alignment,
        source_refs=snapshot.real10y_direct.source_refs,
    )


def _real10y_cross_check_codes(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[str, ...]:
    codes: list[str] = []
    for snapshot in (previous, current):
        if not isinstance(snapshot, FeatureSnapshotV2):
            continue
        if snapshot.real10y_alignment == "diverged":
            codes.append("REAL10Y_BASIS_DIVERGED")
        elif snapshot.real10y_alignment == "unavailable":
            codes.append("REAL10Y_DIRECT_CROSS_CHECK_UNAVAILABLE")
    return tuple(dict.fromkeys(codes))
