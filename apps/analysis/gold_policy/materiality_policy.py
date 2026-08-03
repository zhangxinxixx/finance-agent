"""Pure Decimal materiality and contribution contract for Gold Policy v2."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MaterialityFactor = Literal[
    "real_yield",
    "broad_dollar",
    "breakeven",
    "oil",
    "event_reaction",
    "xauusd_return",
]
MaterialityBucket = Literal["noise", "small", "material", "large"]
QualityStatus = Literal["accepted", "observe", "blocked"]
AlignmentStatus = Literal["aligned", "unknown", "misaligned"]
FreshnessStatus = Literal["fresh", "stale", "missing"]
DirectionSign = Literal[-1, 1]


_THRESHOLDS: dict[MaterialityFactor, Decimal] = {
    "real_yield": Decimal("0.03"),
    "broad_dollar": Decimal("0.20"),
    "breakeven": Decimal("0.03"),
    "oil": Decimal("0.50"),
    "event_reaction": Decimal("0.20"),
    "xauusd_return": Decimal("0.10"),
}
_FACTOR_WEIGHTS: dict[MaterialityFactor, Decimal] = {
    "real_yield": Decimal("0.40"),
    "broad_dollar": Decimal("0.35"),
    "breakeven": Decimal("0.25"),
    "oil": Decimal("0.15"),
    "event_reaction": Decimal("0.40"),
    # Price materiality is useful for move classification, but price cannot
    # contribute to the macro-direction score.
    "xauusd_return": Decimal("0"),
}
_NORMALIZATION_CAP = Decimal("2")
_HALF = Decimal("0.5")
_ONE = Decimal("1")
_CONTRIBUTION_QUANTUM = Decimal("0.00000001")


class GoldMaterialityDecision(BaseModel):
    """Immutable result with every policy constant serialized for audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["gold_materiality_policy.v1"] = (
        "gold_materiality_policy.v1"
    )
    factor: MaterialityFactor
    move_magnitude: Decimal = Field(strict=True, ge=Decimal("0"))
    direction_sign: DirectionSign
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    freshness_status: FreshnessStatus
    threshold: Decimal = Field(strict=True, gt=Decimal("0"))
    factor_weight: Decimal = Field(strict=True, ge=Decimal("0"))
    quality_weight: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    freshness_weight: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    normalization_cap: Decimal = Field(strict=True, gt=Decimal("0"))
    raw_ratio: Decimal = Field(strict=True, ge=Decimal("0"))
    bucket: MaterialityBucket
    normalized_move: Decimal = Field(strict=True, ge=Decimal("0"))
    contribution: Decimal = Field(strict=True)

    @model_validator(mode="after")
    def _reject_injected_derivations(self) -> "GoldMaterialityDecision":
        expected = _derive(
            factor=self.factor,
            move_magnitude=self.move_magnitude,
            direction_sign=self.direction_sign,
            quality_status=self.quality_status,
            alignment_status=self.alignment_status,
            freshness_status=self.freshness_status,
        )
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(
                    f"{field_name} does not match gold materiality policy derivation"
                )
        return self


def evaluate_gold_materiality(
    *,
    factor: MaterialityFactor,
    move_magnitude: Decimal,
    direction_sign: DirectionSign,
    quality_status: QualityStatus,
    alignment_status: AlignmentStatus,
    freshness_status: FreshnessStatus,
) -> GoldMaterialityDecision:
    """Evaluate one factor without floats, I/O, clocks, or mutable state."""

    if not isinstance(move_magnitude, Decimal):
        raise TypeError("move_magnitude must be a Decimal")
    if factor not in _THRESHOLDS:
        raise ValueError("unsupported materiality factor")
    if direction_sign not in {-1, 1}:
        raise ValueError("direction_sign must be -1 or 1")
    if quality_status not in {"accepted", "observe", "blocked"}:
        raise ValueError("unsupported quality_status")
    if alignment_status not in {"aligned", "unknown", "misaligned"}:
        raise ValueError("unsupported alignment_status")
    if freshness_status not in {"fresh", "stale", "missing"}:
        raise ValueError("unsupported freshness_status")
    derived = _derive(
        factor=factor,
        move_magnitude=move_magnitude,
        direction_sign=direction_sign,
        quality_status=quality_status,
        alignment_status=alignment_status,
        freshness_status=freshness_status,
    )
    return GoldMaterialityDecision(
        factor=factor,
        move_magnitude=move_magnitude,
        direction_sign=direction_sign,
        quality_status=quality_status,
        alignment_status=alignment_status,
        freshness_status=freshness_status,
        **derived,
    )


# Noun-oriented alias for callers that treat pure policies as builders.
build_gold_materiality_decision = evaluate_gold_materiality


def _derive(
    *,
    factor: MaterialityFactor,
    move_magnitude: Decimal,
    direction_sign: DirectionSign,
    quality_status: QualityStatus,
    alignment_status: AlignmentStatus,
    freshness_status: FreshnessStatus,
) -> dict[str, Decimal | MaterialityBucket]:
    if not isinstance(move_magnitude, Decimal):
        raise TypeError("move_magnitude must be a Decimal")
    if not move_magnitude.is_finite() or move_magnitude < 0:
        raise ValueError("move_magnitude must be a finite non-negative Decimal")

    threshold = _THRESHOLDS[factor]
    factor_weight = _FACTOR_WEIGHTS[factor]
    quality_weight = _quality_weight(quality_status, alignment_status)
    freshness_weight = {
        "fresh": Decimal("1"),
        "stale": Decimal("0.5"),
        "missing": Decimal("0"),
    }[freshness_status]
    with localcontext() as context:
        context.prec = 50
        raw_ratio = move_magnitude / threshold
        bucket = _bucket(raw_ratio)
        normalized_move = (
            Decimal("0")
            if bucket in {"noise", "small"}
            else min(raw_ratio, _NORMALIZATION_CAP)
        )
        contribution = (
            Decimal(direction_sign)
            * normalized_move
            * factor_weight
            * quality_weight
            * freshness_weight
        ).quantize(_CONTRIBUTION_QUANTUM, rounding=ROUND_HALF_EVEN)
    return {
        "threshold": threshold,
        "factor_weight": factor_weight,
        "quality_weight": quality_weight,
        "freshness_weight": freshness_weight,
        "normalization_cap": _NORMALIZATION_CAP,
        "raw_ratio": raw_ratio,
        "bucket": bucket,
        "normalized_move": normalized_move,
        "contribution": contribution,
    }


def _bucket(raw_ratio: Decimal) -> MaterialityBucket:
    if raw_ratio < _HALF:
        return "noise"
    if raw_ratio < _ONE:
        return "small"
    if raw_ratio < _NORMALIZATION_CAP:
        return "material"
    return "large"


def _quality_weight(
    quality_status: QualityStatus,
    alignment_status: AlignmentStatus,
) -> Decimal:
    if quality_status == "blocked" or alignment_status == "misaligned":
        return Decimal("0")
    if quality_status == "observe" or alignment_status == "unknown":
        return Decimal("0.5")
    return Decimal("1")


__all__ = [
    "GoldMaterialityDecision",
    "build_gold_materiality_decision",
    "evaluate_gold_materiality",
]
