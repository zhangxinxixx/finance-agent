"""Deterministic daily XAUUSD price-attribution policy.

The policy intentionally makes no claim for data that is unavailable or whose
cross-asset evidence is incomplete.  It consumes only two immutable feature
snapshots and returns an immutable, audit-ready attribution record.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.gold_policy.feature_snapshot import feature_snapshot_integrity_valid
from apps.analysis.gold_policy.materiality_policy import evaluate_gold_materiality
from apps.analysis.gold_policy.schemas import (
    FeatureSnapshot,
    FeatureSnapshotV2,
    SourceReference,
    VariableObservation,
)


PriceMove = Literal["up", "down", "flat", "volatile_mixed", "unavailable"]
AttributionStatus = Literal[
    "confirmed_event",
    "cross_asset_consistent",
    "historical_model_inference",
    "agent_inference",
    "unconfirmed",
]
DriverDirection = Literal["supports_up", "supports_down"]

_FLAT_RETURN_PCT = 0.05
FeatureSnapshotContract = FeatureSnapshot | FeatureSnapshotV2


def _source_ref_key(ref: SourceReference) -> tuple[object, object, object]:
    return ref.source, ref.reference, ref.retrieved_at


class _FrozenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttributionDriver(_FrozenOutput):
    """One structured, rule-derived potential price driver."""

    factor: Literal["broad_dollar", "real_yield", "breakeven", "oil_inflation_path", "official_event"]
    direction: DriverDirection
    rule_code: str = Field(min_length=1)
    previous_value: float | None = None
    current_value: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    previous_as_of: str | None = None
    current_as_of: str
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _source_refs_are_unique(self) -> "AttributionDriver":
        if len({_source_ref_key(ref) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("driver source_refs must be deduplicated")
        return self


class GoldPriceAttribution(_FrozenOutput):
    policy_version: Literal["gold_price_attribution.v1"] = "gold_price_attribution.v1"
    current_snapshot_id: str = Field(min_length=1)
    previous_snapshot_id: str = Field(min_length=1)
    price_move: PriceMove
    return_pct: float
    explained_ratio: float = Field(ge=0.0, le=1.0)
    primary_drivers: tuple[AttributionDriver, ...]
    secondary_drivers: tuple[AttributionDriver, ...]
    counter_drivers: tuple[AttributionDriver, ...]
    unexplained_component: float = Field(ge=0.0, le=1.0)
    attribution_status: AttributionStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_accounting_and_references(self) -> "GoldPriceAttribution":
        if abs(self.explained_ratio + self.unexplained_component - 1.0) > 1e-9:
            raise ValueError("explained_ratio and unexplained_component must sum to one")
        if len({_source_ref_key(ref) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("source_refs must be deduplicated")
        return self


def attribute_gold_price(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
) -> GoldPriceAttribution | "GoldPriceAttributionV2":
    """Dispatch versioned snapshots without changing the v1 policy path."""

    if isinstance(current, FeatureSnapshotV2):
        return GoldPriceAttributionV2.evaluate(current, previous)
    return _attribute_gold_price_v1(current, previous)


def _attribute_gold_price_v1(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract | None,
) -> GoldPriceAttribution:
    """Attribute the XAUUSD close move using only accepted, aligned inputs."""

    if not feature_snapshot_integrity_valid(current) or (
        previous is not None and not feature_snapshot_integrity_valid(previous)
    ):
        refs = current.xauusd_spot.source_refs
        if previous is not None:
            refs = (*previous.xauusd_spot.source_refs, *refs)
        return _result(
            price_move="unavailable",
            return_pct=0.0,
            explained_ratio=0.0,
            primary=(),
            secondary=(),
            counter=(),
            status="unconfirmed",
            source_refs=_dedupe_refs(refs),
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id if previous is not None else "missing",
            reason_codes=("FEATURE_SNAPSHOT_DERIVATION_INVALID",),
        )
    if previous is None:
        return _result(
            price_move="unavailable",
            return_pct=0.0,
            explained_ratio=0.0,
            primary=(),
            secondary=(),
            counter=(),
            status="unconfirmed",
            source_refs=_dedupe_refs(current.xauusd_spot.source_refs),
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id="missing",
            reason_codes=("PREVIOUS_FEATURE_SNAPSHOT_MISSING",),
        )
    if previous.as_of > current.as_of:
        return _result(
            price_move="unavailable",
            return_pct=0.0,
            explained_ratio=0.0,
            primary=(),
            secondary=(),
            counter=(),
            status="unconfirmed",
            source_refs=_dedupe_refs((*previous.xauusd_spot.source_refs, *current.xauusd_spot.source_refs)),
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            reason_codes=("PREVIOUS_SNAPSHOT_AFTER_CURRENT",),
        )

    price_move, return_pct = _price_move(current, previous)
    output_refs = _dedupe_refs((*previous.xauusd_spot.source_refs, *current.xauusd_spot.source_refs))
    readiness_reasons = (
        *_real10y_schema_transition_reason(current, previous),
        *_event_attribution_readiness_reasons(current),
    )

    if (
        current.data_quality.analysis_readiness == "blocked"
        or previous.data_quality.analysis_readiness == "blocked"
    ):
        return _result(
            price_move=price_move,
            return_pct=return_pct,
            explained_ratio=0.0,
            primary=(),
            secondary=(),
            counter=(),
            status="unconfirmed",
            source_refs=output_refs,
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            reason_codes=readiness_reasons,
        )

    factor_drivers = tuple(
        driver
        for driver in (
            _variable_driver("broad_dollar", previous.broad_dollar, current.broad_dollar, inverse=True),
            _real10y_attribution_driver(previous, current),
            _variable_driver("breakeven", previous.t10yie, current.t10yie, inverse=False),
            _oil_driver(previous, current),
        )
        if driver is not None
    )
    event_drivers = _confirmed_event_drivers(current, previous, price_move)
    output_refs = _dedupe_refs(
        (*output_refs, *(ref for driver in (*factor_drivers, *event_drivers) for ref in driver.source_refs))
    )

    if price_move in {"flat", "volatile_mixed"}:
        return _result(
            price_move=price_move,
            return_pct=return_pct,
            explained_ratio=0.0,
            primary=(),
            secondary=event_drivers,
            counter=(),
            status="unconfirmed",
            source_refs=output_refs,
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            reason_codes=readiness_reasons,
        )

    expected_direction = "supports_up" if price_move == "up" else "supports_down"
    supporting = tuple(driver for driver in factor_drivers if driver.direction == expected_direction)
    counter = tuple(driver for driver in factor_drivers if driver.direction != expected_direction)

    # A valid official reaction window is formal event evidence, not a parsed
    # news headline.  It can confirm a directional close only after the close.
    if event_drivers and not counter:
        return _result(
            price_move=price_move,
            return_pct=return_pct,
            explained_ratio=0.9,
            primary=event_drivers,
            secondary=supporting,
            counter=(),
            status="confirmed_event",
            source_refs=output_refs,
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            reason_codes=readiness_reasons,
        )

    if len(supporting) >= 2 and not counter:
        ratio = 0.75 if len(supporting) == 2 else 0.9
        return _result(
            price_move=price_move,
            return_pct=return_pct,
            explained_ratio=ratio,
            primary=supporting,
            secondary=(),
            counter=(),
            status="cross_asset_consistent",
            source_refs=output_refs,
            current_snapshot_id=current.snapshot_id,
            previous_snapshot_id=previous.snapshot_id,
            reason_codes=readiness_reasons,
        )

    # One matching factor, or any conflicting factor, is deliberately not
    # promoted into a causal story.
    return _result(
        price_move=price_move,
        return_pct=return_pct,
        explained_ratio=0.0,
        primary=(),
        secondary=supporting,
        counter=counter,
        status="unconfirmed",
        source_refs=output_refs,
        current_snapshot_id=current.snapshot_id,
        previous_snapshot_id=previous.snapshot_id,
        reason_codes=readiness_reasons,
    )


def _price_move(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[PriceMove, float]:
    current_value = current.xauusd_spot.value
    previous_value = previous.xauusd_spot.value
    if current_value is None or previous_value is None or previous_value == 0:
        return "flat", 0.0
    return_pct = round((current_value - previous_value) / previous_value * 100.0, 8)
    if abs(return_pct) < _FLAT_RETURN_PCT:
        return "flat", return_pct
    return ("up" if return_pct > 0 else "down"), return_pct


def _variable_driver(
    factor: Literal["broad_dollar", "real_yield", "breakeven"],
    previous: VariableObservation,
    current: VariableObservation,
    *,
    inverse: bool,
) -> AttributionDriver | None:
    if not _usable(previous) or not _usable(current) or previous.value == current.value:
        return None
    delta = current.value - previous.value
    supports_up = delta < 0 if inverse else delta > 0
    return AttributionDriver(
        factor=factor,
        direction="supports_up" if supports_up else "supports_down",
        rule_code=f"ATTR_{factor.upper()}_{'INVERSE' if inverse else 'DIRECT'}_V1",
        previous_value=previous.value,
        current_value=current.value,
        delta=round(delta, 8),
        delta_pct=_delta_pct(previous.value, current.value),
        previous_as_of=previous.as_of.isoformat(),
        current_as_of=current.as_of.isoformat(),
        source_refs=_dedupe_refs((*previous.source_refs, *current.source_refs)),
    )


def _oil_driver(
    previous: FeatureSnapshotContract, current: FeatureSnapshotContract
) -> AttributionDriver | None:
    pairs = ((previous.wti, current.wti), (previous.brent, current.brent))
    if not all(_usable(old) and _usable(new) for old, new in pairs):
        return None
    changes = [(old, new, new.value - old.value) for old, new in pairs]
    if any(change == 0 for _, _, change in changes):
        return None
    # Opposite WTI/Brent moves leave the inflation path unclassified.
    signs = {change > 0 for _, _, change in changes}
    if len(signs) != 1:
        return None
    direction = "supports_up" if next(iter(signs)) else "supports_down"
    previous_value = sum(old.value for old, _, _ in changes) / len(changes)
    current_value = sum(new.value for _, new, _ in changes) / len(changes)
    refs = _dedupe_refs(tuple(ref for old, new, _ in changes for ref in (*old.source_refs, *new.source_refs)))
    return AttributionDriver(
        factor="oil_inflation_path",
        direction=direction,
        rule_code="ATTR_OIL_INFLATION_PATH_V1",
        previous_value=round(previous_value, 8),
        current_value=round(current_value, 8),
        delta=round(current_value - previous_value, 8),
        delta_pct=_delta_pct(previous_value, current_value),
        previous_as_of=min(old.as_of for old, _, _ in changes).isoformat(),
        current_as_of=max(new.as_of for _, new, _ in changes).isoformat(),
        source_refs=refs,
    )


def _confirmed_event_drivers(
    current: FeatureSnapshotContract,
    previous: FeatureSnapshotContract,
    price_move: PriceMove,
) -> tuple[AttributionDriver, ...]:
    if (
        isinstance(current, FeatureSnapshotV2)
        and current.data_quality.event_attribution_readiness != "ready"
    ) or (
        price_move not in {"up", "down"}
        or current.official_events.freshness_status != "fresh"
        or current.official_events.quality_status != "accepted"
        or current.official_events.alignment_status != "aligned"
    ):
        return ()
    events = tuple(
        event
        for event in current.official_events.events
        if event.reaction_window_end is not None
        and previous.as_of < event.occurred_at <= event.reaction_window_end <= current.as_of
        and event.reaction_status == "confirmed"
        and event.reaction_asset == "XAUUSD"
        and event.reaction_return_pct is not None
        and abs(event.reaction_return_pct) >= _FLAT_RETURN_PCT
        and ((event.reaction_return_pct > 0) == (price_move == "up"))
        and bool(event.reaction_summary and event.reaction_summary.strip())
        and event.source_refs
        and event.reaction_source_refs
    )
    direction = "supports_up" if price_move == "up" else "supports_down"
    return tuple(
        AttributionDriver(
            factor="official_event",
            direction=direction,
            rule_code="ATTR_OFFICIAL_EVENT_REACTION_WINDOW_V1",
            previous_as_of=event.occurred_at.isoformat(),
            current_as_of=event.reaction_window_end.isoformat(),
            source_refs=_dedupe_refs((*event.source_refs, *event.reaction_source_refs)),
        )
        for event in events
    )


def _event_attribution_readiness_reasons(
    snapshot: FeatureSnapshotContract,
) -> tuple[str, ...]:
    if not isinstance(snapshot, FeatureSnapshotV2):
        return ()
    readiness = snapshot.data_quality.event_attribution_readiness
    if readiness == "ready":
        return ()
    return (f"EVENT_ATTRIBUTION_READINESS_{readiness.upper()}",)


def _usable(observation: VariableObservation) -> bool:
    return (
        observation.value is not None
        and observation.quality_status == "accepted"
        and observation.alignment_status == "aligned"
        and observation.freshness_status == "fresh"
    )


def _delta_pct(previous: float, current: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 8)


def _dedupe_refs(refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    unique: dict[tuple[object, object, object], SourceReference] = {}
    for ref in refs:
        unique.setdefault(_source_ref_key(ref), ref)
    return tuple(unique.values())


def _real10y_directional(snapshot: FeatureSnapshotContract) -> VariableObservation:
    """DFII10 is a cross-check only for v2 attribution drivers."""

    return snapshot.real10y_estimated if isinstance(snapshot, FeatureSnapshotV2) else snapshot.real10y


def _real10y_attribution_driver(
    previous: FeatureSnapshotContract, current: FeatureSnapshotContract
) -> AttributionDriver | None:
    if isinstance(current, FeatureSnapshotV2) != isinstance(previous, FeatureSnapshotV2):
        return None
    return _variable_driver(
        "real_yield",
        _real10y_directional(previous),
        _real10y_directional(current),
        inverse=True,
    )


def _real10y_schema_transition_reason(
    current: FeatureSnapshotContract, previous: FeatureSnapshotContract
) -> tuple[str, ...]:
    if isinstance(current, FeatureSnapshotV2) != isinstance(previous, FeatureSnapshotV2):
        return ("REAL10Y_SCHEMA_TRANSITION_NO_DELTA",)
    return ()


def _result(
    *,
    price_move: PriceMove,
    return_pct: float,
    explained_ratio: float,
    primary: tuple[AttributionDriver, ...],
    secondary: tuple[AttributionDriver, ...],
    counter: tuple[AttributionDriver, ...],
    status: AttributionStatus,
    source_refs: tuple[SourceReference, ...],
    current_snapshot_id: str,
    previous_snapshot_id: str,
    reason_codes: tuple[str, ...] = (),
) -> GoldPriceAttribution:
    return GoldPriceAttribution(
        current_snapshot_id=current_snapshot_id,
        previous_snapshot_id=previous_snapshot_id,
        price_move=price_move,
        return_pct=return_pct,
        explained_ratio=explained_ratio,
        primary_drivers=primary,
        secondary_drivers=secondary,
        counter_drivers=counter,
        unexplained_component=round(1.0 - explained_ratio, 8),
        attribution_status=status,
        source_refs=source_refs,
        reason_codes=reason_codes,
    )


# v2 is intentionally self-contained below.  In particular, do not route v1
# snapshots through these Decimal calculations: the v1 serialization is frozen.
_V2_QUANTUM = Decimal("0.00000001")
_V2_FACTOR_ORDER = {
    "real_yield": 0,
    "broad_dollar": 1,
    "breakeven": 2,
    "oil_inflation_path": 3,
    "official_event": 4,
}


class AttributionDriverV2(_FrozenOutput):
    factor: Literal["broad_dollar", "real_yield", "breakeven", "oil_inflation_path", "official_event"]
    direction: DriverDirection
    direction_sign: Literal[-1, 1]
    attribution_role: Literal["primary", "secondary", "counter", "filtered"]
    move_magnitude: Decimal = Field(ge=Decimal("0"))
    materiality_bucket: Literal["noise", "small", "material", "large"]
    materiality_threshold: Decimal = Field(gt=Decimal("0"))
    raw_ratio: Decimal = Field(ge=Decimal("0"))
    normalized_move: Decimal = Field(ge=Decimal("0"))
    normalization_cap: Decimal = Field(gt=Decimal("0"))
    factor_weight: Decimal = Field(ge=Decimal("0"))
    quality_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    freshness_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    contribution: Decimal
    rule_code: str = Field(min_length=1)
    previous_value: float | None = None
    current_value: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    previous_as_of: str | None = None
    current_as_of: str
    conditional_path: Literal["inflation_support", "opportunity_cost_conflict", "non_dominant"] | None = None
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _recompute_contribution(self) -> "AttributionDriverV2":
        materiality = evaluate_gold_materiality(
            factor={
                "real_yield": "real_yield",
                "broad_dollar": "broad_dollar",
                "breakeven": "breakeven",
                "oil_inflation_path": "oil",
                "official_event": "event_reaction",
            }[self.factor],  # type: ignore[arg-type]
            move_magnitude=self.move_magnitude,
            direction_sign=self.direction_sign,
            quality_status=(
                "accepted"
                if self.quality_weight == 1
                else "observe"
                if self.quality_weight == Decimal("0.5")
                else "blocked"
            ),
            alignment_status=(
                "aligned"
                if self.quality_weight in {Decimal("1"), Decimal("0.5")}
                else "misaligned"
            ),
            freshness_status=(
                "fresh"
                if self.freshness_weight == 1
                else "stale"
                if self.freshness_weight == Decimal("0.5")
                else "missing"
            ),
        )
        gated = self.conditional_path in {
            "opportunity_cost_conflict",
            "non_dominant",
        }
        expected = {
            "materiality_threshold": materiality.threshold,
            "raw_ratio": materiality.raw_ratio,
            "normalization_cap": materiality.normalization_cap,
            "materiality_bucket": materiality.bucket,
            "factor_weight": materiality.factor_weight,
            "quality_weight": materiality.quality_weight,
            "freshness_weight": materiality.freshness_weight,
            "normalized_move": Decimal("0") if gated else materiality.normalized_move,
            "contribution": Decimal("0E-8") if gated else materiality.contribution,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"{field_name} does not match driver derivation")
        if len({_source_ref_key(ref) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("driver source_refs must be deduplicated")
        return self


class GoldPriceAttributionV2(_FrozenOutput):
    policy_version: Literal["gold_price_attribution.v2"] = "gold_price_attribution.v2"
    materiality_policy_version: Literal["gold_attribution_materiality.v1"] = "gold_attribution_materiality.v1"
    current_snapshot_id: str = Field(min_length=1)
    previous_snapshot_id: str = Field(min_length=1)
    price_move: PriceMove
    return_pct: float
    support_contribution: Decimal = Field(ge=Decimal("0"))
    counter_contribution: Decimal = Field(ge=Decimal("0"))
    explained_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    unexplained_component: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    evidence_coverage_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    primary_drivers: tuple[AttributionDriverV2, ...]
    secondary_drivers: tuple[AttributionDriverV2, ...]
    counter_drivers: tuple[AttributionDriverV2, ...]
    filtered_drivers: tuple[AttributionDriverV2, ...]
    attribution_status: AttributionStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attribution_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_derived_field_injection(self) -> "GoldPriceAttributionV2":
        drivers = (*self.primary_drivers, *self.secondary_drivers, *self.counter_drivers, *self.filtered_drivers)
        price_sign = Decimal("1") if self.price_move == "up" else Decimal("-1") if self.price_move == "down" else Decimal("0")
        support = sum((max(price_sign * driver.contribution, Decimal("0")) for driver in drivers), Decimal("0")).quantize(_V2_QUANTUM)
        counter = sum((max(-price_sign * driver.contribution, Decimal("0")) for driver in drivers), Decimal("0")).quantize(_V2_QUANTUM)
        explained = max(Decimal("0"), min(Decimal("1"), support - counter)).quantize(_V2_QUANTUM)
        coverage = _v2_evidence_coverage(drivers)
        expected_status: AttributionStatus = (
            "confirmed_event"
            if explained > 0
            and any(driver.factor == "official_event" for driver in self.primary_drivers)
            else "cross_asset_consistent"
            if explained > 0
            else "unconfirmed"
        )
        if (
            self.support_contribution,
            self.counter_contribution,
            self.explained_ratio,
            self.unexplained_component,
            self.evidence_coverage_ratio,
            self.attribution_status,
        ) != (
            support,
            counter,
            explained,
            Decimal("1") - explained,
            coverage,
            expected_status,
        ):
            raise ValueError("attribution accounting does not match driver derivation")
        for values, role in (
            (self.primary_drivers, "primary"),
            (self.secondary_drivers, "secondary"),
            (self.counter_drivers, "counter"),
            (self.filtered_drivers, "filtered"),
        ):
            if any(driver.attribution_role != role for driver in values):
                raise ValueError("driver attribution_role does not match its output group")
            if tuple(values) != tuple(
                sorted(values, key=lambda driver: _V2_FACTOR_ORDER[driver.factor])
            ):
                raise ValueError("driver output groups must use stable factor order")
        if len({_source_ref_key(ref) for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("source_refs must be deduplicated")
        payload = self.model_dump(mode="json", exclude={"payload_hash", "attribution_id"})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if self.payload_hash != expected_hash or self.attribution_id != f"gold_price_attribution.v2:{expected_hash}":
            raise ValueError("attribution identity does not match derived payload")
        return self

    @classmethod
    def evaluate(
        cls, current: FeatureSnapshotV2, previous: FeatureSnapshotContract | None
    ) -> "GoldPriceAttributionV2":
        return _attribute_gold_price_v2(current, previous)


def _v2_worst_quality(
    previous: VariableObservation, current: VariableObservation
) -> Literal["accepted", "observe", "blocked"]:
    values = {previous.quality_status, current.quality_status}
    if "blocked" in values:
        return "blocked"
    if "observe" in values:
        return "observe"
    return "accepted"


def _v2_worst_alignment(
    previous: VariableObservation, current: VariableObservation
) -> Literal["aligned", "unknown", "misaligned"]:
    values = {previous.alignment_status, current.alignment_status}
    if "misaligned" in values:
        return "misaligned"
    if "unknown" in values:
        return "unknown"
    return "aligned"


def _v2_worst_freshness(
    previous: VariableObservation, current: VariableObservation
) -> Literal["fresh", "stale", "missing"]:
    values = {previous.freshness_status, current.freshness_status}
    if "missing" in values:
        return "missing"
    if "stale" in values:
        return "stale"
    return "fresh"


def _v2_evidence_coverage(
    drivers: tuple[AttributionDriverV2, ...],
) -> Decimal:
    core_factors = {"real_yield", "broad_dollar", "breakeven"}
    effective_weight = sum(
        (
            driver.factor_weight
            * driver.quality_weight
            * driver.freshness_weight
            for driver in drivers
            if driver.factor in core_factors
        ),
        Decimal("0"),
    )
    return min(Decimal("1"), effective_weight).quantize(
        _V2_QUANTUM, rounding=ROUND_HALF_EVEN
    )


def _v2_driver(
    *, factor: Literal["broad_dollar", "real_yield", "breakeven", "oil_inflation_path", "official_event"], materiality_factor: Literal["broad_dollar", "real_yield", "breakeven", "oil", "event_reaction"], previous: VariableObservation | None,
    current: VariableObservation | None, inverse: bool, conditional_path: Literal["inflation_support", "opportunity_cost_conflict", "non_dominant"] | None = None,
    event_return: float | None = None, event_refs: tuple[SourceReference, ...] = (), event_as_of: str | None = None,
) -> AttributionDriverV2 | None:
    if event_return is None:
        if previous is None or current is None or previous.value is None or current.value is None:
            return None
        delta = current.value - previous.value
        # Observations are float-backed at the boundary; normalize their
        # declared eight-decimal policy precision before Decimal materiality.
        magnitude = abs(Decimal(str(round(delta, 8))))
        raw_sign = 1 if delta >= 0 else -1
        direction_sign = -raw_sign if inverse else raw_sign
        refs = _dedupe_refs((*previous.source_refs, *current.source_refs))
        quality = _v2_worst_quality(previous, current)
        alignment = _v2_worst_alignment(previous, current)
        freshness = _v2_worst_freshness(previous, current)
        previous_value, current_value = previous.value, current.value
        previous_as_of, current_as_of = previous.as_of.isoformat(), current.as_of.isoformat()
    else:
        magnitude = abs(Decimal(str(event_return)))
        direction_sign = 1 if event_return >= 0 else -1
        refs = _dedupe_refs(event_refs)
        quality, alignment, freshness = "accepted", "aligned", "fresh"
        previous_value = current_value = delta = None
        previous_as_of = event_as_of
        current_as_of = event_as_of or current.as_of.isoformat()  # pragma: no cover
    decision = evaluate_gold_materiality(
        factor=materiality_factor, move_magnitude=magnitude, direction_sign=direction_sign,
        quality_status=quality, alignment_status=alignment, freshness_status=freshness,
    )
    return AttributionDriverV2(
        factor=factor, direction="supports_up" if direction_sign == 1 else "supports_down",
        direction_sign=direction_sign, attribution_role="filtered", move_magnitude=decision.move_magnitude,
        materiality_bucket=decision.bucket, materiality_threshold=decision.threshold,
        raw_ratio=decision.raw_ratio, normalized_move=decision.normalized_move,
        normalization_cap=decision.normalization_cap,
        factor_weight=decision.factor_weight, quality_weight=decision.quality_weight,
        freshness_weight=decision.freshness_weight, contribution=decision.contribution,
        rule_code=f"ATTR_{factor.upper()}_V2", previous_value=previous_value, current_value=current_value,
        delta=round(delta, 8) if delta is not None else None,
        delta_pct=_delta_pct(previous_value, current_value) if previous_value is not None else None,
        previous_as_of=previous_as_of, current_as_of=current_as_of, conditional_path=conditional_path,
        source_refs=refs,
    )


def _v2_with_role(driver: AttributionDriverV2, price_move: PriceMove) -> AttributionDriverV2:
    if driver.contribution == 0 or price_move not in {"up", "down"}:
        return driver
    price_sign = 1 if price_move == "up" else -1
    role: Literal["primary", "counter", "filtered"] = (
        "primary" if price_sign * driver.contribution > 0 else "counter"
    )
    return driver.model_copy(update={"attribution_role": role})


def _v2_oil_driver(
    current: FeatureSnapshotV2, previous: FeatureSnapshotContract
) -> AttributionDriverV2 | None:
    if not isinstance(previous, FeatureSnapshotV2):
        return None
    wti = _v2_driver(factor="oil_inflation_path", materiality_factor="oil", previous=previous.wti, current=current.wti, inverse=False)
    brent = _v2_driver(factor="oil_inflation_path", materiality_factor="oil", previous=previous.brent, current=current.brent, inverse=False)
    if wti is None or brent is None:
        return None
    if wti.delta == 0 or brent.delta == 0:
        return None
    same_direction = wti.direction_sign == brent.direction_sign
    both_material = wti.materiality_bucket in {"material", "large"} and brent.materiality_bucket in {"material", "large"}
    # The aggregate move uses the two benchmark changes, but eligibility is
    # deliberately stricter than the aggregate's own materiality alone.
    previous_value = (previous.wti.value + previous.brent.value) / 2  # type: ignore[operator]
    current_value = (current.wti.value + current.brent.value) / 2  # type: ignore[operator]
    previous_oil = VariableObservation.model_validate(
        {
            **previous.wti.model_dump(mode="python"),
            "value": previous_value,
            "quality_status": _v2_worst_quality(previous.wti, previous.brent),
            "alignment_status": _v2_worst_alignment(previous.wti, previous.brent),
            "freshness_status": _v2_worst_freshness(previous.wti, previous.brent),
            "source_refs": _dedupe_refs(
                (*previous.wti.source_refs, *previous.brent.source_refs)
            ),
        }
    )
    current_oil = VariableObservation.model_validate(
        {
            **current.wti.model_dump(mode="python"),
            "value": current_value,
            "quality_status": _v2_worst_quality(current.wti, current.brent),
            "alignment_status": _v2_worst_alignment(current.wti, current.brent),
            "freshness_status": _v2_worst_freshness(current.wti, current.brent),
            "source_refs": _dedupe_refs(
                (*current.wti.source_refs, *current.brent.source_refs)
            ),
        }
    )
    oil = _v2_driver(
        factor="oil_inflation_path",
        materiality_factor="oil",
        previous=previous_oil,
        current=current_oil,
        inverse=False,
    )
    assert oil is not None
    breakeven = _v2_driver(factor="breakeven", materiality_factor="breakeven", previous=previous.t10yie, current=current.t10yie, inverse=False)
    inflation_support = bool(
        breakeven
        and both_material
        and same_direction
        and wti.contribution
        and brent.contribution
        and breakeven.materiality_bucket in {"material", "large"}
        and breakeven.contribution
        and breakeven.direction_sign == oil.direction_sign
    )
    real_yield = _v2_driver(
        factor="real_yield",
        materiality_factor="real_yield",
        previous=previous.real10y_estimated,
        current=current.real10y_estimated,
        inverse=True,
    )
    opportunity_cost_conflict = bool(
        real_yield
        and real_yield.materiality_bucket in {"material", "large"}
        and real_yield.contribution
        and real_yield.direction_sign == -oil.direction_sign
    )
    if inflation_support and opportunity_cost_conflict:
        return oil.model_copy(update={"contribution": Decimal("0E-8"), "normalized_move": Decimal("0"), "conditional_path": "opportunity_cost_conflict"})
    if inflation_support:
        return oil.model_copy(update={"conditional_path": "inflation_support"})
    return oil.model_copy(update={"contribution": Decimal("0E-8"), "normalized_move": Decimal("0"), "conditional_path": "non_dominant"})


def _attribute_gold_price_v2(
    current: FeatureSnapshotV2, previous: FeatureSnapshotContract | None
) -> GoldPriceAttributionV2:
    refs = _dedupe_refs((*current.xauusd_spot.source_refs, *(previous.xauusd_spot.source_refs if previous else ())))
    price_move, return_pct = _price_move(current, previous) if previous is not None else ("unavailable", 0.0)
    reasons: tuple[str, ...] = ()
    candidates: list[AttributionDriverV2] = []
    if not feature_snapshot_integrity_valid(current) or (previous is not None and not feature_snapshot_integrity_valid(previous)):
        reasons = ("FEATURE_SNAPSHOT_DERIVATION_INVALID",)
    elif previous is None:
        reasons = ("PREVIOUS_FEATURE_SNAPSHOT_MISSING",)
    elif previous.as_of > current.as_of:
        reasons = ("PREVIOUS_SNAPSHOT_AFTER_CURRENT",)
        price_move, return_pct = "unavailable", 0.0
    else:
        if not isinstance(previous, FeatureSnapshotV2):
            reasons = ("REAL10Y_SCHEMA_TRANSITION_NO_DELTA",)
        # Historical snapshots naturally age into blocked readiness.  Their
        # accepted, aligned observations remain valid comparison evidence; a
        # blocked *current* snapshot alone fails closed.
        if current.data_quality.analysis_readiness == "blocked":
            reasons = (
                *reasons,
                "ANALYSIS_INPUT_READINESS_BLOCKED",
                *_event_attribution_readiness_reasons(current),
            )
        else:
            if isinstance(previous, FeatureSnapshotV2):
                for factor, materiality, old, new, inverse in (
                    ("real_yield", "real_yield", previous.real10y_estimated, current.real10y_estimated, True),
                    ("broad_dollar", "broad_dollar", previous.broad_dollar, current.broad_dollar, True),
                    ("breakeven", "breakeven", previous.t10yie, current.t10yie, False),
                ):
                    driver = _v2_driver(factor=factor, materiality_factor=materiality, previous=old, current=new, inverse=inverse)  # type: ignore[arg-type]
                    if driver:
                        candidates.append(driver)
                oil = _v2_oil_driver(current, previous)
                if oil:
                    candidates.append(oil)
            else:
                for factor, materiality, old, new, inverse in (
                    ("broad_dollar", "broad_dollar", previous.broad_dollar, current.broad_dollar, True),
                    ("breakeven", "breakeven", previous.t10yie, current.t10yie, False),
                ):
                    driver = _v2_driver(factor=factor, materiality_factor=materiality, previous=old, current=new, inverse=inverse)  # type: ignore[arg-type]
                    if driver:
                        candidates.append(driver)
            if current.data_quality.event_attribution_readiness == "ready" and price_move in {"up", "down"}:
                for event in current.official_events.events:
                    if (previous.as_of < event.occurred_at <= (event.reaction_window_end or previous.as_of) <= current.as_of and event.reaction_status == "confirmed" and event.reaction_asset == "XAUUSD" and event.reaction_return_pct is not None and event.source_refs and event.reaction_source_refs):
                        event_driver = _v2_driver(factor="official_event", materiality_factor="event_reaction", previous=None, current=None, inverse=False, event_return=event.reaction_return_pct, event_refs=(*event.source_refs, *event.reaction_source_refs), event_as_of=event.reaction_window_end.isoformat() if event.reaction_window_end else None)
                        if event_driver:
                            candidates.append(event_driver)
            else:
                reasons = (*reasons, *_event_attribution_readiness_reasons(current))
    candidates = [_v2_with_role(driver, price_move) for driver in candidates]
    candidates.sort(key=lambda driver: _V2_FACTOR_ORDER[driver.factor])
    primary = tuple(driver for driver in candidates if driver.attribution_role == "primary")
    counter = tuple(driver for driver in candidates if driver.attribution_role == "counter")
    filtered = tuple(driver for driver in candidates if driver.attribution_role == "filtered")
    all_refs = _dedupe_refs((*refs, *(ref for driver in candidates for ref in driver.source_refs)))
    return _v2_result(price_move=price_move, return_pct=return_pct, primary=primary, counter=counter, filtered=filtered, source_refs=all_refs, current_snapshot_id=current.snapshot_id, previous_snapshot_id=previous.snapshot_id if previous else "missing", reason_codes=reasons)


def _v2_result(**values: object) -> GoldPriceAttributionV2:
    primary = values["primary"]
    counter = values["counter"]
    filtered = values["filtered"]
    assert isinstance(primary, tuple) and isinstance(counter, tuple) and isinstance(filtered, tuple)
    price_move = values["price_move"]
    assert isinstance(price_move, str)
    all_drivers = (*primary, *counter, *filtered)
    sign = Decimal("1") if price_move == "up" else Decimal("-1") if price_move == "down" else Decimal("0")
    support = sum((max(sign * driver.contribution, Decimal("0")) for driver in all_drivers), Decimal("0")).quantize(_V2_QUANTUM)
    opposing = sum((max(-sign * driver.contribution, Decimal("0")) for driver in all_drivers), Decimal("0")).quantize(_V2_QUANTUM)
    explained = max(Decimal("0"), min(Decimal("1"), support - opposing)).quantize(_V2_QUANTUM)
    base = {
        **{key: value for key, value in values.items() if key not in {"primary", "counter", "filtered"}},
        "primary_drivers": primary,
        "secondary_drivers": (),
        "counter_drivers": counter,
        "filtered_drivers": filtered,
        "support_contribution": support,
        "counter_contribution": opposing,
        "explained_ratio": explained,
        "unexplained_component": Decimal("1") - explained,
        "evidence_coverage_ratio": _v2_evidence_coverage(all_drivers),
        "attribution_status": (
            "confirmed_event"
            if explained > 0
            and any(driver.factor == "official_event" for driver in primary)
            else "cross_asset_consistent"
            if explained > 0
            else "unconfirmed"
        ),
    }
    payload = GoldPriceAttributionV2.model_construct(**base).model_dump(mode="json", exclude={"payload_hash", "attribution_id"})
    payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return GoldPriceAttributionV2(**base, payload_hash=payload_hash, attribution_id=f"gold_price_attribution.v2:{payload_hash}")
