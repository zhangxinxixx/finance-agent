"""Deterministic daily XAUUSD price-attribution policy.

The policy intentionally makes no claim for data that is unavailable or whose
cross-asset evidence is incomplete.  It consumes only two immutable feature
snapshots and returns an immutable, audit-ready attribution record.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.gold_policy.schemas import FeatureSnapshot, SourceReference, VariableObservation


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
    current: FeatureSnapshot,
    previous: FeatureSnapshot | None,
) -> GoldPriceAttribution:
    """Attribute the XAUUSD close move using only accepted, aligned inputs."""

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
        )

    factor_drivers = tuple(
        driver
        for driver in (
            _variable_driver("broad_dollar", previous.broad_dollar, current.broad_dollar, inverse=True),
            _variable_driver("real_yield", previous.real10y, current.real10y, inverse=True),
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
    )


def _price_move(current: FeatureSnapshot, previous: FeatureSnapshot) -> tuple[PriceMove, float]:
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


def _oil_driver(previous: FeatureSnapshot, current: FeatureSnapshot) -> AttributionDriver | None:
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
    current: FeatureSnapshot,
    previous: FeatureSnapshot,
    price_move: PriceMove,
) -> tuple[AttributionDriver, ...]:
    if (
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
