"""Deterministic daily-close interpretation of the minimum gold factor set."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.analysis.gold_policy.schemas import FeatureSnapshot, SourceReference, VariableObservation


Direction = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
DirectionalTilt = Literal["bullish", "bearish", "none"]
DecisionQuality = Literal["accepted", "observe", "blocked"]
DriverDirection = Literal["bullish", "bearish"]


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


_MIN_ABSOLUTE_DELTAS = {
    "real_yield": 0.03,
    "breakeven": 0.03,
    "broad_dollar": 0.20,
    "oil": 0.50,
    "xauusd_price_state": 0.20,
}


def evaluate_gold_analysis_policy(
    current: FeatureSnapshot,
    previous: FeatureSnapshot | None,
) -> GoldAnalysisDecision:
    """Evaluate current versus previous snapshots without I/O or inferred text.

    Nominal Treasury yields are intentionally not read: their movement has no
    standalone directional meaning until decomposed into real yield and inflation.
    """

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
        )

    quality_status = _decision_quality(current, previous)
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
        )

    drivers, conflicts = _drivers(current, previous)
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
        confidence=_confidence(direction, bullish, bearish, quality_status),
        quality_status=quality_status,
    )


# Short alias retained for callers that prefer a noun-oriented API.
build_gold_analysis_decision = evaluate_gold_analysis_policy


def _decision_quality(current: FeatureSnapshot, previous: FeatureSnapshot) -> DecisionQuality:
    readiness = {current.data_quality.analysis_readiness, previous.data_quality.analysis_readiness}
    if "blocked" in readiness:
        return "blocked"
    if "observe" in readiness:
        return "observe"
    return "accepted"


def _drivers(current: FeatureSnapshot, previous: FeatureSnapshot) -> tuple[list[PolicyDriver], list[str]]:
    drivers: list[PolicyDriver] = []
    conflicts: list[str] = []

    for factor, current_observation, previous_observation, bullish_on_rise in (
        ("real_yield", current.real10y, previous.real10y, False),
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


def _oil_driver(current: FeatureSnapshot, previous: FeatureSnapshot) -> tuple[PolicyDriver | None, str | None]:
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
    if direction == "mixed":
        return "cross_asset_conflict"
    if direction == "neutral":
        return "stable_cross_asset_inputs"
    primary = (bullish if direction == "bullish" else bearish)[0].factor
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
) -> float:
    evidence_count = len(bullish) + len(bearish)
    if direction in {"neutral", "unavailable"}:
        base = 0.5 if direction == "neutral" else 0.0
    elif direction == "mixed":
        base = min(0.65, 0.35 + evidence_count * 0.05)
    else:
        base = min(0.9, 0.45 + evidence_count * 0.1)
    return round(base * (0.75 if quality_status == "observe" else 1.0), 4)
