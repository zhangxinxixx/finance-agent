from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.attribution_policy import (
    AttributionDriverV2,
    GoldPriceAttributionV2,
    attribute_gold_price,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"
CASES = FIXTURES / "attribution_v2" / "contract_cases.json"
QUANTUM = Decimal("0.00000001")
OBSERVATION_FIELDS = (
    "xauusd_spot",
    "gc_futures",
    "us02y",
    "us10y",
    "us30y",
    "t10yie",
    "real10y_direct",
    "broad_dollar",
    "wti",
    "brent",
    "etf_flow",
    "cot",
    "cme_options_regime",
)


def _bundle() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _case(case_id: str) -> dict:
    return next(case for case in _bundle()["cases"] if case["id"] == case_id)


def _set_path(payload: dict, dotted_key: str, value: object) -> None:
    target = payload
    path = dotted_key.split(".")
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def _clamp_reference_times(value: object, cutoff: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_refs", "reaction_source_refs"} and isinstance(child, list):
                for reference in child:
                    reference["retrieved_at"] = cutoff
            else:
                _clamp_reference_times(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            _clamp_reference_times(child, cutoff)


def _v2_payload(*, current: bool, changes: dict[str, object] | None = None) -> dict:
    bundle = _bundle()
    base = bundle["base_payload"]
    payload = json.loads((FIXTURES / base["source_fixture"]).read_text(encoding="utf-8"))
    direct = payload.pop("real10y")
    direct["market_role"] = "real_yield_direct"
    payload.update(schema_version="feature_snapshot.v2", real10y_direct=direct)
    if current:
        cutoff = base["current_as_of"]
        payload["as_of"] = cutoff
        for field in OBSERVATION_FIELDS:
            payload[field]["as_of"] = cutoff
        payload["official_events"]["as_of"] = cutoff
        _clamp_reference_times(payload, cutoff)
        for dotted_key, value in base["common_changes"].items():
            _set_path(payload, dotted_key, value)
        for dotted_key, value in (changes or {}).items():
            _set_path(payload, dotted_key, value)
    return payload


def _snapshots(changes: dict[str, object] | None = None):
    previous = build_feature_snapshot(_v2_payload(current=False))
    current = build_feature_snapshot(_v2_payload(current=True, changes=changes))
    return current, previous


def _drivers(result) -> tuple:
    return (
        *result.primary_drivers,
        *result.secondary_drivers,
        *result.counter_drivers,
        *result.filtered_drivers,
    )


def _assert_driver_is_recomputable(driver) -> None:
    expected = (
        Decimal(driver.direction_sign)
        * driver.normalized_move
        * driver.factor_weight
        * driver.quality_weight
        * driver.freshness_weight
    ).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
    assert driver.contribution == expected
    assert driver.materiality_threshold > 0
    with localcontext() as context:
        context.prec = 50
        assert (
            driver.raw_ratio
            == driver.move_magnitude / driver.materiality_threshold
        )
    assert driver.source_refs


def _assert_result_accounting(result) -> None:
    drivers = _drivers(result)
    for driver in drivers:
        _assert_driver_is_recomputable(driver)
    price_sign = Decimal("1") if result.price_move == "up" else Decimal("-1")
    support = sum(
        (max(price_sign * driver.contribution, Decimal("0")) for driver in drivers),
        Decimal("0"),
    ).quantize(QUANTUM)
    counter = sum(
        (max(-price_sign * driver.contribution, Decimal("0")) for driver in drivers),
        Decimal("0"),
    ).quantize(QUANTUM)
    explained = max(Decimal("0"), min(Decimal("1"), support - counter)).quantize(QUANTUM)
    assert result.support_contribution == support
    assert result.counter_contribution == counter
    assert result.explained_ratio == explained
    assert result.unexplained_component == Decimal("1") - explained


def test_v2_noise_is_filtered_and_accounting_is_explicit() -> None:
    case = _case("noise_filtered")
    current, previous = _snapshots(case["changes"])
    result = attribute_gold_price(current, previous)
    expected = case["expected"]

    assert isinstance(result, GoldPriceAttributionV2)
    assert result.policy_version == "gold_price_attribution.v2"
    assert result.materiality_policy_version == "gold_attribution_materiality.v1"
    assert result.support_contribution == Decimal(expected["support_contribution"])
    assert result.counter_contribution == Decimal(expected["counter_contribution"])
    assert result.explained_ratio == Decimal(expected["explained_ratio"])
    assert result.unexplained_component == Decimal(expected["unexplained_component"])
    assert result.evidence_coverage_ratio == Decimal(expected["evidence_coverage_ratio"])
    actual_filtered = {
        driver.factor: driver.materiality_bucket for driver in result.filtered_drivers
    }
    assert expected["filtered"].items() <= actual_filtered.items()
    _assert_result_accounting(result)


def test_v2_counter_contribution_reduces_explained_ratio_in_stable_order() -> None:
    case = _case("material_support_with_counter")
    current, previous = _snapshots(case["changes"])
    result = attribute_gold_price(current, previous)
    expected = case["expected"]

    assert result.support_contribution == Decimal(expected["support_contribution"])
    assert result.counter_contribution == Decimal(expected["counter_contribution"])
    assert result.explained_ratio == Decimal(expected["explained_ratio"])
    assert result.unexplained_component == Decimal(expected["unexplained_component"])
    assert result.evidence_coverage_ratio == Decimal(expected["evidence_coverage_ratio"])
    assert [driver.factor for driver in _drivers(result)] == expected["ordered_factors"]
    assert [driver.attribution_role for driver in result.counter_drivers] == ["counter"]
    _assert_result_accounting(result)


@pytest.mark.parametrize(
    "variant_name",
    ("inflation_support", "opportunity_cost_conflict", "non_dominant"),
)
def test_v2_oil_uses_conditional_paths(variant_name: str) -> None:
    variant = _case("oil_conditional_paths")["variants"][variant_name]
    current, previous = _snapshots(variant["changes"])
    result = attribute_gold_price(current, previous)
    oil = next(driver for driver in _drivers(result) if driver.factor == "oil_inflation_path")

    assert oil.conditional_path == variant["expected_path"]
    assert oil.contribution == Decimal(variant["expected_oil_contribution"])
    if variant_name != "inflation_support":
        assert oil.attribution_role == "filtered"
    else:
        assert {ref.reference for ref in oil.source_refs} >= {
            "contract://bullish/wti",
            "contract://bullish/brent",
        }
    _assert_result_accounting(result)


def test_v2_micro_real_yield_move_does_not_trigger_oil_conflict() -> None:
    current, previous = _snapshots(
        {
            "us10y.value": 4.65,
            "t10yie.value": 2.38,
            "wti.value": 78.4,
            "brent.value": 81.3,
        }
    )
    result = attribute_gold_price(current, previous)
    oil = next(driver for driver in _drivers(result) if driver.factor == "oil_inflation_path")

    assert oil.conditional_path == "inflation_support"
    assert oil.contribution == Decimal("0.15000000")


def test_v2_coverage_uses_effective_core_factor_weights() -> None:
    current, previous = _snapshots(
        {
            "broad_dollar.value": 120.8,
            "broad_dollar.quality_status": "observe",
        }
    )
    result = attribute_gold_price(current, previous)

    assert result.evidence_coverage_ratio == Decimal("0.82500000")


def test_v2_flat_price_move_cannot_assign_directional_driver_roles() -> None:
    current, previous = _snapshots(
        {
            "xauusd_spot.value": 2704.0,
            "broad_dollar.value": 120.6,
        }
    )
    result = attribute_gold_price(current, previous)

    assert result.price_move == "flat"
    assert not result.primary_drivers
    assert not result.counter_drivers
    assert result.filtered_drivers
    assert result.explained_ratio == Decimal("0E-8")


@pytest.mark.parametrize("variant_name", ("material", "micro"))
def test_v2_event_reaction_has_an_independent_materiality_threshold(variant_name: str) -> None:
    variant = _case("event_reaction_materiality")["variants"][variant_name]
    event = {
        "event_id": f"fed-{variant_name}",
        "title": "FOMC policy statement",
        "occurred_at": "2025-01-21T19:00:00Z",
        "reaction_window_end": "2025-01-21T20:00:00Z",
        "reaction_summary": "Structured XAUUSD reaction window.",
        "reaction_asset": "XAUUSD",
        "reaction_return_pct": variant["reaction_return_pct"],
        "reaction_status": "confirmed",
        "source_refs": [
            {
                "source": "fixture",
                "reference": f"contract://event/{variant_name}",
                "retrieved_at": "2025-01-21T21:00:00Z"
            }
        ],
        "reaction_source_refs": [
            {
                "source": "fixture",
                "reference": f"contract://event/{variant_name}/reaction",
                "retrieved_at": "2025-01-21T21:00:00Z"
            }
        ]
    }
    current, previous = _snapshots({"official_events.events": [event]})
    result = attribute_gold_price(current, previous)
    driver = next(driver for driver in _drivers(result) if driver.factor == "official_event")

    assert driver.materiality_bucket == variant["expected_bucket"]
    assert driver.contribution == Decimal(variant["expected_contribution"])
    assert driver.attribution_role == variant["expected_role"]
    _assert_result_accounting(result)


def test_v2_identity_is_stable_and_derived_values_cannot_be_injected() -> None:
    case = _case("stable_identity_and_injection_guards")
    current, previous = _snapshots(case["changes"])
    results = [attribute_gold_price(current, previous) for _ in range(100)]
    result = results[0]
    serialized = result.model_dump_json()

    assert result.policy_version == case["expected"]["policy_version"]
    assert result.materiality_policy_version == case["expected"]["materiality_policy_version"]
    assert len(result.payload_hash) == 64
    assert result.attribution_id.startswith("gold_price_attribution.v2:")
    assert {item.model_dump_json() for item in results} == {serialized}
    assert {item.payload_hash for item in results} == {result.payload_hash}
    assert {item.attribution_id for item in results} == {result.attribution_id}
    assert GoldPriceAttributionV2.model_validate(result.model_dump(mode="python")) == result

    payload = result.model_dump(mode="python")
    with pytest.raises(ValidationError):
        GoldPriceAttributionV2.model_validate(
            {**payload, "explained_ratio": result.explained_ratio + Decimal("0.01")}
        )
    with pytest.raises(ValidationError):
        GoldPriceAttributionV2.model_validate(
            {
                **payload,
                "evidence_coverage_ratio": result.evidence_coverage_ratio
                - Decimal("0.01"),
            }
        )
    with pytest.raises(ValidationError):
        GoldPriceAttributionV2.model_validate({**payload, "payload_hash": "0" * 64})
    with pytest.raises(ValidationError):
        GoldPriceAttributionV2.model_validate({**payload, "attribution_id": "caller-supplied"})

    driver_payload = _drivers(result)[0].model_dump(mode="python")
    with pytest.raises(ValidationError):
        AttributionDriverV2.model_validate(
            {
                **driver_payload,
                "raw_ratio": driver_payload["raw_ratio"] + Decimal("0.01"),
            }
        )
